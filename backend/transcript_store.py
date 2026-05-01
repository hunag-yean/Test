import threading
from .models import TranscriptSegment

# When total words exceed this threshold, send rolling summary + recent words to Claude.
_LONG_MEETING_WORD_THRESHOLD = 30_000
_RECENT_WORDS_FOR_LONG_MEETING = 10_000


class TranscriptStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._segments: list[TranscriptSegment] = []
        self._full_text: list[str] = []
        self._analysis_mark: int = 0
        self._rolling_summary: str = ""

    def append(self, segments: list[TranscriptSegment]) -> None:
        with self._lock:
            for seg in segments:
                self._segments.append(seg)
                self._full_text.append(seg.text)

    def get_full_text(self) -> str:
        with self._lock:
            return " ".join(self._full_text)

    def get_text_for_claude(self) -> str:
        """Returns text optimised for Claude: full text for short meetings,
        compressed summary + recent window for long meetings."""
        with self._lock:
            total_words = sum(len(t.split()) for t in self._full_text)
            if total_words <= _LONG_MEETING_WORD_THRESHOLD:
                return " ".join(self._full_text)
            recent_tokens: list[str] = []
            count = 0
            for chunk in reversed(self._full_text):
                words = chunk.split()
                if count + len(words) > _RECENT_WORDS_FOR_LONG_MEETING:
                    break
                recent_tokens.insert(0, chunk)
                count += len(words)
            prefix = ""
            if self._rolling_summary:
                prefix = f"[之前會議摘要]\n{self._rolling_summary}\n\n[最近逐字稿]\n"
            return prefix + " ".join(recent_tokens)

    def update_rolling_summary(self, summary: str) -> None:
        with self._lock:
            self._rolling_summary = summary

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
            self._rolling_summary = ""
