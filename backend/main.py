import asyncio
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import sounddevice as sd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .audio_capture import AudioCaptureManager
from .analysis_scheduler import AnalysisScheduler
from .claude_client import ClaudeClient
from .config import settings
from .transcript_store import TranscriptStore
from .transcription import TranscriptionService

executor = ThreadPoolExecutor(max_workers=2)
transcription_service: TranscriptionService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_service
    transcription_service = TranscriptionService(
        model_size=settings.whisper_model,
        language=settings.whisper_language,
    )
    yield
    executor.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False)
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                pass

    async def send_to(self, ws: WebSocket, message: dict) -> None:
        await ws.send_text(json.dumps(message, ensure_ascii=False))


manager = ConnectionManager()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/audio-devices")
async def list_audio_devices():
    devices = sd.query_devices()
    result = []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            result.append({"index": i, "name": dev["name"]})
    return result


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    meeting_id = str(uuid.uuid4())
    await manager.send_to(ws, {"type": "connected", "meeting_id": meeting_id, "status": "idle"})

    store = TranscriptStore()
    claude_client = ClaudeClient(api_key=settings.anthropic_api_key)
    chunk_queue: asyncio.Queue = asyncio.Queue()
    audio_manager: AudioCaptureManager | None = None
    meeting_tasks: list[asyncio.Task] = []
    meeting_start: float | None = None
    chunk_index = 0

    async def broadcast(msg: dict):
        await manager.broadcast(msg)

    async def audio_drain_task():
        nonlocal chunk_index, meeting_start
        loop = asyncio.get_event_loop()
        while True:
            audio = await chunk_queue.get()
            time_offset = time.time() - meeting_start if meeting_start else 0.0
            await broadcast({"type": "status_update", "is_transcribing": True, "is_analyzing": False, "is_recording": True})
            try:
                segments = await loop.run_in_executor(
                    executor,
                    transcription_service.transcribe,
                    audio,
                    chunk_index,
                    time_offset,
                )
                if segments:
                    store.append(segments)
                    new_text = " ".join(s.text for s in segments)
                    await broadcast({
                        "type": "transcript_update",
                        "new_text": new_text,
                        "full_transcript_length_chars": len(store.get_full_text()),
                        "chunk_index": chunk_index,
                    })
                chunk_index += 1
            except Exception as e:
                await broadcast({"type": "error", "code": "TRANSCRIPTION_FAILED", "message": str(e), "recoverable": True})
            finally:
                await broadcast({"type": "status_update", "is_transcribing": False, "is_analyzing": False, "is_recording": True})

    async def status_task():
        while True:
            await asyncio.sleep(5)
            elapsed = int(time.time() - meeting_start) if meeting_start else 0
            await broadcast({
                "type": "status_update",
                "is_recording": True,
                "is_transcribing": False,
                "is_analyzing": False,
                "meeting_duration_seconds": elapsed,
                "word_count": store.word_count(),
            })

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "ping":
                await manager.send_to(ws, {"type": "pong"})

            elif msg_type == "start_meeting":
                meeting_start = time.time()
                device_index = msg.get("device_index", settings.audio_device_index)
                loop = asyncio.get_event_loop()
                audio_manager = AudioCaptureManager(
                    chunk_queue=chunk_queue,
                    loop=loop,
                    device_index=device_index,
                    chunk_seconds=settings.audio_chunk_seconds,
                )
                audio_manager.start()
                scheduler = AnalysisScheduler(
                    transcript_store=store,
                    claude_client=claude_client,
                    broadcast_fn=broadcast,
                    interval_seconds=settings.analysis_interval_seconds,
                    min_new_words=settings.analysis_min_new_words,
                )
                meeting_tasks = [
                    asyncio.create_task(audio_drain_task()),
                    asyncio.create_task(scheduler.run()),
                    asyncio.create_task(status_task()),
                ]
                await broadcast({"type": "meeting_started", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

            elif msg_type == "stop_meeting":
                for task in meeting_tasks:
                    task.cancel()
                meeting_tasks.clear()
                if audio_manager:
                    audio_manager.stop()
                    audio_manager = None
                elapsed = int(time.time() - meeting_start) if meeting_start else 0
                meeting_start = None
                await broadcast({"type": "meeting_stopped", "duration_seconds": elapsed})

            elif msg_type == "ask_question":
                question = msg.get("question", "").strip()
                if not question:
                    continue
                await manager.send_to(ws, {"type": "qa_thinking"})
                try:
                    result = await claude_client.answer_question(store.get_text_for_claude(), question)
                    await manager.send_to(ws, {"type": "qa_result", **result.model_dump()})
                except Exception as e:
                    await manager.send_to(ws, {"type": "error", "code": "CLAUDE_API_ERROR", "message": str(e), "recoverable": True})

    except WebSocketDisconnect:
        pass
    finally:
        for task in meeting_tasks:
            task.cancel()
        if audio_manager:
            audio_manager.stop()
        manager.disconnect(ws)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
