"""多模态综合评估输出与评估记忆库模型。

对应目标图：
- 「多模态心理评估 Agent」→ AssessmentResult
- 「评估结果输出」→ DimensionScore / RiskResult / Recommendation
- 「评估记忆库」→ AssessmentRecord
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from backend.models.enums import (
    FollowUpStatus,
    RecommendationCategory,
)
from backend.models.states import RiskResult, _now


class DimensionScore(BaseModel):
    """单个心理评估维度的得分。"""
    dimension: str = Field(description="维度标识，见 AssessmentDimension")
    dimension_label: str = Field(description="维度中文名")
    score: float = Field(ge=0, le=1, description="该维度风险/困扰程度 0~1")
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence: list[str] = Field(
        default_factory=list,
        description="支撑该得分的对话内容/多模态特征")
    trend: str | None = Field(
        default=None,
        description="该维度在对话中的变化趋势，如 worsening/stable/improving")


class Recommendation(BaseModel):
    """个性化建议。"""
    category: RecommendationCategory
    content: str
    priority: int = Field(default=2, ge=1, le=3,
                          description="优先级 1高 2中 3低")
    source: str = Field(default="rule",
                        description="建议来源：rule/knowledge/counselor")


class AssessmentResult(BaseModel):
    """多模态综合评估 Agent 的完整输出。"""
    result_id: str
    session_id: str
    student_ref: str | None = None

    dimension_scores: list[DimensionScore]
    overall_score: float = Field(ge=0, le=1,
                                 description="综合风险/困扰程度")
    risk: RiskResult
    recommendations: list[Recommendation]

    summary: str = Field(description="本次筛查的文字摘要")
    key_concerns: list[str] = Field(
        default_factory=list,
        description="重要关注点")

    assessment_method: str = Field(
        default="mock",
        description="评估方式：mock/rule/model；用于区分机器生成与人工审核")
    is_ai_generated: bool = True
    counselor_reviewed: bool = False

    created_at: datetime = Field(default_factory=_now)


class CounselorNote(BaseModel):
    """心理老师人工复核与跟进记录。"""
    note_id: str
    counselor_ref: str
    content: str
    created_at: datetime = Field(default_factory=_now)


class AssessmentRecord(BaseModel):
    """评估记忆库中的一条历史记录，支持长期跟踪与个性化服务。

    对应目标图「评估记忆库」：
    - 存储本次评估结果
    - 历史评估记录管理
    - 支持长期跟踪与个性化服务
    """
    record_id: str
    student_ref: str
    result: AssessmentResult

    follow_up_status: FollowUpStatus = FollowUpStatus.NONE
    counselor_notes: list[CounselorNote] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_now)
    archived: bool = False


class CommunicationMessage(BaseModel):
    """学生与心理老师双向互动沟通的消息。

    对应目标图「双向互动沟通」，与 AI 对话消息分开存储。
    """
    message_id: str
    student_ref: str
    counselor_ref: str | None = None
    direction: str = Field(description="student_to_counselor / counselor_to_student")
    content: str
    read: bool = False
    created_at: datetime = Field(default_factory=_now)
