import json
import anthropic
from .models import AnalysisResult, ActionItem, QAResult

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "你是一位智慧型會議助理。你會收到即時會議的逐字稿，請分析內容並以 JSON 格式回應。"
    "請確保 JSON 格式正確且完整。"
)

ANALYSIS_PROMPT = """\
以下是目前的會議逐字稿：
<transcript>
{transcript}
</transcript>

請以下列 JSON 格式回應（不要加任何其他文字）：
{{
  "summary": "2-4句話描述目前討論的摘要",
  "key_points": ["重點1", "重點2"],
  "action_items": [
    {{"owner": "負責人或Unknown", "task": "任務描述", "due": "截止時間或null"}}
  ],
  "topics_discussed": ["主題1", "主題2"]
}}"""

QA_PROMPT = """\
以下是目前的會議逐字稿：
<transcript>
{transcript}
</transcript>

與會者提問：「{question}」

請根據逐字稿回答問題。若答案不在逐字稿中，請明確說明並提供可推測的相關資訊。
以下列 JSON 格式回應（不要加任何其他文字）：
{{
  "answer": "詳細回答",
  "confidence": "high 或 medium 或 low",
  "relevant_excerpt": "逐字稿中相關的原文片段，若無則為空字串"
}}"""


class ClaudeClient:
    def __init__(self, api_key: str, model: str = MODEL):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _stream_and_parse(self, user_content: str) -> dict:
        buffer = ""
        with self._client.messages.stream(
            model=self._model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            for text in stream.text_stream:
                buffer += text
        start = buffer.find("{")
        end = buffer.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON found in Claude response: {buffer[:200]}")
        return json.loads(buffer[start:end])

    async def analyze_transcript(self, transcript: str) -> AnalysisResult:
        import asyncio
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None,
            self._stream_and_parse,
            ANALYSIS_PROMPT.format(transcript=transcript),
        )
        action_items = [
            ActionItem(
                owner=item.get("owner", "Unknown"),
                task=item.get("task", ""),
                due=item.get("due"),
            )
            for item in data.get("action_items", [])
        ]
        return AnalysisResult(
            summary=data.get("summary", ""),
            key_points=data.get("key_points", []),
            action_items=action_items,
            topics_discussed=data.get("topics_discussed", []),
        )

    async def answer_question(self, transcript: str, question: str) -> QAResult:
        import asyncio
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None,
            self._stream_and_parse,
            QA_PROMPT.format(transcript=transcript, question=question),
        )
        return QAResult(
            question=question,
            answer=data.get("answer", ""),
            confidence=data.get("confidence", "low"),
            relevant_excerpt=data.get("relevant_excerpt", ""),
        )
