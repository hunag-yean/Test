"""
Mock meeting test — simulates a full meeting session without a microphone.
Injects a pre-written transcript directly, then tests Claude analysis and Q&A.

Usage:
  1. Set ANTHROPIC_API_KEY in .env (real key required for Level 2+)
  2. python3 test_mock_meeting.py
"""
import asyncio
import json
import sys
import time
import subprocess
import urllib.request

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

# ── Mock transcript (simulates ~3 minutes of meeting speech) ───────────────────
MOCK_TRANSCRIPT_CHUNKS = [
    "大家好，今天的會議主要討論Q3產品路線圖。首先我們來回顧一下上週的進度。",
    "Alice報告說API設計文件已經完成了70%，預計週五可以全部完成。",
    "Bob提到資料庫遷移遇到了一些問題，主要是舊資料的格式轉換比較複雜。",
    "我們決定讓Bob這週專注在資料庫遷移上，截止日期是下週一。",
    "關於新功能的優先順序，大家同意先做用戶認證模組，再做通知系統。",
    "Carol負責撰寫測試計畫，目標是在本月底前完成所有單元測試。",
    "最後大家確認下次會議時間是下週三上午十點，地點是3樓會議室。",
]

def print_section(title):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")

async def run_mock_meeting_test():
    import websockets
    from backend.config import settings
    from backend.transcript_store import TranscriptStore
    from backend.models import TranscriptSegment
    from backend.claude_client import ClaudeClient

    all_passed = True

    # ── Level 1: Server startup ────────────────────────────────────────────────
    print_section("Level 1：伺服器啟動測試")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", "19000", "--log-level", "error"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(5)

    try:
        with urllib.request.urlopen("http://127.0.0.1:19000/api/health", timeout=5) as r:
            ok = r.status == 200
        print(f"  {PASS if ok else FAIL}  伺服器啟動並回應 /api/health")
        if not ok:
            all_passed = False
    except Exception as e:
        print(f"  {FAIL}  伺服器啟動失敗：{e}")
        proc.terminate()
        return False

    # ── Level 2: WebSocket + mock transcript injection ─────────────────────────
    print_section("Level 2：WebSocket 協定 + 模擬逐字稿注入")

    try:
        async with websockets.connect("ws://127.0.0.1:19000/ws", open_timeout=5) as ws:
            # 1. connected
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            ok = msg.get("type") == "connected"
            print(f"  {PASS if ok else FAIL}  收到 connected 訊息  [meeting_id={msg.get('meeting_id','')}]")
            if not ok:
                all_passed = False

            # 2. ping/pong
            await ws.send(json.dumps({"type": "ping"}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            ok = msg.get("type") == "pong"
            print(f"  {PASS if ok else FAIL}  ping → pong")
            if not ok:
                all_passed = False
    except Exception as e:
        print(f"  {FAIL}  WebSocket 連線失敗：{e}")
        all_passed = False

    # ── Level 3: Claude API test with mock transcript ──────────────────────────
    print_section("Level 3：Claude API 測試（注入模擬逐字稿）")

    api_key = settings.anthropic_api_key
    if api_key == "test-key-placeholder" or not api_key.startswith("sk-"):
        print(f"  \033[93m⊘\033[0m  跳過（.env 中的 ANTHROPIC_API_KEY 不是真實金鑰）")
        print(f"  {INFO}  請在 .env 填入真實的 Anthropic API Key 後再執行此測試")
    else:
        # Build transcript store with mock data
        store = TranscriptStore()
        for i, text in enumerate(MOCK_TRANSCRIPT_CHUNKS):
            store.append([TranscriptSegment(
                text=text, start_time=i*20, end_time=i*20+20, chunk_index=i
            )])

        full_text = store.get_full_text()
        print(f"  {INFO}  注入逐字稿：{store.word_count()} 字，{len(MOCK_TRANSCRIPT_CHUNKS)} 段")

        client = ClaudeClient(api_key=api_key)

        # Test analyze_transcript
        print(f"  {INFO}  呼叫 Claude 分析逐字稿...")
        try:
            start = time.time()
            result = await client.analyze_transcript(full_text)
            elapsed = time.time() - start

            ok = bool(result.summary)
            print(f"  {PASS if ok else FAIL}  摘要生成成功（{elapsed:.1f}s）")
            print(f"         📝 {result.summary[:80]}…")
            if not ok:
                all_passed = False

            ok = len(result.action_items) > 0
            print(f"  {PASS if ok else FAIL}  行動項目偵測：{len(result.action_items)} 項")
            for item in result.action_items:
                print(f"         • [{item.owner}] {item.task}  截止：{item.due or '未定'}")
            if not ok:
                all_passed = False

            ok = len(result.key_points) > 0
            print(f"  {PASS if ok else FAIL}  重點擷取：{len(result.key_points)} 個重點")
            for pt in result.key_points[:3]:
                print(f"         • {pt}")

        except Exception as e:
            print(f"  {FAIL}  Claude 分析失敗：{e}")
            all_passed = False

        # Test answer_question
        test_question = "Bob負責什麼任務？截止日期是什麼時候？"
        print(f"\n  {INFO}  測試 Q&A：「{test_question}」")
        try:
            start = time.time()
            qa = await client.answer_question(full_text, test_question)
            elapsed = time.time() - start

            ok = bool(qa.answer) and "Bob" in qa.answer
            print(f"  {PASS if ok else FAIL}  Q&A 回答生成（{elapsed:.1f}s，可信度={qa.confidence}）")
            print(f"         💬 {qa.answer[:100]}")
            if not ok:
                all_passed = False

        except Exception as e:
            print(f"  {FAIL}  Q&A 失敗：{e}")
            all_passed = False

    # ── Level 4: Guide for real mic test ──────────────────────────────────────
    print_section("Level 4：真實麥克風測試（需在你的電腦上執行）")
    print(f"  {INFO}  這個層級需要有麥克風的 Windows/Mac 電腦")
    print(f"  {INFO}  步驟：")
    print(f"         1. python run.py")
    print(f"         2. 開瀏覽器 http://127.0.0.1:8000")
    print(f"         3. 點「開始會議」→ 對著麥克風說幾句話")
    print(f"         4. ~15秒後看逐字稿出現")
    print(f"         5. ~30秒後看 Claude 摘要出現")
    print(f"         6. 在 Q&A 輸入框提問，驗證回答")

    proc.terminate()
    proc.wait()

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'═'*55}")
    if all_passed:
        print(f"  所有已執行的測試通過 ✓")
    else:
        print(f"  部分測試未通過，請檢查上方錯誤訊息")
    print(f"{'═'*55}\n")
    return all_passed


if __name__ == "__main__":
    ok = asyncio.run(run_mock_meeting_test())
    sys.exit(0 if ok else 1)
