from pydantic import BaseModel

from backend.models.states import AudioState, VisionState


class FusedState(BaseModel):
    user_text: str
    vision_available: bool
    audio_available: bool
    # TODO: Replace presence flags with validated multimodal features.


def fuse(user_text: str, vision_state: VisionState | None = None,
         audio_state: AudioState | None = None) -> FusedState:
    return FusedState(user_text=user_text,
                      vision_available=bool(vision_state and vision_state.face_detected),
                      audio_available=bool(audio_state and audio_state.audio_available))
