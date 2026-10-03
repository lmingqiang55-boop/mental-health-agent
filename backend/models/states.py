"""多模态状态、风险结果、消息与会话状态。

公共字段与接入方式见 docs/api_spec.md 和 docs/vision_alignment.md。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.models.enums import (
    ConsentStatus,
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
    """视觉指标；消息绑定的句级快照用于风险辅助及最终评估。

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


class VisionFrameObservation(BaseModel):
    """Structured frame only; client capture time is separate from server UTC."""
    frame_id: str
    capture_id: str
    captured_at_ms: float
    image_digest: str
    state: VisionState


class VisionSegment(BaseModel):
    """Frozen interval result, reused even if more frames arrive later."""
    capture_id: str
    start_ms: float
    end_ms: float
    vision_snapshot: VisionState | None = None
    frame_count: int = 0
    valid_frame_count: int = 0


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
                                             description="句级视觉样本中有效人脸的比例")
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

class SpeechMetadata(BaseModel):
    """Actual recording boundaries on a shared client monotonic time axis."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    capture_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    recording_start_ms: float = Field(ge=0)
    recording_end_ms: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered_interval(self) -> "SpeechMetadata":
        if self.recording_end_ms <= self.recording_start_ms:
            raise ValueError("Recording end must follow recording start")
        return self


class ChatReceipt(BaseModel):
    """Internal successful-request cache, with the same lifetime as its session."""
    fingerprint: str
    response: dict


class Message(BaseModel):
    role: MessageRole
    content: str
    created_at: datetime = Field(default_factory=_now)
    # 该消息对应的句级多模态快照（可选），不存原始音视频
    vision_snapshot: VisionState | None = None
    audio_snapshot: AudioState | None = None
    utterance_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"\S")
    speech: SpeechMetadata | None = None


class ConsentRecord(BaseModel):
    """知情同意记录，对应目标图底部「知情同意与伦理合规」。"""
    status: ConsentStatus = ConsentStatus.NOT_PROVIDED
    scope: list[str] = Field(default_factory=list,
                             description="同意的数据使用范围")
    granted_at: datetime | None = None
    withdrawn_at: datetime | None = None


class SessionState(BaseModel):
    """一次完整筛查会话的权威状态，由 SessionManager 统一管理。"""
    session_id: str
    student_ref: str | None = Field(default=None,
                                    description="匿名/假名学生标识，非实名")
    conversation_history: list[Message] = Field(default_factory=list)
    turn_count: int = 0
    # Excluded from the session API; no raw audio or upload data is cached.
    chat_receipts: dict[str, ChatReceipt] = Field(default_factory=dict, exclude=True, repr=False)
    current_stage: SessionStage = SessionStage.EXPLORATION

    # 最新句级多模态状态
    latest_vision_state: VisionState | None = None
    latest_audio_state: AudioState | None = None

    # 实时状态日志；按固定间隔采样的帧不能直接当作逐句评估输入。
    vision_state_log: list[VisionState] = Field(default_factory=list)
    audio_state_log: list[AudioState] = Field(default_factory=list)

    # Capture generations reject delayed start/stop and in-flight old frames.
    vision_capture_generation: int = -1
    active_vision_capture_id: str | None = None
    vision_frames: list[VisionFrameObservation] = Field(default_factory=list, exclude=True)
    vision_segments: dict[str, VisionSegment] = Field(default_factory=dict, exclude=True)

    # 可接收上游汇总；缺省时从消息绑定的逐句快照生成。
    vision_summary: SessionVisionSummary | None = None
    audio_summary: SessionAudioSummary | None = None

    # 风险与危机模式
    latest_risk: RiskResult = Field(default_factory=RiskResult)
    crisis_mode: bool = False

    # 知情同意
    consent: ConsentRecord = Field(default_factory=ConsentRecord)

    # 最终评估结果（评估完成后填充）
    assessment_result_id: str | None = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
