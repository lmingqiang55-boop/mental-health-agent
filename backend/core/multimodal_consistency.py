"""把"用户嘴上说的"与"脸上显示的"放在一起算一个一致程度。

边界（不要越过）
----------------
本模块算出的分数只表示**语言信号与视觉信号彼此接近的程度**，既不表示诊断置信度，
也不表示受访者是否诚实——与 ``evaluation_agent.schemas.MultimodalObservation``
的字段说明保持一致。

口径
----
逐句取"用户自述、且这一句有人脸效价"的回合，把文字极性
（:func:`backend.core.text_polarity.text_polarity`，[-1, 1]）与视觉效价
（``VisionState.valence``，[-1, 1]）作差，再聚合::

    一致程度 = 100 × (1 - 平均极性差 / 2)

两路完全同向 → 100；方向相反 → 0。等级分界见
:class:`backend.core.vision_thresholds.ConsistencyThresholds`，**没有权威出处**，
是按当前样本暂定的经验值。

为什么用"极性差"而不是余弦相似度
--------------------------------
村口开源实现（``EcheoSan/multimodal_lie_detect``）把文本与面部各自转成 7 类情绪
概率再做余弦，阈值 0.75。余弦对"同样负面但类别不同"（难过 vs 烦躁）会判成不相似，
语义上不对；极性差只关心方向与强度，与我们要回答的问题（"说的和显示的对得上吗"）
一致。这个选择是刻意的，不是少做了一步。

样本不够时宁可不给分
--------------------
少于 ``min_pairs`` 句可比对时返回 ``score=None`` / ``level=unknown``，并在文案里
说清"是没得比，不是比出来一致"。把"没数据"混同于"一致"会让这个字段失去意义。

同一套口径也用在**单句**上
----------------------------
:func:`detect_turn_discordance` 复用同一对信号（文字极性 × 人脸效价）判定
"这一句是不是反着来"，供对话层在下一轮温和核对一次。它与报告里的会话级分数
共用阈值模块，所以调一处两边同时变。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from evaluation_agent.inputs import SELF_REPORT_ROLES, EvaluationInput
from evaluation_agent.schemas import ConsistencyLevel

from backend.core.text_polarity import text_polarity
from backend.core.vision_thresholds import ConsistencyThresholds


LEVEL_LABELS = {
    ConsistencyLevel.HIGH: "较高",
    ConsistencyLevel.MODERATE: "中等",
    ConsistencyLevel.LOW: "较低",
}

SUMMARY_TEXT_LIMIT = 24


@dataclass(frozen=True)
class ConsistencyPair:
    """一句可比对的话：文字怎么说、脸上怎么样。"""

    turn_index: int
    text: str
    text_polarity: float
    vision_valence: float

    @property
    def difference(self) -> float:
        """两个极性之间的距离，0 同向、2 反向。"""

        return abs(self.text_polarity - self.vision_valence)


@dataclass(frozen=True)
class ConsistencyResult:
    """一致性计算的全部产出；页面只用 score / level / summary 三项。"""

    score: int | None
    level: ConsistencyLevel
    summary: str
    pairs: tuple[ConsistencyPair, ...]
    considered_turns: int


def _clip(text: str, limit: int = SUMMARY_TEXT_LIMIT) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _level_for(score: int, thresholds: ConsistencyThresholds) -> ConsistencyLevel:
    if score >= thresholds.high_score:
        return ConsistencyLevel.HIGH
    if score >= thresholds.moderate_score:
        return ConsistencyLevel.MODERATE
    return ConsistencyLevel.LOW


def _insufficient_summary(
    paired: int, considered: int, thresholds: ConsistencyThresholds,
) -> str:
    if considered == 0:
        opening = "本次没有一句用户自述同时拿到了可用的人脸数据"
    else:
        opening = (
            f"本次有 {considered} 句用户自述拿到了可用的人脸数据，"
            f"其中 {paired} 句的文字里能识别出情绪"
        )
    return (
        f"{opening}，少于给出一致性分数所需的最少 {thresholds.min_pairs} 句，"
        "因此本次不给视觉一致性分数。"
        "没有分数不等于「一致」，只表示两路信号没有重叠到可以比较。"
    )


def _paired_summary(
    score: int,
    level: ConsistencyLevel,
    pairs: tuple[ConsistencyPair, ...],
    considered: int,
) -> str:
    mean_difference = sum(pair.difference for pair in pairs) / len(pairs)
    widest = max(pairs, key=lambda pair: pair.difference)
    unpaired = considered - len(pairs)
    coverage = (
        f"另有 {unpaired} 句文字里没有可识别的情绪词，未参与比对。"
        if unpaired else ""
    )
    return (
        f"本次有 {len(pairs)} 句同时具备可识别的文字情绪与人脸效价，"
        f"两路信号平均相差 {mean_difference:.2f}（0 为方向一致，2 为方向相反），"
        f"一致程度 {score}/100，属于{LEVEL_LABELS[level]}。"
        f"相差最大的一句是「{_clip(widest.text)}」"
        f"（文字 {widest.text_polarity:+.2f}，表情 {widest.vision_valence:+.2f}）。"
        f"{coverage}"
        "这个视觉一致性分数只说明语言自述与面部表现两路信号彼此接近的程度，"
        "不代表诊断置信度，也不表示受访者是否诚实；"
        "分档阈值是暂定的经验值，会随样本积累重新校准。"
    )


def compute_consistency(
    input_data: EvaluationInput,
    thresholds: ConsistencyThresholds | None = None,
) -> ConsistencyResult:
    """按句比对文字极性与人脸效价，给出一个 0-100 的一致程度。

    只看 ``SELF_REPORT_ROLES``（用户本人的话）里**同时**具备
    "检出人脸 + 有效价 + 文字可判极性"的句子；其余句子计入
    :attr:`ConsistencyResult.considered_turns` 只用来说明覆盖率。
    """

    limits = thresholds or ConsistencyThresholds.from_env()
    considered = 0
    pairs: list[ConsistencyPair] = []
    for index, message in enumerate(input_data.dialogue_history):
        if message.role not in SELF_REPORT_ROLES:
            continue
        snapshot = message.vision_snapshot
        if snapshot is None or not snapshot.face_detected or snapshot.valence is None:
            continue
        considered += 1
        polarity = text_polarity(message.content)
        if polarity is None:
            continue
        pairs.append(
            ConsistencyPair(
                turn_index=index,
                text=message.content,
                text_polarity=polarity,
                vision_valence=float(snapshot.valence),
            )
        )

    matched = tuple(pairs)
    if len(matched) < limits.min_pairs:
        return ConsistencyResult(
            score=None,
            level=ConsistencyLevel.UNKNOWN,
            summary=_insufficient_summary(len(matched), considered, limits),
            pairs=matched,
            considered_turns=considered,
        )

    mean_difference = sum(pair.difference for pair in matched) / len(matched)
    score = max(0, min(100, round(100.0 * (1.0 - mean_difference / 2.0))))
    level = _level_for(score, limits)
    return ConsistencyResult(
        score=score,
        level=level,
        summary=_paired_summary(score, level, matched, considered),
        pairs=matched,
        considered_turns=considered,
    )


class ValenceSnapshot(Protocol):
    """判定单句是否矛盾只需要两个字段。

    会话端的 ``backend.models.states.VisionState`` 与评估端的
    ``evaluation_agent.multimodal.VisionState`` 都满足，因此这里不绑定具体模型。
    """

    face_detected: bool
    valence: float | None


@dataclass(frozen=True)
class TurnDiscordance:
    """一句里"说的"与"显示的"方向相反。"""

    text_polarity: float
    vision_valence: float

    @property
    def difference(self) -> float:
        """两个极性之间的距离，0 同向、2 反向。"""

        return abs(self.text_polarity - self.vision_valence)


def detect_turn_discordance(
    text: str,
    snapshot: ValenceSnapshot | None,
    thresholds: ConsistencyThresholds | None = None,
) -> TurnDiscordance | None:
    """这一句是不是"嘴上说的"和"脸上显示的"反着来。

    成立条件：检出人脸、有视觉效价、文字能读出极性、两者**方向相反**且相差达到
    ``ConsistencyThresholds.discordance_gap``。同向而强度不同不算矛盾——那是很常见
    的情绪强度差异，不是不一致。

    默认还要求**表情一侧是消极的**（``discordance_direction="face_negative"``）：
    只抓"嘴上说还好、脸色不太好"，不抓"嘴上在诉苦、表情却偏正"。后一种一旦触发，
    对话 Agent 就会用摄像头的一个猜测去反驳学生自己的诉苦，那是这份产品明确要
    避免的；想恢复对称判定，把 ``CONSISTENCY_DISCORDANCE_DIRECTION`` 设成 ``both``。

    返回 ``None`` 表示"这一句没得比或并不矛盾"，两种情况调用方无需区分：
    无论哪种都不该触发核对。
    """

    if snapshot is None or not snapshot.face_detected or snapshot.valence is None:
        return None
    polarity = text_polarity(text)
    if polarity is None:
        return None
    valence = float(snapshot.valence)
    if polarity * valence >= 0:
        return None
    limits = thresholds or ConsistencyThresholds.from_env()
    if abs(polarity - valence) < limits.discordance_gap:
        return None
    if limits.discordance_direction == "face_negative" and valence > 0:
        return None
    return TurnDiscordance(text_polarity=polarity, vision_valence=valence)
