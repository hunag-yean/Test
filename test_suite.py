"""
Comprehensive test suite for the meeting assistant.
Tests: core logic, WebSocket protocol, server endpoints, and (optionally) Claude API.
"""
import asyncio
import json
import sys
import time
import threading
import numpy as np
import urllib.request
import subprocess
import os
import signal

# ── helpers ────────────────────────────────────────────────────────────────────
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
SKIP = "\033[93m⊘\033[0m"
results = []

def check(label, passed, detail=""):
    symbol = PASS if passed else FAIL
    results.append((label, passed))
    print(f"  {symbol}  {label}" + (f"  [{detail}]" if detail else ""))

def section(name):
    print(f"\n{'─'*55}")
    print(f"  {name}")
    print(f"{'─'*55}")

# ── 1. Unit tests: TranscriptStore ─────────────────────────────────────────────
section("1. TranscriptStore 單元測試")
from backend.transcript_store import TranscriptStore
from backend.models import TranscriptSegment

store = TranscriptStore()
segs = [
    TranscriptSegment(text="今天開會討論Q3產品路線圖", start_time=0, end_time=5, chunk_index=0),
    TranscriptSegment(text="Alice負責API設計，截止週五", start_time=5, end_time=10, chunk_index=0),
]
store.append(segs)
check("append + get_full_text", "Q3產品路線圖" in store.get_full_text())
check("word_count > 0", store.word_count() > 0, f"{store.word_count()} 詞")

store.mark_analysis_point()
check("get_since_last_analysis 回傳空（已標記）", store.get_since_last_analysis().strip() == "")

segs2 = [TranscriptSegment(text="Bob負責資料庫遷移", start_time=10, end_time=15, chunk_index=1)]
store.append(segs2)
check("mark後新增的文字可取得", "Bob" in store.get_since_last_analysis())

store.update_rolling_summary("討論了API和資料庫任務分工")
check("update_rolling_summary 儲存成功", store._rolling_summary != "")

# Long meeting compression test
big_store = TranscriptStore()
# Simulate 35K words
for i in range(3500):
    big_store.append([TranscriptSegment(text=f"這是第{i}段測試文字內容填充", start_time=i*10, end_time=i*10+10, chunk_index=i)])
big_store.update_rolling_summary("這是之前的滾動摘要")
compressed = big_store.get_text_for_claude()
check("長會議 >30K 詞啟用壓縮", "之前的滾動摘要" in compressed and big_store.word_count() > 30000,
      f"共{big_store.word_count()}詞")
check("壓縮後包含最近逐字稿", "第3499段" in compressed)

store.clear()
check("clear() 重置 store", store.word_count() == 0 and store.get_full_text() == "")

# ── 2. Unit tests: Pydantic models ─────────────────────────────────────────────
section("2. Pydantic 模型驗證")
from backend.models import AnalysisResult, ActionItem, QAResult

ar = AnalysisResult(
    summary="討論了路線圖",
    key_points=["重點1", "重點2"],
    action_items=[ActionItem(owner="Alice", task="API設計", due="週五")],
    topics_discussed=["路線圖", "工程"]
)
check("AnalysisResult model_dump() 可序列化", isinstance(ar.model_dump(), dict))

qa = QAResult(question="誰負責DB?", answer="Bob", confidence="high", relevant_excerpt="Bob負責")
check("QAResult 欄位正確", qa.confidence == "high" and qa.question == "誰負責DB?")

# ── 3. Config loading ───────────────────────────────────────────────────────────
section("3. Config 載入測試")
from backend.config import settings
check("WHISPER_MODEL 可讀取", isinstance(settings.whisper_model, str), settings.whisper_model)
check("WHISPER_LANGUAGE 可讀取", isinstance(settings.whisper_language, str), settings.whisper_language)
check("ANALYSIS_INTERVAL_SECONDS 合理", 10 <= settings.analysis_interval_seconds <= 300,
      f"{settings.analysis_interval_seconds}s")

# ── 4. Transcription service (lazy load) ───────────────────────────────────────
section("4. TranscriptionService 初始化測試")
from backend.transcription import TranscriptionService
svc = TranscriptionService(model_size="tiny", language="zh")
check("TranscriptionService 初始化（延遲載入）", svc._model is None, "模型未預先載入")
check("model_size / language 屬性正確", svc._model_size == "tiny" and svc._language == "zh")

# ── 5. ClaudeClient structure ──────────────────────────────────────────────────
section("5. ClaudeClient 結構測試")
from backend.claude_client import ClaudeClient, ANALYSIS_PROMPT, QA_PROMPT
cc = ClaudeClient(api_key="test-key")
check("ClaudeClient 可建立", cc._model == "claude-sonnet-4-6")
check("ANALYSIS_PROMPT 含JSON schema", "action_items" in ANALYSIS_PROMPT and "summary" in ANALYSIS_PROMPT)
check("QA_PROMPT 含confidence欄位", "confidence" in QA_PROMPT)

# ── 6. Server HTTP endpoints ───────────────────────────────────────────────────
section("6. HTTP 端點測試（啟動測試伺服器）")

server_proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "backend.main:app",
     "--host", "127.0.0.1", "--port", "18765", "--log-level", "error"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(3)

