"""Conservative observations from a frozen recent window for dialogue wording.

三条通道，共用同一套前置条件（真实检测器、冻结快照对齐、帧数与可用率、冷却）：

``select_visual_observation``
    画面里的表情**足够确定、而且说得出口**时，允许对话 Agent 顺口提一句
    "你看起来……"。门槛严，因为它要把一个情绪名字说出口；标签白名单只有
    开心/难过/紧张/烦躁，neutral 与 surprised 之类都过不了这一关。

``select_visual_checkin``
    这一句**文字自述与人脸效价方向相反**时，允许对话 Agent 温和核对一次。
    不要求表情有高置信度的名字——矛盾靠的是方向，不是标签。真实会话里
    最常见的正是"画面 neutral 或置信度偏低、但效价明显为负"。

``select_visual_tone``
    说不出名字、又不构成矛盾（比如学生本来就在诉苦，画面也确实低落）时，
    只凭**连续效价**说一句"你看起来有点低落"。这是把"视觉只作辅助"变成
    "视觉真的参与关心"的最后一块：模型输出里最常见的 neutral / surprised
    永远拿不到标签，但效价一直是有值的。
"""

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from backend.core.multimodal_consistency import (
    TurnDiscordance,
    detect_turn_discordance,
)
from backend.core.vision_thresholds import (
    ConsistencyThresholds,
    VisualEvidenceThresholds,
)
from backend.models.responses import VisualFeedback
from backend.models.states import SessionState, VisionState

VisualAcknowledgment = Literal["happy", "sad", "fearful", "angry"]
VisualTone = Literal["low", "bright"]

VISUAL_LABELS: dict[VisualAcknowledgment, str] = {
    "happy": "开心", "sad": "难过", "fearful": "紧张", "angry": "烦躁",
}
"""允许口头提及的四类外观线索 → 说给学生听的说法。

这张表和 :data:`TONE_LABELS` 是**全项目唯一的一份**：``backend/prompts/dialogue_prompt``
直接 import 它们来拼提示词，不再各抄一份。以前 prompt 里另有一份内容完全相同的表，
改文案只会改到一处，"后端允许说的"和"提示词里说的"会悄悄分家。
"""
TONE_LABELS: dict[VisualTone, str] = {
    "low": "偏低落（低落、疲惫、提不起劲那一类）",
    "bright": "偏轻松（放松、愉快那一类）",
}
"""整体语气的两档说法；与 :data:`VISUAL_LABELS` 一样只保留这一份。"""
ALIASES = {"happiness": "happy", "sadness": "sad", "fear": "fearful", "anger": "angry"}


@dataclass(frozen=True)
class VisualCheckIn:
    """"这一轮要不要温和核对一句"的判定结果。

    ``discordance`` 有值才要核对；``reason`` 无论成立与否都有值，供
    ``visual_feedback`` 诊断使用（与表情采纳通道共用同一批 reason 词）。
    """

    reason: str
    discordance: TurnDiscordance | None = None


@dataclass(frozen=True)
class VisualToneReading:
    """"能不能只说一句整体感受"的判定结果。

    ``tone`` 有值才要说话；``valence`` 是几帧效价的均值，留作诊断——出问题时
    要能看出到底是"没数据"还是"数据太轻"。
    """

    reason: str
    tone: VisualTone | None = None
    valence: float | None = None


