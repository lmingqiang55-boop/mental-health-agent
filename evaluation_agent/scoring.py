# -*- coding: utf-8 -*-
"""11 个底层小项 -> 五维心理画像 -> concern_index -> OverallLevel 的确定性计算规则。

本模块只做**纯计算**：无副作用、不调用任何模型、不使用随机数、
不读取当前时间或任何外部状态。同样的输入永远得到完全相同的输出。

派生链（v1.0 固定，不允许大模型或调用方自由决定）
--------------------------------------------------

.. code-block:: text

    AssessmentItemScores（11 个小项，各 0-3）
                ↓  calculate_psychological_profile：维度内求和 / (3 × 小项数) × 100
        PsychologicalProfile（五维分数，0-100）
                ↓  calculate_concern_index：0.7 × 五维平均分 + 0.3 × 五维最高分
        concern_index（0-100 整数，派生值）
                ↓  get_overall_level：固定阈值分档
        OverallLevel（四档枚举，二次派生值）

- ``calculate_psychological_profile``：由 11 个小项计算五维画像；
- ``calculate_concern_index``：由五维画像计算综合关注指数；
- ``get_overall_level``：由关注指数推导整体关注等级；
- ``derive_overall_status``：一步得到彼此一致的 ``OverallStatus`` 便利函数。

舍入约定
--------
全项目统一使用**四舍五入**（恰好 ``.5`` 时进位，即 ``round_half_up``），
**不使用** Python 内置 ``round`` 的银行家舍入（``round(6.5) == 6``）。
所有计算用整数精确完成，不引入二进制浮点误差。

口径说明
--------
``concern_index``、五维分数与四档等级都是**产品内部生成的心理状态展示指标**：
既不是临床量表得分，也不是疾病概率，不用于替代专业诊断。

本模块**不定义**每个小项分数本身是怎么判断出来的
（例如"为什么 depressed_mood 是 2"），那属于下一阶段的评分 rubric / Prompt 工作。

自伤 / 自杀相关信号不参与本模块的任何计算，将由独立的 safety module 处理。
"""

from __future__ import annotations

from typing import Final, Union

from .base import MAX_ITEM_SCORE as BASE_MAX_ITEM_SCORE
from .schemas import (
    AssessmentItemScores,
    OverallLevel,
    OverallStatus,
    PsychologicalDimension,
    PsychologicalProfile,
)

__all__ = [
    "MEAN_WEIGHT",
    "MAX_WEIGHT",
    "MAX_ITEM_SCORE",
    "DIMENSION_ITEMS",
    "LEVEL_BANDS",
    "LEVEL_LABELS_ZH",
    "round_half_up",
    "calculate_psychological_profile",
    "calculate_concern_index",
    "get_overall_level",
    "get_level_label_zh",
    "derive_overall_status",
]


# ---------------------------------------------------------------------------
# 公式权重
# ---------------------------------------------------------------------------

#: 五维平均分的权重：70% 反映整体心理状态画像。
MEAN_WEIGHT: Final[float] = 0.7

#: 五维最高分的权重：30% 对当前最突出的关注维度做修正，
#: 避免"单纯平均值掩盖某个明显异常维度"。
MAX_WEIGHT: Final[float] = 0.3

#: 单个底层小项的最大分数（0-3）。与 ``base.ItemScore`` 的上界是同一个常量。
MAX_ITEM_SCORE: Final[int] = BASE_MAX_ITEM_SCORE


# ---------------------------------------------------------------------------
# 维度 -> 底层小项（正式映射，完整覆盖 11 项且不重复）
# ---------------------------------------------------------------------------

