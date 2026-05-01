import numpy as np
from faster_whisper import WhisperModel
from .models import TranscriptSegment


class TranscriptionService:
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8", language: str = "zh"):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(self._model_size, device=self._device, compute_type=self._compute_type)
        return self._model

    def transcribe(self, audio: np.ndarray, chunk_index: int, time_offset: float = 0.0) -> list[TranscriptSegment]:
        audio_f32 = audio.astype(np.float32)
        segments, _ = self._get_model().transcribe(audio_f32, beam_size=1, language=self._language)
        results = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                results.append(TranscriptSegment(
                    text=text,
                    start_time=time_offset + seg.start,
                    end_time=time_offset + seg.end,
                    chunk_index=chunk_index,
                ))
        return results
