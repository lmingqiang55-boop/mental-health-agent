from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


DimensionStatus = Literal["pending", "in_progress", "covered"]
Stage = Literal["exploration", "completed"]


class VisionState(BaseModel):
    emotion: str | None = None
    emotion_confidence: float | None = Field(default=None, ge=0, le=1)
    valence: float | None = Field(default=None, ge=-1, le=1)
    arousal: float | None = Field(default=None, ge=0, le=1)
    engagement: float | None = Field(default=None, ge=0, le=1)
    face_detected: bool = False


class AudioState(BaseModel):
    text: str | None = None
    speech_rate: float | None = None
    pause_ratio: float | None = Field(default=None, ge=0, le=1)
    energy: float | None = Field(default=None, ge=0, le=1)
    pitch_mean: float | None = None
    audio_available: bool = False


class RiskResult(BaseModel):
    risk_level: Literal["low", "medium", "high"] = "low"
    risk_score: float = Field(default=0.0, ge=0, le=1)
    risk_reasons: list[str] = Field(default_factory=list)
    requires_intervention: bool = False


def initial_assessment() -> dict[str, DimensionStatus]:
    return {name: "pending" for name in (
        "mood", "interest", "sleep", "energy", "concentration", "duration"
    )}


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionState(BaseModel):
    session_id: str
    conversation_history: list[Message] = Field(default_factory=list)
    turn_count: int = 0
    current_stage: Stage = "exploration"
    assessment_state: dict[str, DimensionStatus] = Field(default_factory=initial_assessment)
    latest_vision_state: VisionState | None = None
    latest_audio_state: AudioState | None = None
    latest_risk: RiskResult = Field(default_factory=RiskResult)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