#: 每个五维用户维度由哪些底层小项计算得出。键为维度枚举，值按固定顺序排列。
#:
#: - ``emotion``：抑郁情绪 + 自我价值/内疚
#: - ``interest_motivation``：兴趣缺失 + 主动性下降
#: - ``sleep_energy``：睡眠 + 疲劳 + 食欲（对应 Tseng et al. 2024 Somatic factor）
#: - ``attention_thinking``：注意/决策 + 精神运动（对应 Sensorimotor factor）
#: - ``social_daily``：学习工作受损 + 社交日常受损（功能影响，来自 NICE）
DIMENSION_ITEMS: Final[dict[PsychologicalDimension, tuple[str, ...]]] = {
    PsychologicalDimension.EMOTION: (
        "depressed_mood",
        "low_self_worth_guilt",
    ),
    PsychologicalDimension.INTEREST_MOTIVATION: (
        "anhedonia",
        "reduced_activity_initiative",
    ),
    PsychologicalDimension.SLEEP_ENERGY: (
        "sleep_disturbance",
        "fatigue_low_energy",
        "appetite_change",
    ),
    PsychologicalDimension.ATTENTION_THINKING: (
        "concentration_indecision",
        "psychomotor_change",
    ),
    PsychologicalDimension.SOCIAL_DAILY: (
        "study_work_impairment",
        "social_daily_impairment",
    ),
}


# ---------------------------------------------------------------------------
# level 分档（固定阈值）
# ---------------------------------------------------------------------------

#: 按上界升序排列的分档表：``concern_index <= upper_bound`` 即落入该档。
#: 区间为 0-24 / 25-49 / 50-74 / 75-100，必须完整覆盖 0-100 且不重叠。
LEVEL_BANDS: Final[tuple[tuple[int, OverallLevel], ...]] = (
    (24, OverallLevel.LOW_CONCERN),
    (49, OverallLevel.MILD_CONCERN),
    (74, OverallLevel.MODERATE_CONCERN),
    (100, OverallLevel.HIGH_CONCERN),
)

#: 四档的中文展示文案。**仅用于用户界面展示**，
#: 不得替换 Schema 中的英文枚举值（英文枚举才是正式协议）。
#: 以字符串枚举值为键，便于直接用 JSON 里的字符串查询。
LEVEL_LABELS_ZH: Final[dict[str, str]] = {
    OverallLevel.LOW_CONCERN.value: "状态较平稳",
    OverallLevel.MILD_CONCERN.value: "可以留意",
    OverallLevel.MODERATE_CONCERN.value: "建议关注",
    OverallLevel.HIGH_CONCERN.value: "建议重点关注",
}


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def round_half_up(numerator: int, denominator: int) -> int:
    """对精确有理数 ``numerator / denominator`` 做四舍五入。

    实现为 ``floor(n/d + 1/2)``，等价于 ``(2n + d) // (2d)``，
    全程整数运算，因此不受二进制浮点表示误差影响。

    与 Python 内置 ``round`` 的区别：内置 ``round`` 是**银行家舍入**
    （恰好 ``.5`` 时取偶，``round(6.5) == 6``），本项目统一改用四舍五入
    （``.5`` 进位，``round_half_up(13, 2) == 7``）。

    前置条件（不在此处校验）：
        ``numerator`` 与 ``denominator`` 均为非负整数，且 ``denominator > 0``。

    参数:
        numerator: 分子（精确整数，调用方已完成所有放大运算）。
        denominator: 分母（正整数）。

    返回:
        四舍五入后的整数。
    """
    return (2 * numerator + denominator) // (2 * denominator)


def calculate_psychological_profile(
    item_scores: AssessmentItemScores,
) -> PsychologicalProfile:
    """由 11 个底层小项计算五维心理画像（每维 0-100 整数）。

    每个维度的公式::

        dimension_score = round_half_up(该维度小项之和 / (3 × 该维度小项数) × 100)

    其中 ``3`` 是单个小项的最大分。等价地，维度分就是"该维度小项得分率"
    换算成百分制：

    - ``emotion`` / ``interest_motivation`` / ``attention_thinking`` /
      ``social_daily``：2 个小项，分母 6；
    - ``sleep_energy``：3 个小项，分母 9。

    方向与全项目一致：**分数越高，该维度值得关注的信号越明显**。

    参数:
        item_scores: 11 个小项的 0-3 打分（已通过 Schema 校验）。

    返回:
        五维 :class:`PsychologicalProfile`；不会修改入参。

    异常:
        pydantic.ValidationError: 若 :data:`DIMENSION_ITEMS` 未覆盖全部五个维度
            （属于映射配置错误，会立刻暴露而不是静默产出部分结果）。
    """
    scores: dict[str, int] = {}
    for dimension, item_keys in DIMENSION_ITEMS.items():
        total = sum(getattr(item_scores, key) for key in item_keys)
        scores[dimension.value] = round_half_up(
            total * 100, MAX_ITEM_SCORE * len(item_keys)
        )
    return PsychologicalProfile(**scores)


