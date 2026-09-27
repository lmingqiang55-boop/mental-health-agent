from pydantic import BaseModel, Field

from backend.models.states import RiskResult, Stage


class DialogueResponse(BaseModel):
    reply: str
    next_strategy: str
    current_stage: Stage
    risk: RiskResult = Field(default_factory=RiskResult)


class ChatResponse(DialogueResponse):
    session_id: str
    turn_count: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
