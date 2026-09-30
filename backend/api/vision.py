import base64
import binascii
import io

from fastapi import APIRouter, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.states import VisionState
from backend.vision.detector import get_detector


router = APIRouter(prefix="/api", tags=["vision"])
MAX_FRAME_PIXELS = 1920 * 1080


class VisionRequest(VisionState):
    session_id: str


class VisionFrameRequest(BaseModel):
    session_id: str
    speech_segment_id: str | None = Field(default=None, min_length=1, max_length=100)
    image_base64: str = Field(min_length=32, max_length=3_000_000)


class VisionResponse(BaseModel):
    session_id: str
    status: str = "updated"
    vision_state: VisionState


class VisionFrameResponse(VisionResponse):
    speech_segment_id: str | None = None


@router.post("/vision", response_model=VisionResponse)
def update_vision(request: VisionRequest) -> VisionResponse:
    state = VisionState.model_validate(request.model_dump(exclude={"session_id"}))
    if session_manager.update_session(request.session_id, latest_vision_state=state) is None:
        raise session_not_found()
    return VisionResponse(session_id=request.session_id, vision_state=state)


@router.post("/vision/frame", response_model=VisionFrameResponse)
def analyze_vision_frame(request: VisionFrameRequest) -> VisionFrameResponse:
    """Extract one frame's facial state; keep only the structured result."""
    if session_manager.get_session(request.session_id) is None:
        raise session_not_found()

    data = request.image_base64
    if data.startswith("data:"):
        header, separator, data = data.partition(",")
        if not separator or header not in (
            "data:image/jpeg;base64", "data:image/png;base64"
        ):
            raise _invalid_frame()
    try:
        frame = base64.b64decode(data, validate=True)
        with Image.open(io.BytesIO(frame)) as image:
            if image.format not in ("JPEG", "PNG") or image.width * image.height > MAX_FRAME_PIXELS:
                raise _invalid_frame()
            image.verify()
    except (binascii.Error, OSError, ValueError, UnidentifiedImageError,
            Image.DecompressionBombError) as exc:
        raise _invalid_frame() from exc

    try:
        state = get_detector().analyze_frame(frame)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={
            "code": "VISION_UNAVAILABLE", "message": str(exc),
        }) from exc

    if session_manager.update_session(request.session_id, latest_vision_state=state) is None:
        raise session_not_found()
    return VisionFrameResponse(
        session_id=request.session_id,
        vision_state=state,
        speech_segment_id=request.speech_segment_id,
    )


def _invalid_frame() -> HTTPException:
    return HTTPException(status_code=422, detail={
        "code": "INVALID_FRAME", "message": "需要有效的 JPEG/PNG 图片，分辨率不超过 1920×1080。",
    })
