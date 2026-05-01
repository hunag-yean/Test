import threading
from .models import TranscriptSegment


class TranscriptStore:
    def __init__(self, max_chars: int = 200_000):
        self._lock = threading.RLock()
        self._segments: list[TranscriptSegment] = []
        self._full_text: list[str] = []
        self._analysis_mark: int = 0
        self._max_chars = max_chars

    def append(self, segments: list[TranscriptSegment]) -> None:
        with self._lock:
            for seg in segments:
                self._segments.append(seg)
                self._full_text.append(seg.text)

    def get_full_text(self) -> str:
        with self._lock:
            return " ".join(self._full_text)

    def get_since_last_analysis(self) -> str:
        with self._lock:
            return " ".join(self._full_text[self._analysis_mark:])

    def mark_analysis_point(self) -> None:
        with self._lock:
            self._analysis_mark = len(self._full_text)

    def word_count(self) -> int:
        with self._lock:
            return sum(len(t.split()) for t in self._full_text)

    def clear(self) -> None:
        with self._lock:
            self._segments.clear()
            self._full_text.clear()
            self._analysis_mark = 0
