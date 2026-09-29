from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.assessment.bank import ITEMS


ItemStatus = Literal["unasked", "mentioned", "needs_clarification", "confirmed"]
SessionStatus = Literal["in_progress", "complete", "stopped", "safety_paused"]
Category = Literal["not_at_all", "several_days", "more_than_half_days", "nearly_every_day"]
SafetyFlag = Literal["no_signal", "needs_review", "urgent"]


class EvidenceEvent(BaseModel):
    turn_id: int
    quote: str
    period: Literal["past_14_days", "other", "unknown"]
    proposed_category: Category | None = None
    accepted: bool = False
    reason: str | None = None


class ItemState(BaseModel):
    status: ItemStatus = "unasked"
    asked_once: bool = False
    category: Category | None = None
    score: int | None = Field(default=None, ge=0, le=3)
    evidence_quote: str | None = None
    evidence_turn_id: int | None = None
    period: Literal["past_14_days"] | None = None
    confirmed_by_user: bool = False
    conflict: bool = False
    evidence_history: list[EvidenceEvent] = Field(default_factory=list)


class TurnRecord(BaseModel):
    turn_id: int
    target_item_id: str | None
    user_text: str
    assistant_text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SelectedAction(BaseModel):
    """One action the question decider chose, kept for audit and later training.

    ``action_log`` is the state -> action -> question record that a future
    real-dialogue dataset or a replacement decision model can be trained from.
    ``intent`` is a plain string here on purpose: the intent vocabulary lives in
    ``question_generator`` and importing it would create a cycle.
    """

    turn_id: int
    item_id: str
    intent: str
    anchor_quote: str = ""
    reason: str = ""
    decider_version: str = ""
    question: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AssessmentSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    grade: int | None = Field(default=None, ge=1, le=12)
    instrument_version: str = "phqa_zh_pending"
    extractor_version: str = "rule_mock_v1"
    status: SessionStatus = "in_progress"
    safety_flag: SafetyFlag = "no_signal"
    current_item_id: str | None = "item_01"
    items: dict[str, ItemState] = Field(default_factory=lambda: {item.item_id: ItemState() for item in ITEMS})
    turns: list[TurnRecord] = Field(default_factory=list)
    action_log: list[SelectedAction] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AssessmentReport(BaseModel):
    session_id: str
    instrument_version: str
    status: SessionStatus
    safety_flag: SafetyFlag
    confirmed_count: int
    required_count: int = 9
    mapped_total: int | None
    pending_items: list[str]
    items: dict[str, ItemState]
    label: str = "对话式 PHQ-A 条目映射分（研究原型）"


def pending_item_ids(state: AssessmentSession) -> list[str]:
    """Topics that still block completion.

    A topic is pending when it is not ``confirmed``, **or** when the assistant
    never explicitly asked it. The second condition matters: a topic the student
    only mentioned on their own is inferred, not asked, so it still has to be
    put to them as a question before the assessment can end.
    """
    return [item.item_id for item in ITEMS
            if state.items[item.item_id].status != "confirmed"
            or not state.items[item.item_id].asked_once]


def can_complete(state: AssessmentSession) -> bool:
    """All nine topics must be explicitly asked and confirmed.

    This is the program-side rule behind "九个主题未明确问完不能完成测评";
    there is no decision-model action that can end the assessment early.
    """
    return not pending_item_ids(state)


def build_report(state: AssessmentSession) -> AssessmentReport:
    pending = pending_item_ids(state)
    complete = (state.status == "complete" and can_complete(state)
                and all(state.items[item.item_id].score is not None for item in ITEMS))
    total = sum(state.items[item.item_id].score for item in ITEMS) if complete else None
    return AssessmentReport(
        session_id=state.session_id,
        instrument_version=state.instrument_version,
        status=state.status,
        safety_flag=state.safety_flag,
        confirmed_count=sum(state.items[item.item_id].status == "confirmed" for item in ITEMS),
        mapped_total=total,
        pending_items=pending,
        items=state.items,
    )
