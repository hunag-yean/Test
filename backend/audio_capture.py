import asyncio
import threading
import numpy as np
import sounddevice as sd
import scipy.signal as signal


TARGET_SAMPLE_RATE = 16000


class AudioCaptureManager:
    def __init__(
        self,
        chunk_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        device_index: int | None = None,
        chunk_seconds: int = 15,
    ):
        self._queue = chunk_queue
        self._loop = loop
        self._device_index = device_index
        self._chunk_seconds = chunk_seconds
        self._stream: sd.InputStream | None = None
        self._buffer: list[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        self._drain_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._device_rate = self._get_device_rate()

    def _get_device_rate(self) -> int:
        try:
            info = sd.query_devices(self._device_index, "input")
            return int(info["default_samplerate"])
        except Exception:
            return 44100

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        with self._buffer_lock:
            self._buffer.append(mono)

    def _drain_loop(self) -> None:
        while not self._stop_event.wait(timeout=self._chunk_seconds):
            self._emit_chunk()
        self._emit_chunk()

    def _emit_chunk(self) -> None:
        with self._buffer_lock:
            if not self._buffer:
                return
            raw = np.concatenate(self._buffer)
            self._buffer.clear()

        if self._device_rate != TARGET_SAMPLE_RATE:
            raw = signal.resample_poly(
                raw,
                TARGET_SAMPLE_RATE,
                self._device_rate,
            ).astype(np.float32)
        else:
            raw = raw.astype(np.float32)

        max_val = np.max(np.abs(raw))
        if max_val > 0:
            raw = raw / max_val

        asyncio.run_coroutine_threadsafe(self._queue.put(raw), self._loop)

    def start(self) -> None:
        self._stop_event.clear()
        self._stream = sd.InputStream(
            samplerate=self._device_rate,
            channels=1,
            dtype="float32",
            device=self._device_index,
            callback=self._callback,
        )
        self._stream.start()
        self._drain_thread = threading.Thread(target=self._drain_loop, daemon=True)
        self._drain_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._stream:
            self._stream.stop()
            self._stream.close()
        if self._drain_thread:
            self._drain_thread.join(timeout=5)