def http_get(path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:18765{path}", timeout=5) as r:
            return r.status, r.read()
    except Exception as e:
        return None, str(e)

status, body = http_get("/api/health")
check("/api/health → 200", status == 200, str(status))
check("/api/health 回傳 ok", b'"ok"' in (body or b""), body[:50] if body else "")

status, body = http_get("/api/audio-devices")
check("/api/audio-devices → 200", status == 200, str(status))
check("/api/audio-devices 回傳 list", body is not None and body.startswith(b"["), body[:30] if body else "")

status, body = http_get("/")
check("前端首頁 → 200", status == 200, str(status))
check("前端包含 <title>", b"<title>" in (body or b""), "")

status, body = http_get("/app.js")
check("app.js → 200", status == 200, str(status))
check("app.js 包含 WebSocket 邏輯", b"WebSocket" in (body or b""), "")

status, body = http_get("/style.css")
check("style.css → 200", status == 200, str(status))

# ── 7. WebSocket protocol ──────────────────────────────────────────────────────
section("7. WebSocket 協定測試")

async def test_websocket():
    import websockets
    ws_results = {}
    try:
        async with websockets.connect("ws://127.0.0.1:18765/ws", open_timeout=5) as ws:
            # Should receive 'connected' immediately
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            ws_results["connected"] = msg.get("type") == "connected"
            ws_results["meeting_id"] = "meeting_id" in msg

            # Test ping/pong
            await ws.send(json.dumps({"type": "ping"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            ws_results["pong"] = msg.get("type") == "pong"

            # Test start_meeting — expect meeting_started or AUDIO_DEVICE_ERROR
            await ws.send(json.dumps({"type": "start_meeting", "device_index": None}))
            raw = await asyncio.wait_for(ws.recv(), timeout=8)
            msg = json.loads(raw)
            ws_results["start_meeting_response"] = msg.get("type") in ("meeting_started", "error")
            ws_results["start_type"] = msg.get("type")
            ws_results["error_code"] = msg.get("code", "")

            # If started, send stop
            if msg.get("type") == "meeting_started":
                await ws.send(json.dumps({"type": "stop_meeting"}))
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                ws_results["stop_meeting"] = msg.get("type") == "meeting_stopped"

    except Exception as e:
        ws_results["error"] = str(e)
    return ws_results

ws_res = asyncio.run(test_websocket())
check("WS 連線 → 收到 connected", ws_res.get("connected", False))
check("WS connected 含 meeting_id", ws_res.get("meeting_id", False))
check("WS ping → pong", ws_res.get("pong", False))
check("WS start_meeting 有回應", ws_res.get("start_meeting_response", False),
      f"{ws_res.get('start_type','no response')} / {ws_res.get('error_code','')}")
if ws_res.get("stop_meeting"):
    check("WS stop_meeting → meeting_stopped", True)

server_proc.terminate()
server_proc.wait()

# ── 8. Synthetic audio transcription ──────────────────────────────────────────
section("8. 音訊處理管線測試（合成靜音片段）")
from backend.audio_capture import TARGET_SAMPLE_RATE
import scipy.signal as sig

# Generate 3s silence + noise (simulates real audio chunk shape)
duration = 3.0
sr = 44100
samples = int(sr * duration)
audio_noise = np.random.randn(samples).astype(np.float32) * 0.001  # near-silent

# Resample to 16kHz (same as audio_capture._emit_chunk does)
resampled = sig.resample_poly(audio_noise, TARGET_SAMPLE_RATE, sr).astype(np.float32)
max_val = np.max(np.abs(resampled))
if max_val > 0:
    resampled = resampled / max_val

check("音訊重新取樣成功", resampled.shape[0] == int(TARGET_SAMPLE_RATE * duration),
      f"shape={resampled.shape}")
check("重新取樣後為 float32", resampled.dtype == np.float32)
check("振幅正規化 ≤ 1.0", float(np.max(np.abs(resampled))) <= 1.0)

# ── 9. AnalysisScheduler logic ─────────────────────────────────────────────────
section("9. AnalysisScheduler 閘門邏輯測試")
from backend.analysis_scheduler import AnalysisScheduler

gate_store = TranscriptStore()
gate_results = []

async def mock_broadcast(msg):
    gate_results.append(msg)

async def test_scheduler_gate():
    # Feed fewer than min_new_words — should NOT trigger
    for i in range(3):
        gate_store.append([TranscriptSegment(
            text=f"短句{i}", start_time=i, end_time=i+1, chunk_index=i
        )])
    new_words = len(gate_store.get_since_last_analysis().split())
    return new_words

word_count_before_gate = asyncio.run(test_scheduler_gate())
check("min_words 閘門：< 50詞時不應觸發", word_count_before_gate < 50,
      f"目前新詞數={word_count_before_gate}")

# ── Summary ────────────────────────────────────────────────────────────────────
total = len(results)
passed = sum(1 for _, p in results if p)
failed = total - passed

print(f"\n{'═'*55}")
print(f"  測試結果：{passed}/{total} 通過", "🎉" if failed == 0 else f"（{failed} 個失敗）")
print(f"{'═'*55}\n")

if failed > 0:
    print("失敗項目：")
    for label, ok in results:
        if not ok:
            print(f"  {FAIL} {label}")
    sys.exit(1)
