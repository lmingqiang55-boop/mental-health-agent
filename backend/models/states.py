"""多模态状态、风险结果、消息与会话状态。

这是三个模块之间的「插头标准」。修改任何字段都必须走 development_rules.md
第 4 节的公共接口变更流程，不得直接 Push。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from backend.models.enums import (
    ConsentStatus,
    DimensionStatus,
    FollowUpStatus,
    MessageRole,
    RiskLevel,
    SessionStage,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 多模态状态：B 模块输出，A/C 模块只读
# ---------------------------------------------------------------------------

class VisionState(BaseModel):
    """句级视觉状态（实时），用于对话 Agent 动态调整提问策略。

    对应目标图「微表情和眼动检测输出心理状态」。
    A 不关心 B 用 OpenFace / MediaPipe / 自训练模型。
    """
    emotion: str | None = None
    emotion_confidence: float | None = Field(default=None, ge=0, le=1)
    valence: float | None = Field(default=None, ge=-1, le=1,
                                  description="情绪效价，-1 极消极 ~ 1 极积极")
    arousal: float | None = Field(default=None, ge=0, le=1,
                                  description="情绪唤醒度 0~1")
    engagement: float | None = Field(default=None, ge=0, le=1,
                                     description="参与度/关注度 0~1")
    attention_score: float | None = Field(default=None, ge=0, le=1,
                                          description="眼动注意力分布得分")
    gaze_focus: float | None = Field(default=None, ge=0, le=1,
                                     description="注视点稳定度")
    micro_expression_intensity: float | None = Field(default=None, ge=0, le=1,
                                                      description="微表情强度")
    face_detected: bool = False
    timestamp: datetime = Field(default_factory=_now)


class AudioState(BaseModel):
    """句级音频状态（实时），含语音转写文本与副语言特征。"""
    text: str | None = Field(default=None, description="ASR 语音转写文本")
    speech_rate: float | None = Field(default=None, ge=0,
                                      description="语速，标准化 0~1")
    pause_ratio: float | None = Field(default=None, ge=0, le=1,
                                      description="停顿占比")
    energy: float | None = Field(default=None, ge=0, le=1,
                                 description="音量能量 0~1")
    pitch_mean: float | None = Field(default=None, ge=0, le=1,
                                     description="平均音高，标准化 0~1")
    pitch_variability: float | None = Field(default=None, ge=0, le=1,
                                            description="音高变化率")
    audio_available: bool = False
    timestamp: datetime = Field(default_factory=_now)


class SessionVisionSummary(BaseModel):
    """会话级视觉状态（整段对话汇总），用于多模态综合评估 Agent 最终评估。

    由 B 在对话结束时基于全部句级 VisionState 聚合生成。
    """
    dominant_emotion: str | None = None
    mean_valence: float | None = Field(default=None, ge=-1, le=1)
    mean_arousal: float | None = Field(default=None, ge=0, le=1)
    mean_engagement: float | None = Field(default=None, ge=0, le=1)
    mean_attention: float | None = Field(default=None, ge=0, le=1)
    valence_trend: list[float] = Field(default_factory=list,
                                       description="逐句效价序列，用于变化分析")
    face_present_ratio: float | None = Field(default=None, ge=0, le=1,
                                             description="人脸出现时长占比")
    sample_count: int = 0


class SessionAudioSummary(BaseModel):
    """会话级音频状态（整段对话汇总），用于最终评估。"""
    mean_speech_rate: float | None = Field(default=None, ge=0)
    mean_pause_ratio: float | None = Field(default=None, ge=0, le=1)
    mean_energy: float | None = Field(default=None, ge=0, le=1)
    mean_pitch: float | None = Field(default=None, ge=0, le=1)
    energy_trend: list[float] = Field(default_factory=list)
    audio_present_ratio: float | None = Field(default=None, ge=0, le=1)
    sample_count: int = 0


# ---------------------------------------------------------------------------
# 风险结果
# ---------------------------------------------------------------------------

class RiskResult(BaseModel):
    risk_level: RiskLevel = RiskLevel.LOW
    risk_score: float = Field(default=0.1, ge=0, le=1)
    risk_reasons: list[str] = Field(default_factory=list)
    risk_types: list[str] = Field(default_factory=list,
                                  description="风险类型，如自伤倾向、严重抑郁迹象")
    key_evidence: list[str] = Field(default_factory=list,
                                    description="关键对话内容/行为特征")
    requires_intervention: bool = False


# ---------------------------------------------------------------------------
# 消息与会话
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: MessageRole
    content: str
    created_at: datetime = Field(default_factory=_now)
    # 该消息对应的句级多模态快照（可选），不存原始音视频
    vision_snapshot: VisionState | None = None
    audio_snapshot: AudioState | None = None


class ConsentRecord(BaseModel):
    """知情同意记录，对应目标图底部「知情同意与伦理合规」。"""
    status: ConsentStatus = ConsentStatus.NOT_PROVIDED
    scope: list[str] = Field(default_factory=list,
                             description="同意的数据使用范围")
    granted_at: datetime | None = None
    withdrawn_at: datetime | None = None


def initial_assessment() -> dict[str, DimensionStatus]:
    from backend.models.enums import AssessmentDimension
    return {dim.value: DimensionStatus.PENDING for dim in AssessmentDimension}


class SessionState(BaseModel):
    """一次完整筛查会话的权威状态，由 SessionManager 统一管理。"""
    session_id: str
    student_ref: str | None = Field(default=None,
                                    description="匿名/假名学生标识，非实名")
    conversation_history: list[Message] = Field(default_factory=list)
    turn_count: int = 0
    current_stage: SessionStage = SessionStage.EXPLORATION

    # 六维评估覆盖状态
    assessment_state: dict[str, DimensionStatus] = Field(
        default_factory=initial_assessment)

    # 最新句级多模态状态
    latest_vision_state: VisionState | None = None
    latest_audio_state: AudioState | None = None

    # 句级状态日志（每次 vision/audio 提交都记录，用于会话级汇总）
    vision_state_log: list[VisionState] = Field(default_factory=list)
    audio_state_log: list[AudioState] = Field(default_factory=list)

    # 会话级多模态汇总（对话结束后生成）
    vision_summary: SessionVisionSummary | None = None
    audio_summary: SessionAudioSummary | None = None

    # 风险与危机模式
    latest_risk: RiskResult = Field(default_factory=RiskResult)
    crisis_mode: bool = False
    clarify_count: int = Field(default=0,
                               description="当前维度已澄清次数，防止无限循环")

    # 知情同意
    consent: ConsentRecord = Field(default_factory=ConsentRecord)

    # 最终评估结果（评估完成后填充）
    assessment_result_id: str | None = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
