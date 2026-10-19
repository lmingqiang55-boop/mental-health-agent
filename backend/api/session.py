"""Session API（C 模块）。"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.api.errors import session_not_found
from backend.api.consent_guard import ALLOWED_SCOPES, CONSENT_VERSION
from backend.core.session_manager import session_manager
from backend.models.enums import ConsentStatus
from backend.models.requests import ConsentRequest, CreateSessionRequest
from backend.models.responses import (
    ConsentResponse,
    CreateSessionResponse,
)
from backend.models.states import ConsentRecord, SessionState

router = APIRouter(prefix="/api/session", tags=["session"])


@router.post("", response_model=CreateSessionResponse)
def create_session(request: CreateSessionRequest | None = None) -> CreateSessionResponse:
    session = session_manager.create_session(
        student_ref=request.student_ref if request else None
    )
    return CreateSessionResponse(
        session_id=session.session_id, student_ref=session.student_ref,
        opening_message=session.conversation_history[0].content,
    )


@router.get("/{session_id}", response_model=SessionState)
def get_session(session_id: str) -> SessionState:
    session = session_manager.get_session(session_id)
    if session is None:
        raise session_not_found()
    return session


@router.delete("/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    if not session_manager.delete_session(session_id):
        raise session_not_found()
    return {"status": "deleted"}


@router.put("/{session_id}/consent", response_model=ConsentResponse)
def update_consent(session_id: str, request: ConsentRequest) -> ConsentResponse:
    if request.session_id != session_id:
        raise HTTPException(status_code=422, detail={
            "code": "SESSION_MISMATCH", "message": "请求中的会话标识不一致。"})
    unknown = sorted(set(request.scope) - ALLOWED_SCOPES)
    if unknown:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_CONSENT_SCOPE", "message": "包含未知的授权范围。"})
    required = {"text_processing", "third_party_ai", "assessment_storage"}
    if request.granted and not required.issubset(request.scope):
        raise HTTPException(status_code=422, detail={
            "code": "INCOMPLETE_CONSENT", "message": "基础文字处理、第三方模型处理和结果保存为完成筛查所必需。"})
    def mutate(session: SessionState) -> None:
        if request.granted:
            session.consent = ConsentRecord(
                status=ConsentStatus.GRANTED,
                scope=sorted(set(request.scope)),
                version=request.version or CONSENT_VERSION,
                granted_at=datetime.now(timezone.utc),
            )
        else:
            session.consent = ConsentRecord(
                status=ConsentStatus.WITHDRAWN,
                version=request.version or CONSENT_VERSION,
                withdrawn_at=datetime.now(timezone.utc),
            )

    updated = session_manager.modify_session(session_id, mutate)
    if updated is None:
        raise session_not_found()
    return ConsentResponse(session_id=session_id, consent=updated.consent)