def calculate_concern_index(profile: PsychologicalProfile) -> int:
    """由五维画像计算综合心理状态关注指数（0-100 整数）。

    公式::

        concern_index = round(0.7 * 五维平均分 + 0.3 * 五维最高分)

    其中 70% 反映整体画像，30% 对最突出的关注维度做修正，
    避免"单纯平均值掩盖某个明显异常维度"。

    实现说明（为了可复现，刻意避开浮点与银行家舍入）：

    1. 公式等价于 ``(7 * 五维总分 + 15 * 五维最高分) / 50``，
       这里全程使用整数运算，避免二进制浮点误差
       （例如 ``0.14 * 249`` 会得到 ``34.859999999999999`` 这类值）。
    2. 舍入使用 :func:`round_half_up`（四舍五入，``.5`` 进位）。
       Python 内置 ``round`` 是银行家舍入（``.5`` 取偶，``round(6.5) == 6``），
       会导致 6.5 分被舍成 6 而非 7，因此这里不使用内置 ``round``。
       注意这一步**确实会遇到** ``.5``（例如五维 ``[10, 10, 5, 0, 0]``
       的精确值是 6.5），所以两种舍入方式在此处结果不同。

    参数:
        profile: 已经通过校验的五维画像（每项为 0-100 整数）。

    返回:
        0-100 的整数关注指数。分数越高表示值得关注的信号越突出。
    """
    scores = (
        profile.emotion,
        profile.interest_motivation,
        profile.sleep_energy,
        profile.attention_thinking,
        profile.social_daily,
    )
    total = sum(scores)
    highest = max(scores)

    # round((7 * total + 15 * highest) / 50)
    return round_half_up(7 * total + 15 * highest, 50)


def get_overall_level(concern_index: int) -> OverallLevel:
    """由关注指数推导整体关注等级。

    固定阈值，**必须由代码推导**，不允许大模型或调用方自由指定::

        0-24   -> low_concern
        25-49  -> mild_concern
        50-74  -> moderate_concern
        75-100 -> high_concern

    参数:
        concern_index: 0-100 的整数关注指数。

    返回:
        对应的 :class:`OverallLevel`。

    异常:
        ValueError: 当 ``concern_index`` 不在 0-100 范围内时抛出。
            越界输入属于调用错误，这里直接报错而不是静默归入某一档。
    """
    if not 0 <= concern_index <= 100:
        raise ValueError(
            f"concern_index 必须在 0-100 之间，实际收到 {concern_index!r}"
        )

    for upper_bound, level in LEVEL_BANDS:
        if concern_index <= upper_bound:
            return level

    # LEVEL_BANDS 覆盖 0-100 且入参已校验，理论上不可达。
    raise AssertionError(f"LEVEL_BANDS 未覆盖 concern_index={concern_index}")


def get_level_label_zh(level: Union[OverallLevel, str]) -> str:
    """取关注等级的中文展示文案（仅用于界面展示）。

    同时接受枚举成员与 JSON 中的字符串值，避免调用方踩
    "枚举成员 vs 字符串" 的哈希坑。
    """
    key = level.value if isinstance(level, OverallLevel) else level
    try:
        return LEVEL_LABELS_ZH[key]
    except KeyError:
        raise ValueError(f"未知的关注等级：{level!r}") from None


def derive_overall_status(profile: PsychologicalProfile, summary: str) -> OverallStatus:
    """由五维画像一步派生出一致的 ``OverallStatus``。

    便利函数，供后续阶段构造报告时使用：它保证
    ``concern_index`` 与 ``level`` 一定与 ``profile`` 自洽，
    不会出现三者矛盾（``EvaluationOutput`` 也会再次校验这一点）。
    """
    concern_index = calculate_concern_index(profile)
    return OverallStatus(
        level=get_overall_level(concern_index),
        concern_index=concern_index,
        summary=summary,
    )
