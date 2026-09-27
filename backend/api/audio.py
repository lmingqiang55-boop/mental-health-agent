from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.states import AudioState


router = APIRouter(prefix="/api", tags=["audio"])


class AudioRequest(AudioState):
    session_id: str


class AudioResponse(BaseModel):
    session_id: str
    status: str = "updated"
    audio_state: AudioState


@router.post("/audio", response_model=AudioResponse)
def update_audio(request: AudioRequest) -> AudioResponse:
    state = AudioState.model_validate(request.model_dump(exclude={"session_id"}))
    if session_manager.update_session(request.session_id, latest_audio_state=state) is None:
        raise session_not_found()
    return AudioResponse(session_id=request.session_id, audio_state=state)
