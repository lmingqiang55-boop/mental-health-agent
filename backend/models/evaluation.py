"""Evaluation Agent 已实现的五维评估结果协议。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from evaluation_agent.schemas import OverallLevel, PsychologicalProfile

from backend.models.assessment import CounselorNote
from backend.models.enums import FollowUpStatus
from backend.models.states import RiskResult, _now


class EvaluationResult(BaseModel):
    """只包含目前可由新 Agent 实际生成的结果。"""

    result_id: str
    session_id: str
    student_ref: str | None = None
    psychological_profile: PsychologicalProfile
    concern_index: int = Field(ge=0, le=100)
    overall_level: OverallLevel
    risk: RiskResult
    assessment_method: Literal["evaluation_agent"] = "evaluation_agent"
    created_at: datetime = Field(default_factory=_now)


class EvaluationRecord(BaseModel):
    record_id: str
    student_ref: str
    result: EvaluationResult
    follow_up_status: FollowUpStatus = FollowUpStatus.NONE
    counselor_notes: list[CounselorNote] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    archived: bool = False
