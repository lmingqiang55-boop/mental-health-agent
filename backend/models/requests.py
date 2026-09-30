"""API 请求体模型。路由层只做校验和转发，不在这里写业务逻辑。"""

from pydantic import BaseModel, Field

from backend.models.states import AudioState, VisionState


class ChatRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=4000)


class VisionUpsertRequest(BaseModel):
    """提交句级视觉状态。

    所有状态字段可选；服务端做 merge（部分更新），不会把未传字段重置为 None。
    """
    session_id: str
    state: VisionState


class VisionFrameRequest(BaseModel):
    """浏览器摄像头帧，服务端即时分析且不落盘。"""
    session_id: str
    image_base64: str = Field(min_length=32, max_length=3_000_000)


class AudioUpsertRequest(BaseModel):
    """提交句级音频状态，服务端做 merge。"""
    session_id: str
    state: AudioState


class TriggerAssessmentRequest(BaseModel):
    """对话结束后触发多模态综合评估。"""
    session_id: str


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
