"""API 响应体模型。"""

from pydantic import BaseModel, Field

from backend.models.assessment import (
    CommunicationMessage,
)
from backend.models.evaluation import EvaluationRecord, EvaluationResult
from backend.models.states import (
    AudioState,
    ConsentRecord,
    RiskResult,
    SessionState,
    SpeechMetadata,
    VisionSegment,
    VisionState,
)


class CreateSessionResponse(BaseModel):
    session_id: str
    student_ref: str
    status: str = "created"


class DialogueResponsePayload(BaseModel):
    """对话 Agent 给系统负责人的标准输出。"""
    reply: str
    next_strategy: str
    current_stage: str
    risk: RiskResult


class ChatResponse(DialogueResponsePayload):
    session_id: str
    turn_count: int


class TranscriptionResponse(BaseModel):
    session_id: str
    utterance_id: str
    text: str
    speech: SpeechMetadata


class StateUpsertResponse(BaseModel):
    session_id: str
    status: str = "updated"
    vision_state: VisionState | None = None
    audio_state: AudioState | None = None


class VisionFrameResponse(StateUpsertResponse):
    frame_id: str | None = None
    capture_id: str | None = None
    captured_at_ms: float | None = None


class VisionSegmentResponse(VisionSegment):
    session_id: str
    utterance_id: str


class AssessmentResponse(BaseModel):
    session_id: str
    status: str = "completed"
    result: EvaluationResult


class HistoryListResponse(BaseModel):
    student_ref: str
    records: list[EvaluationRecord]
    total: int


class CommunicationListResponse(BaseModel):
    student_ref: str
    messages: list[CommunicationMessage]


class SendCommunicationResponse(BaseModel):
    status: str = "sent"
    message: CommunicationMessage


class ConsentResponse(BaseModel):
    session_id: str
    consent: ConsentRecord


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
