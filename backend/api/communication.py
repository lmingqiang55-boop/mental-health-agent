"""双向互动沟通 API（C 模块）。

学生与心理老师之间的人工消息，与 AI 对话分开。
"""

from fastapi import APIRouter

from backend.core.communication import communication_store
from backend.models.requests import SendCommunicationRequest
from backend.models.responses import (
    CommunicationListResponse,
    SendCommunicationResponse,
)

router = APIRouter(prefix="/api/communication", tags=["communication"])


@router.post("", response_model=SendCommunicationResponse)
def send_message(request: SendCommunicationRequest) -> SendCommunicationResponse:
    message = communication_store.send(
        student_ref=request.student_ref,
        direction=request.direction,
        content=request.content,
        counselor_ref=request.counselor_ref,
    )
    return SendCommunicationResponse(status="sent", message=message)


@router.get("/{student_ref}", response_model=CommunicationListResponse)
def list_messages(student_ref: str) -> CommunicationListResponse:
    messages = communication_store.list_for_student(student_ref)
    return CommunicationListResponse(
        student_ref=student_ref, messages=messages)
