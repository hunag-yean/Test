from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    text: str
    start_time: float
    end_time: float
    chunk_index: int


class ActionItem(BaseModel):
    owner: str
    task: str
    due: str | None


class AnalysisResult(BaseModel):
    summary: str
    key_points: list[str]
    action_items: list[ActionItem]
    topics_discussed: list[str]


class QAResult(BaseModel):
    question: str
    answer: str
    confidence: str
    relevant_excerpt: str
