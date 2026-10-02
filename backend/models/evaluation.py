"""Evaluation Agent 已实现的五维评估结果协议。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from evaluation_agent.schemas import EvaluationOutput, OverallLevel, PsychologicalProfile

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
    report: EvaluationOutput
    assessment_method: Literal["evaluation_agent"] = "evaluation_agent"
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _report_matches_scores(self) -> "EvaluationResult":
        if (
            self.report.psychological_profile != self.psychological_profile
            or self.report.overall_status.concern_index != self.concern_index
            or self.report.overall_status.level != self.overall_level
            or self.report.metadata.assessment_id != self.result_id
            or self.report.metadata.generated_at != self.created_at
        ):
            raise ValueError("报告内容与评估结果不一致")
        return self


class EvaluationRecord(BaseModel):
    record_id: str
    student_ref: str
    result: EvaluationResult
    follow_up_status: FollowUpStatus = FollowUpStatus.NONE
    counselor_notes: list[CounselorNote] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    archived: bool = False