def _gate_frames(
    session: SessionState, utterance_id: str | None, snapshot: VisionState | None,
    limits: VisualEvidenceThresholds,
) -> VisualFeedback | tuple[list, list[VisionState], object]:
    """两条通道的共同前置条件：画面里确实有一张真实、新鲜的脸。

    通过时返回 ``(frames, faces, latest)``；不通过时返回带 reason 的
    :class:`VisualFeedback`，调用方直接把它当结果返回即可。
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
    if len(frames) < limits.min_frames:
        return VisualFeedback(reason="too_few_frames")
    latest = max(frames, key=lambda item: item.captured_at_ms)
    if segment.end_ms - latest.captured_at_ms > limits.max_staleness_ms:
        return VisualFeedback(reason="stale_frames")
    if not latest.state.face_detected:
        return VisualFeedback(reason="no_face")
    faces = [item.state for item in frames if item.state.face_detected]
    if len(faces) / len(frames) < limits.min_frame_ratio:
        return VisualFeedback(reason="no_face")
    return frames, faces, latest


def _cooldown_gate(
    session: SessionState, limits: VisualEvidenceThresholds,
) -> VisualFeedback | None:
    """两条通道共用的节流：开场两轮内不提，提过一次后隔几轮再说。"""
    # The opening plus two generated replies precede the first opportunity.
    # An explicit turn marker also works when the Agent varies its wording.
    if session.turn_count < limits.first_eligible_turn:
        return VisualFeedback(reason="cooldown")
    if (session.last_visual_observation_turn is not None
            and session.turn_count - session.last_visual_observation_turn < limits.cooldown_turns):
        return VisualFeedback(reason="cooldown")
    return None


def _labelled(
    frames: list, faces: list[VisionState], latest: object,
    limits: VisualEvidenceThresholds,
) -> VisualFeedback | VisualAcknowledgment:
    """表情采纳通道专有的一关：画面里得有一个说得出口的情绪名字。"""
    labels = [(ALIASES.get(frame.emotion, frame.emotion), frame.emotion_confidence)
              for frame in faces]
    supported = [(label, score) for label, score in labels if label in VISUAL_LABELS]
    if len(supported) / len(frames) < limits.min_frame_ratio:
        return VisualFeedback(reason="unsupported_emotion")
    eligible = [label for label, score in supported
                if score is not None and score >= limits.min_confidence]
    if len(eligible) < limits.min_frames or len(eligible) / len(frames) < limits.min_frame_ratio:
        return VisualFeedback(reason="low_confidence")
    label, count = Counter(eligible).most_common(1)[0]
    if count / len(frames) < limits.min_frame_ratio:
        return VisualFeedback(reason="unstable_emotion")
    if ALIASES.get(latest.state.emotion, latest.state.emotion) != label:
        return VisualFeedback(reason="unstable_emotion")
    if (latest.state.emotion_confidence is None
            or latest.state.emotion_confidence < limits.min_confidence):
        return VisualFeedback(reason="low_confidence")
    return label


def select_visual_observation(
    session: SessionState, utterance_id: str | None,
    snapshot: VisionState | None,
    thresholds: VisualEvidenceThresholds | None = None,
) -> VisualFeedback:
    """Only a real, stable, recent facial label may prompt a tentative observation.

    Frame-count and confidence cutoffs are prototype filters, not calibrated
    probabilities of how the student actually feels. They live in
    :mod:`backend.core.vision_thresholds` so a 0.6/0.8 A/B needs no code edit.
    """
    limits = thresholds or VisualEvidenceThresholds.from_env()
    gated = _gate_frames(session, utterance_id, snapshot, limits)
    if isinstance(gated, VisualFeedback):
        return gated
    frames, faces, latest = gated
    labelled = _labelled(frames, faces, latest, limits)
    if isinstance(labelled, VisualFeedback):
        return labelled
    cooldown = _cooldown_gate(session, limits)
    if cooldown is not None:
        return cooldown
    return VisualFeedback(reason="eligible", emotion=labelled)


def select_visual_checkin(
    session: SessionState, utterance_id: str | None, snapshot: VisionState | None,
    user_text: str,
    thresholds: VisualEvidenceThresholds | None = None,
    consistency: ConsistencyThresholds | None = None,
) -> VisualCheckIn:
    """这一轮要不要因为"嘴上说的和脸上显示的反着来"而温和核对一句。

    前置条件与 :func:`select_visual_observation` 完全一致，但**不经过表情标签
    那一关**：核对靠的是文字极性与人脸效价的方向，不需要模型先给出一个高置信度
    的表情名字。命中时不需要 emotion——核对不是"说出某个情绪"。
    """
    limits = thresholds or VisualEvidenceThresholds.from_env()
    gated = _gate_frames(session, utterance_id, snapshot, limits)
    if isinstance(gated, VisualFeedback):
        return VisualCheckIn(reason=gated.reason)
    cooldown = _cooldown_gate(session, limits)
    if cooldown is not None:
        return VisualCheckIn(reason=cooldown.reason)
    discordance = detect_turn_discordance(user_text, snapshot, consistency)
    if discordance is None:
        return VisualCheckIn(reason="no_discordance")
    return VisualCheckIn(reason="discordance", discordance=discordance)


def select_visual_tone(
    session: SessionState, utterance_id: str | None, snapshot: VisionState | None,
    thresholds: VisualEvidenceThresholds | None = None,
) -> VisualToneReading:
    """这一轮能不能只凭**连续效价**说一句整体感受。

    比 :func:`select_visual_observation` 宽：不看情绪标签，也不看标签置信度——
    模型给出的 neutral / surprised 全都用不上，但 ``valence`` 一直是有的。
    比它严的地方在于**方向**：默认只说"偏低落"，不说"偏轻松"（见
    :class:`~backend.core.vision_thresholds.VisualEvidenceThresholds`）。

    要求多帧同号且均值过线：只有一帧恰好偏负不算，那更可能是识别抖动。
    """
    limits = thresholds or VisualEvidenceThresholds.from_env()
    gated = _gate_frames(session, utterance_id, snapshot, limits)
    if isinstance(gated, VisualFeedback):
        return VisualToneReading(reason=gated.reason)
    frames, faces, _latest = gated
    cooldown = _cooldown_gate(session, limits)
    if cooldown is not None:
        return VisualToneReading(reason=cooldown.reason)
    values = [face.valence for face in faces if face.valence is not None]
    if len(values) < limits.min_frames:
        return VisualToneReading(reason="no_valence")
    if len({value > 0 for value in values}) != 1:
        return VisualToneReading(reason="unstable_valence")
    mean = sum(values) / len(values)
    if abs(mean) < limits.tone_valence:
        return VisualToneReading(reason="faint_valence", valence=mean)
    tone: VisualTone = "low" if mean < 0 else "bright"
    if tone == "bright" and limits.tone_direction != "both":
        return VisualToneReading(reason="tone_direction", valence=mean)
    return VisualToneReading(reason="tone", tone=tone, valence=mean)


def choose_visual_acknowledgment(
    session: SessionState, utterance_id: str | None, snapshot: VisionState | None,
    thresholds: VisualEvidenceThresholds | None = None,
) -> VisualAcknowledgment | None:
    return select_visual_observation(session, utterance_id, snapshot, thresholds).emotion
