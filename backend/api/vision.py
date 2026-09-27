from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.states import VisionState


router = APIRouter(prefix="/api", tags=["vision"])


class VisionRequest(VisionState):
    session_id: str


class VisionResponse(BaseModel):
    session_id: str
    status: str = "updated"
    vision_state: VisionState


@router.post("/vision", response_model=VisionResponse)
def update_vision(request: VisionRequest) -> VisionResponse:
    state = VisionState.model_validate(request.model_dump(exclude={"session_id"}))
    if session_manager.update_session(request.session_id, latest_vision_state=state) is None:
        raise session_not_found()
    return VisionResponse(session_id=request.session_id, vision_state=state)
