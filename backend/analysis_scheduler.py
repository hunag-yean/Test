import asyncio
from collections.abc import Awaitable, Callable
from .transcript_store import TranscriptStore
from .claude_client import ClaudeClient


class AnalysisScheduler:
    def __init__(
        self,
        transcript_store: TranscriptStore,
        claude_client: ClaudeClient,
        broadcast_fn: Callable[[dict], Awaitable[None]],
        interval_seconds: int = 30,
        min_new_words: int = 50,
    ):
        self._store = transcript_store
        self._claude = claude_client
        self._broadcast = broadcast_fn
        self._interval = interval_seconds
        self._min_words = min_new_words

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            new_text = self._store.get_since_last_analysis()
            word_count = len(new_text.split())
            if word_count < self._min_words:
                continue
            try:
                await self._broadcast({"type": "status_update", "is_analyzing": True})
                result = await self._claude.analyze_transcript(self._store.get_text_for_claude())
                self._store.mark_analysis_point()
                self._store.update_rolling_summary(result.summary)
                payload = {"type": "analysis_update", **result.model_dump()}
                await self._broadcast(payload)
            except Exception as e:
                await self._broadcast({
                    "type": "error",
                    "code": "CLAUDE_API_ERROR",
                    "message": str(e),
                    "recoverable": True,
                })
            finally:
                await self._broadcast({"type": "status_update", "is_analyzing": False})
