"""Aggregate actual frame observations; missing values remain missing."""

from collections import Counter

from backend.models.states import VisionState


def aggregate_frames(states: list[VisionState]) -> VisionState | None:
    if not states:
        return None
    valid = [state for state in states if state.face_detected]
    if not valid:
        return VisionState(face_detected=False)

    def mean(field: str) -> float | None:
        values = [getattr(state, field) for state in valid
                  if getattr(state, field) is not None]
        return round(sum(values) / len(values), 4) if values else None

    emotions = Counter(state.emotion for state in valid if state.emotion)
    return VisionState(
        face_detected=True,
        emotion=emotions.most_common(1)[0][0] if emotions else None,
        **{field: mean(field) for field in (
            "emotion_confidence", "valence", "arousal", "engagement",
            "attention_score", "gaze_focus", "micro_expression_intensity")},
    )
