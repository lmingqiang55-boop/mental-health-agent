"""API 响应体模型。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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


# ---------------------------------------------------------------------------
# Agent 运行轨迹（演示面板用，默认关闭）
# ---------------------------------------------------------------------------
#
# ``state`` 是五段共用的统一词表，让前端一眼分出"已调用 / 跳过 / 安全分支提前
# 结束 / 该引擎不提供"，而不必去理解每一段的业务含义：
TraceState = Literal["ran", "skipped", "short_circuit", "unavailable"]


class TurnScheduling(BaseModel):
    """图内调度事实（只有 graph 引擎会填）。

    **这是内部搬运字段，不进 HTTP 响应**（见 :class:`DialogueResponsePayload`
    上的 ``exclude=True``）：它对外的形态是 :class:`AgentTrace`。
    """

    engine: str
    #: Dialogue 本轮是否真的被问过"要不要新策略"。后端强制换策略时会短路掉
    #: 这次模型调用，因此 ``routed=False`` 而 ``need_decision=True`` 是合法组合。
    routed: bool
    need_decision: bool
    route_reason_code: str = ""
    forced_reason: str | None = None
    #: 本轮选中的视觉关怀通道（emotion / discordance / tone）与线索名。
    visual_channel: str | None = None
    visual_cue: str | None = None


class TraceSafety(BaseModel):
    """前置安全检查（**LangGraph 之外**执行，每轮恰好一次）。"""

    placement: Literal["pre_graph"] = "pre_graph"
    placement_label: str = "前置安全检查（LangGraph 之外）"
    engine: str
    risk_level: str
    route: str
    model_status: str
    state: TraceState = "ran"
    #: continue / review / stop，供前端着色。
    outcome: str


class TraceDialogue(BaseModel):
    """Dialogue Agent：本轮是否执行自主路由，以及结论是继续还是换策略。"""

    state: TraceState
    routed: bool | None = None
    need_decision: bool | None = None
    reason_code: str = ""
    reason_label: str = ""
    forced_reason: str | None = None
    forced_label: str | None = None


class TraceDecision(BaseModel):
    """Decision Agent：普通轮每轮调用；主动结束或达到轮数上限时跳过。"""

    state: TraceState
    called: bool | None = None
    label: str = ""
    strategy: str = ""


class TraceVision(BaseModel):
    """视觉感知：本轮线索是否有效，以及是否真的被说出口。"""

    state: TraceState
    cue_valid: bool = False
    channel: str | None = None
    channel_label: str | None = None
    cue: str | None = None
    spoken: bool = False
    reason: str = ""


class TraceOutput(BaseModel):
    """本轮最终生成几条聊天气泡。"""

    bubbles: int = 0


class AgentTrace(BaseModel):
    """一轮对话的 Agent 运行轨迹，只含结论、不含原始数据与推理文本。"""

    engine: str
    safety: TraceSafety
    dialogue: TraceDialogue
    decision: TraceDecision
    vision: TraceVision
    output: TraceOutput


class DialogueResponsePayload(BaseModel):
    """对话 Agent 给系统负责人的标准输出。

    **不含风险字段**：对话安全由 ``backend/safety`` 的 Safety Agent 单独产出，
    见 :class:`ChatResponse` 的 ``safety`` 字段。评估报告的风险字段由
    ``backend/safety/projection.py`` 从安全结论单向投影，与本响应无关。

    ``messages`` 是本轮真实要显示的气泡（1~3 条），``reply`` 是向后兼容的
    全文投影。**前端只按 messages 渲染**，不得两者都渲染。
    """

    reply: str
    next_strategy: str
    current_stage: str
    assessment_ready: bool = False
    completion_reason: str | None = None
    screening_progress: ScreeningProgress = Field(default_factory=ScreeningProgress)
    visual_feedback: VisualFeedback = Field(default_factory=VisualFeedback)
    #: 本轮面向学生的消息（1~3 条）。为空时按单条 ``reply`` 处理，见校验器。
    messages: list[str] = Field(default_factory=list)
    #: 图内调度事实（只有 graph 引擎填）。**刻意用 exclude 挡在 HTTP 之外**：
    #: 对外只暴露 :class:`AgentTrace` 这个简化结论，不把图内状态直接给前端。
    scheduling: TurnScheduling | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _messages_fall_back_to_reply(self) -> "DialogueResponsePayload":
        """保证 ``messages`` 永不为空。

        调用方忘记传 messages 时退化成 ``[reply]``，这样消费方（前端、TTS、
        历史记录）只需要处理"至少一条"，不必再判断"是不是旧响应"。
        """
        items = [item.strip() for item in self.messages if item and item.strip()]
        self.messages = items or [self.reply]
        return self


class ChatResponse(DialogueResponsePayload):
    session_id: str
    turn_count: int
    #: 本轮的安全结论（系统唯一安全状态来源），每轮都有。
    safety: SafetyVerdict | None = None
    #: 面向用户的消息（安全分支 1~3 条；普通对话为 1 条且等于 reply）。
    messages: list[str] = Field(default_factory=list)
    #: Agent 运行轨迹，**默认关闭**（``AGENT_TRACE`` 开启且处于演示模式时才有值）。
    #: 只含节点级结论：不含提示词、模型推理文本、密钥或视觉原始数据。
    trace: AgentTrace | None = None


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
