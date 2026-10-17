"""视觉证据的可调阈值（原型参数，不是校准过的概率）。

为什么单独一个模块：这些数字决定"表情能不能被说出口""视觉和文本算不算矛盾"，
产品与伦理需要按 A/B 结果调整，不该散落在多个文件里各写一份 0.8。
每一项都能用环境变量覆盖，默认值是当前采用的档位。

重校口径（目前还没做）
----------------------
下面这些默认值是原型档位，**不是本项目真实数据上的分位数**，别把它们当成有依据
的阈值。``data/evaluation_memory.sqlite3`` 里现有的记录也帮不上忙：本机 2026-10-15
那份快照有 967 条记录，其中只有 46 条算出了分数（不足 5%），而这 46 条里 42 条的
摘要是同一句话、同一个差值——同一套构造会话跑出来的，没有分布可言；逐帧的置信度与
效价则从来没有落过盘。（这个数字会随库里新增记录变化，看趋势即可，别引用具体值。）

要重校，先把 ``VISION_FRAME_DUMP_DIR`` 指到一个目录（见
:mod:`backend.core.vision_frame_dump`），录一段真实会话——同一台设备、同一间教室
的光照，``VISION_PROVIDER`` 必须是 ``emotiefflib``——**先按每行开头的 ``detector``
分组**（provider / 模型 / 人脸检测后端不同的数据不能混在一起算），再按**句**聚合成
与线上一致的口径，然后：

- ``min_confidence``：取"人眼确认这张脸看得出情绪"那批帧的置信度下四分位；
- ``tone_valence``：取"人眼确认偏负"那批句子的效价均值下四分位；
- ``min_frame_ratio``：先看真实会话里无脸帧到底占多少——比例定高会把整句丢掉，
  那时该修的是采集端的取帧，不是把门槛往下调；
- ``cooldown_turns`` / ``first_eligible_turn``：体验参数，靠真人对练定，不看统计。

新值先写进 ``.env`` 灰度，确认后再改这里的默认值，并把样本量与分位数记进本文件。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _choice_env(name: str, default: str, allowed: tuple[str, ...]) -> str:
    raw = (os.getenv(name) or "").strip().lower()
    return raw if raw in allowed else default


@dataclass(frozen=True)
class VisualEvidenceThresholds:
    """判定"这个表情可以说出口"要用到的全部数字。

    ``min_confidence`` 的默认值从 0.8 放宽到 0.6：模型对真实学生人脸的输出
    常落在 0.3~0.8，0.8 会让采纳路径几乎不可达。这是产品/伦理决定，
    想回到旧行为设 ``VISION_ACK_MIN_CONFIDENCE=0.8`` 即可。

    ``tone_valence`` / ``tone_direction`` 属于**效价说话通道**：模型给不出
    说得出口的情绪名字（neutral、置信度低、或标签不在白名单里，比如
    surprised）时，仍然可以用连续效价说一句"你看起来有点低落"。默认
    ``tone_direction="low"``，即只往"关心"的方向说——表情明显消极时才提，
    **不主动说"你看起来挺开心"**（对方正在诉苦时那是冒犯，而开心本来就
    不用摄像头帮忙）。设成 ``"both"`` 就两边都说。

    ``tone_valence`` 取 0.2 而不是 0.3：本机实测该模型对一张普通人脸就给出
    ±0.23 量级的效价，门槛卡在 0.25 以上会让这条通道基本不可达——那正是
    原来的毛病。0.2 配上"多帧必须同号"和"提一次冷却四轮"，误报的代价只是
    一句可以被学生随口否掉的"你看起来有点累"。
    """

    min_confidence: float = 0.6
    min_frames: int = 3
    min_frame_ratio: float = 0.7
    max_staleness_ms: float = 2500.0
    first_eligible_turn: int = 2
    cooldown_turns: int = 4
    tone_valence: float = 0.2
    tone_direction: str = "low"

    @classmethod
    def from_env(cls) -> "VisualEvidenceThresholds":
        return cls(
            min_confidence=_float_env("VISION_ACK_MIN_CONFIDENCE", 0.6),
            min_frames=_int_env("VISION_ACK_MIN_FRAMES", 3),
            min_frame_ratio=_float_env("VISION_ACK_MIN_FRAME_RATIO", 0.7),
            max_staleness_ms=_float_env("VISION_ACK_MAX_STALENESS_MS", 2500.0),
            first_eligible_turn=_int_env("VISION_ACK_FIRST_TURN", 2),
            cooldown_turns=_int_env("VISION_ACK_COOLDOWN_TURNS", 4),
            tone_valence=_float_env("VISION_ACK_TONE_VALENCE", 0.2),
            tone_direction=_choice_env("VISION_ACK_TONE_DIRECTION", "low", ("low", "both")),
        )


@dataclass(frozen=True)
class ConsistencyThresholds:
    """判定"文字自述与人脸表现是否对得上"要用到的全部数字。

    ``high_score`` / ``moderate_score`` **没有权威出处**：AVEC 系列是连续回归，
    MELD / SIMS 是离散类别，DAIC-WOZ 是 PHQ-8 回归，行为科学文献用"一致组 vs
    不一致组"的组间比较——都不产出"一致性强弱"的数值分档。这里先用一套暂定值，
    等自己的样本积累到几百份后，应按一致性分布的分位数重新校准
    （中位数切 high / low，三分位切 high / moderate / low）。

    ``discordance_gap`` 是**单句**用的：文字极性与人脸效价方向相反、且两者相差
    达到这个值时，才认为这一句"说的和显示的反着来"，值得让对话 Agent 核对一次。
    默认 0.4 的依据是本项目的实际量纲：词表能读出的一次明确表态约在 0.3 上下
    （"难过"= 0.32，"我很难过"= 0.76），0.4 大致等于"两边各自都有一点意思"；
    再小就落进两个模态自身的误差里（人脸野外识别 7 类表情 F1 只有 55%~78%）。
    想更保守就调大，设成 2.0 等于关掉这条通道。

    ``discordance_direction`` 决定这条通道**往哪个方向**认矛盾，默认
    ``"face_negative"``：只在"文字不消极、表情明显消极"时触发，也就是
    "嘴上说还好、脸色不太好"。反方向（文字在诉苦、表情却偏正）**故意不触发**——
    拿摄像头的一个猜测去反驳学生自己的诉苦，是这份产品明确要避免的事；
    设成 ``"both"`` 就恢复对称判定。
    """

    min_pairs: int = 2
    high_score: float = 80.0
    moderate_score: float = 60.0
    discordance_gap: float = 0.4
    discordance_direction: str = "face_negative"

    @classmethod
    def from_env(cls) -> "ConsistencyThresholds":
        return cls(
            # 下限强制为 1：这个旋钮表示"至少几句话才给分"，配成 0 没有意义，
            # 而 0 会让打分处做整除时崩掉（见 compute_consistency 的空配对拦截）。
            min_pairs=max(1, _int_env("CONSISTENCY_MIN_PAIRS", 2)),
            high_score=_float_env("CONSISTENCY_HIGH_SCORE", 80.0),
            moderate_score=_float_env("CONSISTENCY_MODERATE_SCORE", 60.0),
            discordance_gap=_float_env("CONSISTENCY_DISCORDANCE_GAP", 0.4),
            discordance_direction=_choice_env(
                "CONSISTENCY_DISCORDANCE_DIRECTION",
                "face_negative",
                ("face_negative", "both"),
            ),
        )
