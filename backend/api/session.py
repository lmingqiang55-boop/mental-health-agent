from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.states import SessionState


router = APIRouter(prefix="/api/session", tags=["session"])


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str = "created"


@router.post("", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    session = session_manager.create_session()
    return CreateSessionResponse(session_id=session.session_id)


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
