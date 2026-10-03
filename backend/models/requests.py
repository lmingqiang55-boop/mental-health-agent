"""API 请求体模型。路由层只做校验和转发，不在这里写业务逻辑。"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation_agent.inputs import EvaluationInput

from backend.models.states import AudioState, SpeechMetadata, VisionState


class ChatRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=4000)
    # 上游提供与这句话精确对齐的快照，供当前轮决策和最终评估使用。
    vision_snapshot: VisionState | None = None
    utterance_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"\S")
    speech: SpeechMetadata | None = None

    @model_validator(mode="after")
    def speech_has_id(self) -> "ChatRequest":
        if self.speech is not None and self.utterance_id is None:
            raise ValueError("Speech metadata requires an utterance_id")
        return self


class VisionUpsertRequest(BaseModel):
    """提交句级视觉状态。

    所有状态字段可选；服务端做 merge（部分更新），不会把未传字段重置为 None。
    """
    session_id: str
    state: VisionState


class VisionFrameRequest(BaseModel):
    """浏览器摄像头帧，服务端即时分析且不落盘。"""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    session_id: str
    image_base64: str = Field(min_length=32, max_length=3_000_000)
    frame_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"\S")
    capture_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"\S")
    captured_at_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def complete_timing(self) -> "VisionFrameRequest":
        supplied = [self.frame_id is not None, self.capture_id is not None,
                    self.captured_at_ms is not None]
        if any(supplied) and not all(supplied):
            raise ValueError("Timed frames require frame_id, capture_id and captured_at_ms")
        return self


class VisionCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    capture_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    generation: int = Field(ge=0)
    active: bool


class VisionSegmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    session_id: str
    utterance_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    capture_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    start_ms: float = Field(ge=0)
    end_ms: float = Field(gt=0)

    @model_validator(mode="after")
    def bounded_interval(self) -> "VisionSegmentRequest":
        if not 0 < self.end_ms - self.start_ms <= 60_000:
            raise ValueError("Vision interval must be positive and at most 60 seconds")
        return self


class AudioUpsertRequest(BaseModel):
    """兼容现有实时音频状态；评估交接不要求调用，服务端做 merge。"""
    session_id: str
    state: AudioState


class TriggerAssessmentRequest(BaseModel):
    """显式触发评估；上游可直接提交完整的双层视觉输入。"""
    session_id: str
    evaluation_input: EvaluationInput | None = None


class ConsentRequest(BaseModel):
    """更新知情同意状态。"""
    session_id: str
    granted: bool
    scope: list[str] = Field(default_factory=list)


class SendCommunicationRequest(BaseModel):
    """学生/老师发送双向沟通消息。"""
    student_ref: str
    counselor_ref: str | None = None
    direction: str = Field(description="student_to_counselor / counselor_to_student")
    content: str = Field(min_length=1, max_length=2000)
