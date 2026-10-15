"""Contracts for psychological support; internal evidence never enters the student view."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.models.evaluation import EvaluationResult
from backend.models.states import RiskResult, _now

SchoolStage = Literal["primary", "middle", "high"]
Scene = Literal["low_mood", "study_stress", "relationships", "sleep", "general"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HealingBackgroundInput(StrictModel):
    """Caller-supplied context; numerical age comes only from assessment memory."""
    school_stage: SchoolStage | None = None
    current_concern: str | None = Field(default=None, max_length=1000)
    important_events: list[str] = Field(default_factory=list, max_length=10)
    preferences: list[str] = Field(default_factory=list, max_length=10)
    constraints: list[str] = Field(default_factory=list, max_length=10)
    previous_attempts: list[str] = Field(default_factory=list, max_length=10)
    adult_support_available: bool | None = None

    @field_validator("important_events", "preferences", "constraints", "previous_attempts")
    @classmethod
    def bounded_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("背景条目必须非空且不超过 500 字")
        return value


class HealingBackground(HealingBackgroundInput):
    """Resolved internal context for retrieval and age-specific communication."""
    age: int | None = Field(default=None, ge=6, le=18)

    @model_validator(mode="after")
    def consistent_age(self):
        # Broad bounds catch contradictory recorded demographics without guessing.
        bounds = {"primary": (6, 13), "middle": (11, 16), "high": (14, 18)}
        if self.age is not None and self.school_stage is not None:
            low, high = bounds[self.school_stage]
            if not low <= self.age <= high:
                raise ValueError("年龄与学段存在冲突，请确认后再进入")
        return self


class HealingMemory(StrictModel):
    student_ref: str
    session_id: str
    assessment: EvaluationResult
    recent_assessments: list[EvaluationResult] = Field(default_factory=list)
    background: HealingBackground = Field(default_factory=HealingBackground)
    current_session_messages: list[str] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)
    risk_input_issues: list[str] = Field(default_factory=list)


class KnowledgeWording(StrictModel):
    """Verified alternate wording; its reading level never widens source eligibility."""
    wording_id: str
    style: Literal["simple", "conversational", "autonomous"]
    title: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=300)
    steps: list[str] = Field(min_length=1, max_length=6)
    semantic_checked: bool = False
    validation_issues: list[str] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def bounded_steps(cls, value: list[str]) -> list[str]:
        if any(not step.strip() or len(step) > 500 for step in value):
            raise ValueError("知识表达步骤必须非空且不超过 500 字")
        return value


class Evidence(StrictModel):
    """Short verbatim anchor plus offsets in the normalized source, not model guesses."""
    field: str
    quote: str = Field(min_length=1, max_length=600)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class KnowledgeItem(StrictModel):
    knowledge_id: str
    method_key: str
    source_id: str
    source_url: str
    source_title: str
    source_version: str
    source_digest: str
    source_location: str
    title: str = Field(min_length=1, max_length=100)
    scenes: list[Scene] = Field(min_length=1)
    audience: Literal["children_adolescents", "adolescents", "children", "unspecified"]
    age_min: int | None = Field(default=None, ge=0, le=100)
    age_max: int | None = Field(default=None, ge=0, le=100)
    school_stages: list[SchoolStage] = Field(default_factory=list)
    executor: Literal["student", "adult_guided", "adult", "unspecified"]
    purpose: Literal["method", "explanation", "help"]
    goal: str = Field(min_length=1, max_length=300)
    steps: list[str] = Field(default_factory=list, max_length=6)
    prerequisites: list[str] = Field(default_factory=list, max_length=8)
    exclusions: list[str] = Field(default_factory=list, max_length=8)
    referral_conditions: list[str] = Field(default_factory=list, max_length=8)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[Evidence] = Field(min_length=1)
    status: Literal["usable", "explanation_only", "pending"] = "pending"
    validation_issues: list[str] = Field(default_factory=list)
    semantic_checked: bool = False
    wordings: list[KnowledgeWording] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def ordered_ages(self):
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("年龄范围倒置")
        if any(not step.strip() or len(step) > 500 for step in self.steps):
            raise ValueError("知识步骤必须非空且不超过 500 字")
        return self


class KnowledgeHit(StrictModel):
    item: KnowledgeItem
    score: float
    age_match: str
    scene_match: str
    risk_limits: list[str] = Field(default_factory=list)


class Suggestion(StrictModel):
    suggestion_id: str
    knowledge_id: str
    method_key: str
    title: str
    goal: str
    steps: list[str]
    prerequisites: list[str]
    cautions: list[str]
    proposed_turn: int
    display_number: int | None = Field(default=None, ge=1)
    execution: Literal["unconfirmed", "not_attempted", "prepared", "attempted", "declined"] = "unconfirmed"
    effect: Literal["unknown", "helpful", "ineffective", "worse"] = "unknown"
    active: bool = True
    wording_id: str | None = None
    source_title: str = ""
    revisions: list[dict] = Field(default_factory=list)


class SupportGoal(StrictModel):
    scene: Scene = "general"
    mentioned_scenes: list[Scene] = Field(default_factory=list)
    needs_confirmation: bool = False
    evidence: str | None = None


class Feedback(StrictModel):
    suggestion_id: str
    execution: Literal["not_attempted", "prepared", "attempted", "declined"]
    effect: Literal["unknown", "helpful", "ineffective", "worse"] = "unknown"
    evidence: str = Field(min_length=1, max_length=1000)
    turn: int = 0


class SupportReport(StrictModel):
    understanding: str
    focus: str
    suggestion_ids: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    question: str | None = None
    generated_at: datetime = Field(default_factory=_now)
    degraded_reason: str | None = None


def original_text(goal: str, steps: list[str]) -> str:
    """把一条方法的目标与步骤连成一段自然的话，供浅字呈现。

    首报里的建议和聊天轮消息里的 `references` 用同一口径，避免两处对同一条方法
    给出不一样的原文。
    """
    chunks: list[str] = []
    for part in [goal, *steps]:
        part = " ".join(str(part).split())
        if not part:
            continue
        if chunks and chunks[-1][-1] not in "。！？；…":
            chunks[-1] = chunks[-1] + "；"
        chunks.append(part)
    return "".join(chunks)


class MessageReference(StrictModel):
    """回答下方那行浅字：知识库原文的文字内容。学生可见，不含知识编号与来源信息。

    text 是知识库里这条方法原本的说法，直接连成一段话，不做字段罗列；
    conditions/cautions 是这条方法本来就带着的执行条件与要注意的事，同样按整句呈现，
    前端不加“执行条件：/请留意：”这类标签，也不展示来源标题。
    """

    title: str
    text: str = Field(min_length=1, max_length=1200)
    conditions: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class HealingMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=_now)
    references: list[MessageReference] = Field(default_factory=list)


class HealingContextUpdate(StrictModel):
    """Explicit in-round context with the original ordinal references."""
    text: str = Field(min_length=1, max_length=4000)
    turn: int = Field(ge=1)
    reference_suggestions: list[Suggestion] = Field(default_factory=list, max_length=2)


class AdultSupportState(StrictModel):
    """Current-round condition; separate from immutable assessment memory."""
    available: bool | None = None
    source: Literal["caller", "context", "dialogue"] | None = None
    evidence: str | None = None
    turn: int = 0
    asked: bool = False
    waiting: bool = False
    deferred_knowledge_ids: list[str] = Field(default_factory=list, max_length=2)
    blocked_suggestion_ids: list[str] = Field(default_factory=list)


class HealingState(StrictModel):
    healing_id: str
    memory: HealingMemory
    scene: Scene
    goal: SupportGoal = Field(default_factory=SupportGoal)
    report: SupportReport
    suggestions: list[Suggestion] = Field(default_factory=list)
    feedback: list[Feedback] = Field(default_factory=list)
    messages: list[HealingMessage] = Field(default_factory=list)
    context_updates: list[HealingContextUpdate] = Field(default_factory=list, max_length=80)
    adult_support: AdultSupportState = Field(default_factory=AdultSupportState)
    turn_count: int = 0
    status: Literal["active", "paused", "ended", "referred"] = "active"
    risk: RiskResult
    # Kept in process memory, never in the student response or assessment database.
    audit: list[dict] = Field(default_factory=list)
    memory_update_suggestions: list[dict] = Field(default_factory=list)
    receipts: dict[str, dict] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class StartHealingRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    regenerate: bool = False
    expected_healing_id: str | None = Field(default=None, max_length=128)
    background: HealingBackgroundInput = Field(default_factory=HealingBackgroundInput)


class HealingChatRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    healing_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("回答不能为空")
        return value.strip()


class StudentSuggestion(StrictModel):
    """报告卡片里的方法。浅字呈现用 text + prerequisites + cautions，编号与步骤表由前端决定不用。"""

    title: str
    text: str
    goal: str
    steps: list[str]
    prerequisites: list[str]
    cautions: list[str]
    execution: Literal["unconfirmed", "not_attempted", "prepared", "attempted", "declined"]
    effect: Literal["unknown", "helpful", "ineffective", "worse"]
    active: bool


class StudentReport(StrictModel):
    understanding: str
    focus: str
    suggestions: list[StudentSuggestion]
    cautions: list[str]
    question: str | None
    generated_at: datetime


class HealingResponse(StrictModel):
    session_id: str
    healing_id: str
    assessment_result_id: str
    status: Literal["active", "paused", "ended", "referred"]
    turn_count: int
    report: StudentReport
    messages: list[HealingMessage]
    risk: RiskResult
    notice: str | None = None


def student_view(state: HealingState) -> HealingResponse:
    initial = set(state.report.suggestion_ids)
    report = state.report.model_copy(deep=True)
    if state.status in {"paused", "ended", "referred"}:
        report.question = None
    if state.status == "referred":
        report.question = None
        initial = set()
        if state.messages and state.messages[-1].role == "assistant":
            report.understanding = state.messages[-1].content
            report.focus = "先确保现实中的安全与支持。"
    return HealingResponse(
        session_id=state.memory.session_id,
        healing_id=state.healing_id,
        assessment_result_id=state.memory.assessment.result_id,
        status=state.status, turn_count=state.turn_count,
        report=StudentReport(
            **report.model_dump(exclude={"suggestion_ids", "degraded_reason"}),
            suggestions=[StudentSuggestion(
                text=original_text(item.goal, item.steps),
                **item.model_dump(include={
                    "title", "goal", "steps", "prerequisites", "cautions",
                    "execution", "effect", "active",
                })) for item in state.suggestions if item.suggestion_id in initial],
        ),
        messages=state.messages, risk=state.risk,
        notice="本次陪伴记录仅在当前会话中保留；刷新或服务重启后请重新进入。",
    )
