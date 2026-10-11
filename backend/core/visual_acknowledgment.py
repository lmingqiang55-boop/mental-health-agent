"""Conservative observations from a frozen recent window for dialogue wording."""

from collections import Counter
from typing import Literal

from backend.models.responses import VisualFeedback
from backend.models.states import SessionState, VisionState

VisualAcknowledgment = Literal["happy", "sad", "fearful", "angry"]

VISUAL_LABELS: dict[VisualAcknowledgment, str] = {
    "happy": "开心", "sad": "难过", "fearful": "紧张", "angry": "烦躁",
}
ALIASES = {"happiness": "happy", "sadness": "sad", "fear": "fearful", "anger": "angry"}


def select_visual_observation(
    session: SessionState, utterance_id: str | None,
    snapshot: VisionState | None,
) -> VisualFeedback:
    """Only a real, stable, recent facial label may prompt a tentative observation.

    Frame-count and confidence cutoffs are prototype filters, not calibrated
    probabilities of how the student actually feels.
    """
    segment = session.vision_segments.get(utterance_id) if utterance_id else None
    if segment is None:
        return VisualFeedback(reason="missing_segment")
    if session.active_vision_capture_id != segment.capture_id:
        return VisualFeedback(reason="capture_inactive")
    supplied = snapshot.model_dump(exclude={"timestamp"}) if snapshot else None
    frozen = segment.vision_snapshot.model_dump(exclude={"timestamp"}) if segment.vision_snapshot else None
    if supplied != frozen:
        return VisualFeedback(reason="snapshot_mismatch")
    # Frozen at the same time as the aligned snapshot, but never fed to evaluation.
    frames = segment.dialogue_frames
    if not frames:
        return VisualFeedback(reason="no_frames")
    if any(item.source != "real" for item in frames):
        return VisualFeedback(reason="unverified_source")
    if len(frames) < 3:
        return VisualFeedback(reason="too_few_frames")
    latest = max(frames, key=lambda item: item.captured_at_ms)
    if segment.end_ms - latest.captured_at_ms > 2500:
        return VisualFeedback(reason="stale_frames")
    if not latest.state.face_detected:
        return VisualFeedback(reason="no_face")
    faces = [item.state for item in frames if item.state.face_detected]
    if len(faces) / len(frames) < 0.7:
        return VisualFeedback(reason="no_face")
    labels = [(ALIASES.get(frame.emotion, frame.emotion), frame.emotion_confidence)
              for frame in faces]
    supported = [(label, score) for label, score in labels if label in VISUAL_LABELS]
    if len(supported) / len(frames) < 0.7:
        return VisualFeedback(reason="unsupported_emotion")
    eligible = [label for label, score in supported if score is not None and score >= 0.8]
    if len(eligible) < 3 or len(eligible) / len(frames) < 0.7:
        return VisualFeedback(reason="low_confidence")
    label, count = Counter(eligible).most_common(1)[0]
    if count / len(frames) < 0.7:
        return VisualFeedback(reason="unstable_emotion")
    if ALIASES.get(latest.state.emotion, latest.state.emotion) != label:
        return VisualFeedback(reason="unstable_emotion")
    if latest.state.emotion_confidence is None or latest.state.emotion_confidence < 0.8:
        return VisualFeedback(reason="low_confidence")

    # The opening plus two generated replies precede the first opportunity.
    # An explicit turn marker also works when the Agent varies its wording.
    if session.turn_count < 2:
        return VisualFeedback(reason="cooldown")
    if (session.last_visual_observation_turn is not None
            and session.turn_count - session.last_visual_observation_turn < 4):
        return VisualFeedback(reason="cooldown")
    return VisualFeedback(reason="eligible", emotion=label)


def choose_visual_acknowledgment(
    session: SessionState, utterance_id: str | None, snapshot: VisionState | None,
) -> VisualAcknowledgment | None:
    return select_visual_observation(session, utterance_id, snapshot).emotion
