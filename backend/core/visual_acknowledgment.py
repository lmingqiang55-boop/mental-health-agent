"""Conservative, sentence-aligned visual observations for dialogue wording."""

from collections import Counter
from typing import Literal

from backend.models.states import SessionState, VisionState
from backend.vision.detector import real_vision_detector_active

VisualAcknowledgment = Literal["happy", "sad", "fearful", "angry"]

VISUAL_LABELS: dict[VisualAcknowledgment, str] = {
    "happy": "开心", "sad": "难过", "fearful": "紧张", "angry": "烦躁",
}


def choose_visual_acknowledgment(
    session: SessionState, utterance_id: str | None,
    snapshot: VisionState | None,
) -> VisualAcknowledgment | None:
    """Only a real, stable, aligned facial label may prompt a tentative observation.

    Frame-count and confidence cutoffs are prototype filters, not calibrated
    probabilities of how the student actually feels.
    """
    if not real_vision_detector_active():
        return None
    if not utterance_id or snapshot is None or not snapshot.face_detected:
        return None
    segment = session.vision_segments.get(utterance_id)
    if segment is None or segment.vision_snapshot is None:
        return None
    if snapshot.model_dump(exclude={"timestamp"}) != segment.vision_snapshot.model_dump(
            exclude={"timestamp"}):
        return None
    if segment.frame_count < 3 or segment.valid_frame_count / segment.frame_count < 0.7:
        return None

    frames = [item.state for item in session.vision_frames
              if item.capture_id == segment.capture_id
              and segment.start_ms <= item.captured_at_ms < segment.end_ms]
    eligible = [frame for frame in frames
                if frame.face_detected and frame.emotion in VISUAL_LABELS
                and frame.emotion_confidence is not None
                and frame.emotion_confidence >= 0.8]
    if len(eligible) < 3 or len(eligible) / segment.frame_count < 0.7:
        return None
    label, count = Counter(frame.emotion for frame in eligible).most_common(1)[0]
    if count / segment.frame_count < 0.7:
        return None

    # The opening plus two generated replies precede the first opportunity.
    # An explicit turn marker also works when the Agent varies its wording.
    if session.turn_count < 2:
        return None
    if (session.last_visual_observation_turn is not None
            and session.turn_count - session.last_visual_observation_turn < 4):
        return None
    return label
