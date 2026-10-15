"""API 响应体模型。"""

from pydantic import BaseModel, Field

from backend.models.assessment import (
    CommunicationMessage,
)
from backend.models.evaluation import EvaluationRecord, EvaluationResult
from backend.models.heal import FocusSession, HabitRecord, HealContent, MoodEntry
from backend.models.profile import EmergencyContact, StudentProfile
from backend.models.states import (
    AudioState,
    ConsentRecord,
    ScreeningProgress,
    SessionState,
    SpeechMetadata,
    VisionSegment,
    VisionState,
)
from backend.safety.schemas import SafetyVerdict


class CreateSessionResponse(BaseModel):
    session_id: str
    student_ref: str
    opening_message: str
    status: str = "created"


class VisualFeedback(BaseModel):
    """Integration diagnostics; the frontend need not show them to students."""
    reason: str = "not_requested"
    emotion: str | None = None


class DialogueResponsePayload(BaseModel):
    """对话 Agent 给系统负责人的标准输出。

    **不含风险字段**：对话安全由 ``backend/safety`` 的 Safety Agent 单独产出，
    见 :class:`ChatResponse` 的 ``safety`` 字段。评估报告的风险字段由
    ``backend/safety/projection.py`` 从安全结论单向投影，与本响应无关。
    """
    reply: str
    next_strategy: str
    current_stage: str
    assessment_ready: bool = False
    completion_reason: str | None = None
    screening_progress: ScreeningProgress = Field(default_factory=ScreeningProgress)
    visual_feedback: VisualFeedback = Field(default_factory=VisualFeedback)


class ChatResponse(DialogueResponsePayload):
    session_id: str
    turn_count: int
    #: 本轮的安全结论（系统唯一安全状态来源），每轮都有。
    safety: SafetyVerdict | None = None
    #: 面向用户的消息（安全分支 1~3 条；普通对话为 1 条且等于 reply）。
    messages: list[str] = Field(default_factory=list)


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


# ---------------------------------------------------------------------------
# 治愈小工具响应
# ---------------------------------------------------------------------------

class SaveMoodResponse(BaseModel):
    status: str = "saved"
    entry: MoodEntry


class MoodListResponse(BaseModel):
    student_ref: str
    entries: list[MoodEntry]


class HabitCheckinResponse(BaseModel):
    status: str = "saved"
    record: HabitRecord
    streak: int
    total_days: int


class HabitListResponse(BaseModel):
    student_ref: str
    records: list[HabitRecord]
    streak: int
    total_days: int


class FocusLogResponse(BaseModel):
    status: str = "saved"
    session: FocusSession


class FocusListResponse(BaseModel):
    student_ref: str
    sessions: list[FocusSession]
    total_minutes: int


class HealContentsResponse(BaseModel):
    contents: list[HealContent]
    tags: list[str]


class ArtReflectResponse(BaseModel):
    """艺术表达「读画」的陪伴式解读。"""
    text: str


class GrowthResponse(BaseModel):
    """成长回顾汇总（#12）：把心情 / 打卡 / 专注三项合并成一份星光轨迹。"""
    student_ref: str
    days: int
    mood_days: int
    habit_days: int
    streak: int
    focus_sessions: int
    focus_minutes: int
    mood_tag_counts: dict[str, int]
    moods: list[MoodEntry]
    habits: list[HabitRecord]


# ---------------------------------------------------------------------------
# 学生档案 / 紧急联系人响应
# ---------------------------------------------------------------------------

class SaveProfileResponse(BaseModel):
    status: str = "saved"
    profile: StudentProfile


class EmergencyContactListResponse(BaseModel):
    student_ref: str
    contacts: list[EmergencyContact]


class AddContactResponse(BaseModel):
    status: str = "saved"
    contact: EmergencyContact


class DeleteContactResponse(BaseModel):
    status: str = "deleted"
