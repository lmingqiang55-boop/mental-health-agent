"""API 请求体模型。路由层只做校验和转发，不在这里写业务逻辑。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation_agent.inputs import EvaluationInput

from backend.models.states import AudioState, SpeechMetadata, VisionState


class CreateSessionRequest(BaseModel):
    # Pseudonymous identifier reused across sessions; it is not an auth token.
    student_ref: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )


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
    """开始/结束一次摄像头采集。

    ``capture_id`` 只在**开始**采集时必填。结束采集时它没有信息量——服务端
    本来就是按 ``session_id`` 把 ``active_vision_capture_id`` 置空，硬性要求
    非空只会让"关摄像头"这件事平白变成一个 422。为此这里允许 ``active=false``
    时省略或传 null，同时保留 ``active=true`` 必须给出标识的约束。
    """
    model_config = ConfigDict(extra="forbid")
    session_id: str
    capture_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"\S")
    generation: int = Field(ge=0)
    active: bool

    @model_validator(mode="after")
    def complete_capture(self) -> "VisionCaptureRequest":
        if self.active and self.capture_id is None:
            raise ValueError("active 为真时必须提供 capture_id")
        return self


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


# ---------------------------------------------------------------------------
# 治愈小工具（心情 / 微光打卡 / 专注）
# ---------------------------------------------------------------------------

class SaveMoodRequest(BaseModel):
    """提交当日心情日记；重复提交覆盖当天记录。"""
    student_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    mood: int = Field(ge=1, le=5)
    weather: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=20)
    tags: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=200)
    voice_text: str | None = Field(default=None, max_length=200)


class HabitCheckinRequest(BaseModel):
    """提交一天的微光打卡（items 为该日已完成的微行动 id）。"""
    student_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    items: list[str] = Field(default_factory=list, max_length=20)


class FocusLogRequest(BaseModel):
    """记录一次专注学习会话。"""
    student_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    minutes: int = Field(ge=1, le=180)
    mood_before: int | None = Field(default=None, ge=1, le=5)
    mood_after: int | None = Field(default=None, ge=1, le=5)


class ArtReflectRequest(BaseModel):
    """艺术表达「读画」：提交画面的客观特征，返回一段陪伴式解读。

    只传特征、不传图像；服务端仅做语言生成，不落库、不参与风险判定。
    """
    colors: list[str] = Field(default_factory=list, max_length=8, description="用到的颜色名")
    fill: float = Field(default=0.0, ge=0.0, le=1.0, description="涂满程度 0~1")
    symmetry: Literal["free", "mirror", "mandala"] = "free"
    mood: str = Field(default="", max_length=20, description="学生自评心情，选填")
    prompt: str = Field(default="", max_length=80, description="当次题面，选填")
    title: str = Field(default="", max_length=30, description="作品标题，选填")


# ---------------------------------------------------------------------------
# 学生档案 / 紧急联系人
# ---------------------------------------------------------------------------

class SaveProfileRequest(BaseModel):
    """提交/更新学生档案（昵称 / 学校阶段 / 班级）；同一 student_ref 覆盖保存。"""
    student_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    nickname: str = Field(default="", max_length=20)
    school_stage: Literal["primary", "middle", "high"] | None = None
    class_name: str = Field(default="", max_length=40)


class AddContactRequest(BaseModel):
    """新增一名紧急联系人。"""
    student_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=20)
    relation: str = Field(default="", max_length=20)
    phone: str = Field(min_length=3, max_length=20, pattern=r"^[\d\-+\s]{3,20}$")
