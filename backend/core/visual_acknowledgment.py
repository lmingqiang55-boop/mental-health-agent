"""Conservative, sentence-aligned visual observations for dialogue wording."""

from collections import Counter
from typing import Literal

from backend.models.states import SessionState, VisionState
from backend.vision.detector import real_vision_detector_active

VisualAcknowledgment = Literal["sad", "happy"]

ACKNOWLEDGMENTS: dict[VisualAcknowledgment, str] = {
    "sad": "你看起来好像有点不开心。",
    "happy": "你看起来挺开心的。",
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
                if frame.face_detected and frame.emotion in ACKNOWLEDGMENTS
                and frame.emotion_confidence is not None
                and frame.emotion_confidence >= 0.8]
    if len(eligible) < 3 or len(eligible) / segment.frame_count < 0.7:
        return None
    label, count = Counter(frame.emotion for frame in eligible).most_common(1)[0]
    if count / segment.frame_count < 0.7:
        return None

    # Begin after three assistant messages; then require three intervening replies.
    replies_since_observation = 0
    for item in reversed(session.conversation_history):
        if item.role.value != "assistant":
            continue
        if "你看起来" in item.content:
            if replies_since_observation < 3:
                return None
            break
        replies_since_observation += 1
    if replies_since_observation < 3:
        return None
    return label
