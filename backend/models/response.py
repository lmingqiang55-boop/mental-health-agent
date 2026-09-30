from pydantic import BaseModel, Field

from backend.models.enums import DialogueAction
from backend.models.states import RiskResult, Stage


class PolicyDecision(BaseModel):
    """Raw policy output. The policy model can only choose the 11 fixed actions."""

    actions: list[DialogueAction] = Field(min_length=1)


class DialogueResponse(BaseModel):
    reply: str
    next_strategy: str
    current_stage: Stage
    risk: RiskResult = Field(default_factory=RiskResult)
    # Post-processed next-step instructions handed to the reply generator.
    # The policy output stays list[DialogueAction]; the topic constraint may
    # replace a repeated topic with a transition instruction such as
    # "当前话题从睡眠转到食欲", so this field is free text.
    actions: list[str] = Field(min_length=1)


class ChatResponse(DialogueResponse):
    session_id: str
    turn_count: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
