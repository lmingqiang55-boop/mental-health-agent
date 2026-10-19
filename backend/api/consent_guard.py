"""知情同意的服务端强制门禁。

前端显隐只能改善体验，不能阻止绕过页面直接调用 API。所有会处理学生内容的
接口都应在真正处理前检查会话仍处于 granted 状态，且包含所需 scope。
"""

from fastapi import HTTPException

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.enums import ConsentStatus
from backend.models.states import SessionState


CONSENT_VERSION = "1.0"
ALLOWED_SCOPES = {
    "text_processing",
    "third_party_ai",
    "audio_transcription",
    "vision_analysis",
    "assessment_storage",
}


def require_session_scopes(session_id: str, *scopes: str) -> SessionState:
    session = session_manager.get_session(session_id)
    if session is None:
        raise session_not_found()
    require_scopes(session, *scopes)
    return session


def require_scopes(session: SessionState, *scopes: str) -> None:
    if session.consent.status != ConsentStatus.GRANTED:
        raise HTTPException(status_code=403, detail={
            "code": "CONSENT_REQUIRED",
            "message": "请先完成知情同意，再继续本次筛查。",
        })
    missing = sorted(set(scopes) - set(session.consent.scope))
    if missing:
        raise HTTPException(status_code=403, detail={
            "code": "CONSENT_SCOPE_REQUIRED",
            "message": "当前授权不包含此功能，请返回隐私设置重新选择。",
        })
