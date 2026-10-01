# -*- coding: utf-8 -*-
"""11 个底层小项的评分 rubric（结构化数据，不是散落在 Prompt 字符串里的散文）。

设计原则
--------

1. **rubric 是数据**：每个小项的定义、可计入的信号、明确排除的情形都写成
   结构化字段，可以被测试、被渲染进 Prompt、被日志记录、被版本化。
   写死在一个大字符串里就无法做这些事。
2. **两类小项语义不同**（这是最容易出错的地方）：

   - **症状 / 行为类（9 项）**参考 PHQ-9 的 0-3 频率式评分思想，
     按"过去约两周内该表现出现的频率与明显程度"打分；
   - **功能影响类（2 项）**按"实际功能受损的程度"打分，
     **不按频率解释**，且必须有实际功能影响的证据。

   两类锚点分别定义在 :data:`SYMPTOM_ANCHORS` 与 :data:`FUNCTIONAL_ANCHORS`，
   避免 11 处各写一份导致不一致。
3. **每条 exclusions 都是真实的误判来源**：例如"不得仅凭体重变化推断食欲"、
   "不得仅因压力大判定功能受损"、"不得依据'今天有点懒'判断精神运动变化"。
   这些负向约束和正向信号同样重要。

本模块**只描述怎么打分**，不含任何模型调用，也不含 Prompt 拼装
（拼装见 :mod:`evaluation_agent.prompt`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from .schemas import ITEM_KEYS, PsychologicalDimension

__all__ = [
    "ItemCategory",
    "SYMPTOM_ANCHORS",
    "FUNCTIONAL_ANCHORS",
    "ItemRubric",
    "ITEM_RUBRICS",
    "RUBRIC_BY_ITEM",
    "get_item_rubric",
    "anchors_for",
]

#: 小项类别：症状 / 行为类，或功能影响类。两者的 0-3 语义不同。
ItemCategory = Literal["symptom", "functional"]


#: 症状 / 行为类小项的 0-3 锚点（0-3 频率式评分思想，参考 PHQ-9）。
SYMPTOM_ANCHORS: Final[tuple[str, ...]] = (
    "0 = 当前评估中基本未发现相关表现",
    "1 = 偶尔出现 / 少数时间出现",
    "2 = 经常出现 / 表现已较明显",
    "3 = 几乎每天、持续出现，或表现非常突出",
)

#: 功能影响类小项的 0-3 锚点（按实际功能受损程度，不按频率解释）。
FUNCTIONAL_ANCHORS: Final[tuple[str, ...]] = (
    "0 = 未发现实际功能影响",
    "1 = 轻微影响，但总体仍能正常完成",
    "2 = 明显影响，部分活动或任务已经受到干扰",
    "3 = 严重或持续影响，正常学习、工作、社交或日常活动明显受限",
)


def anchors_for(category: ItemCategory) -> tuple[str, ...]:
    """按小项类别返回对应的 0-3 锚点。"""
    if category == "symptom":
        return SYMPTOM_ANCHORS
    if category == "functional":
        return FUNCTIONAL_ANCHORS
    raise ValueError(f"未知的小项类别：{category!r}")


@dataclass(frozen=True)
class ItemRubric:
    """单个小项的评分标准。

    :param item: 小项字段名（与 ``AssessmentItemScores`` 一致）。
    :param dimension: 该小项归属的五维用户维度。
    :param category: ``"symptom"`` 或 ``"functional"``，决定使用哪套 0-3 锚点。
    :param label_zh: 中文短名，用于 Prompt 中的人类可读标题。
    :param definition: 这一项到底评估什么。
    :param signals: 算作相关信号的具体表现（正向清单）。
    :param exclusions: **明确不据此给分**的情形（负向清单，防止系统性高估）。
    """

    item: str
    dimension: PsychologicalDimension
    category: ItemCategory
    label_zh: str
    definition: str
    signals: tuple[str, ...]
    exclusions: tuple[str, ...]

    @property
    def anchors(self) -> tuple[str, ...]:
        """本项的 0-3 锚点。"""
        return anchors_for(self.category)

    @property
    def is_functional(self) -> bool:
        """是否为功能影响类小项。"""
        return self.category == "functional"


#: 11 个小项的 rubric，顺序与 :data:`~evaluation_agent.schemas.ITEM_KEYS` 一致。
ITEM_RUBRICS: Final[tuple[ItemRubric, ...]] = (
    # -- emotion ---------------------------------------------------------
    ItemRubric(
        item="depressed_mood",
        dimension=PsychologicalDimension.EMOTION,
        category="symptom",
        label_zh="情绪低落",
        definition="持续的情绪低落、悲伤、空虚、明显消沉或悲观。",
        signals=(
            "明确说心情不好、难过、想哭、开心不起来",
            "说觉得空虚、没意思、很消沉、提不起劲（情绪层面）",
            "反复出现悲观、看不到希望的表述",
        ),
        exclusions=(
            "只对某件具体的事一时不满、生气或烦躁，没有持续的低落 → 不给分",
            "只提到“忙”“压力大”，但没有任何情绪低落表述 → 不给分",
        ),
    ),
    ItemRubric(
        item="low_self_worth_guilt",
        dimension=PsychologicalDimension.EMOTION,
        category="symptom",
        label_zh="自我价值降低与内疚",
        definition="明显自我否定、失败感、无价值感，或过度、不恰当的内疚。",
        signals=(
            "说自己不行、没用、一无是处、是别人的负担",
            "把并非自己责任的事归咎于自己",
            "反复说对不起别人、让别人失望、拖累了别人",
        ),
        exclusions=(
            "对某个具体失误、与事实相称的懊恼或反省 → 不给分",
            "自谦式的客套（例如“我水平一般”）→ 不给分",
        ),
    ),
    # -- interest_motivation ---------------------------------------------
    ItemRubric(
        item="anhedonia",
        dimension=PsychologicalDimension.INTEREST_MOTIVATION,
        category="symptom",
        label_zh="兴趣或愉悦感下降",
        definition="对原本喜欢的活动兴趣下降，很难获得愉悦感，爱好明显减少。",
        signals=(
            "说以前喜欢做的事，现在不想做了",
            "说做什么都没意思、感觉不到开心",
            "明确提到兴趣、爱好减少",
        ),
        exclusions=(
            "只是因为课业忙、没时间做某件事 → 不给分",
            "对某一件本来就不喜欢的事表达不感兴趣 → 不给分",
        ),
    ),
    ItemRubric(
        item="reduced_activity_initiative",
        dimension=PsychologicalDimension.INTEREST_MOTIVATION,
        category="symptom",
        label_zh="主动性下降",
        definition="主动做事的意愿下降、开始任务困难、活动减少、明显缺少主动性。",
        signals=(
            "说什么都不想干、一直拖着、躺着不想动",
            "说明知道该做却迟迟开不了头",
            "提到原本会主动做的事，现在不做了",
        ),
        exclusions=(
            "只是某一天不想做事，或任务型拖延但最终仍能完成 → 不给高分",
            "有明确外部原因（生病、连续熬夜赶工）且为短期 → 谨慎给分",
        ),
    ),
    # -- sleep_energy ----------------------------------------------------
    ItemRubric(
        item="sleep_disturbance",
        dimension=PsychologicalDimension.SLEEP_ENERGY,
        category="symptom",
        label_zh="睡眠异常",
        definition="入睡困难、夜间易醒、早醒、睡眠过多，或睡眠质量明显下降。",
        signals=(
            "说入睡困难、躺很久睡不着",
            "说夜里反复醒、早醒之后睡不着",
            "说睡得太多，或睡完仍然很累、睡眠质量差",
        ),
        exclusions=(
            "偶尔一次熬夜赶作业 → 不给分",
            "只是作息偏晚，但睡眠时长与质量没有问题的 → 不给分"
            "（单纯作息紊乱计入 social_daily_impairment）",
        ),
    ),
    ItemRubric(
        item="fatigue_low_energy",
        dimension=PsychologicalDimension.SLEEP_ENERGY,
        category="symptom",
        label_zh="疲劳与精力不足",
        definition="疲劳、精力不足、很容易累，日常活动明显缺乏精力。",
        signals=(
            "说很容易累、没精力、身体发沉",
            "说白天没精神、犯困、撑不住",
            "说稍微做点事就觉得累",
        ),
        exclusions=(
            "完全能由一次性熬夜或高强度运动解释、且没有持续表现 → 不给高分",
            "不要把“睡不好”本身重复算成疲劳：睡眠问题计入 sleep_disturbance，"
            "只有另有精力不足的表述时才给本项分数",
        ),
    ),
    ItemRubric(
        item="appetite_change",
        dimension=PsychologicalDimension.SLEEP_ENERGY,
        category="symptom",
        label_zh="食欲变化",
        definition="食欲下降或明显增加，以及与近期状态相关的明显进食变化。",
        signals=(
            "说吃不下、没胃口",
            "说最近吃得明显比平时多",
            "提到进食习惯因为近期状态发生了明显变化",
        ),
        exclusions=(
            "**不得仅凭体重变化推断**：没有提到进食，只有体重数字 → 不给分",
            "主动减肥、节食、健身增重等有明确目的的变化 → 不给分",
        ),
    ),
    # -- attention_thinking ----------------------------------------------
    ItemRubric(
        item="concentration_indecision",
        dimension=PsychologicalDimension.ATTENTION_THINKING,
        category="symptom",
        label_zh="注意力与决策困难",
        definition="注意力难以集中、学习和工作时难以持续专注、思考效率下降、明显决策困难。",
        signals=(
            "说看不进去书、容易走神、坐不住",
            "说脑子转不动、反应变慢、想不清楚",
            "说小事也反复纠结、做不了决定",
        ),
        exclusions=(
            "只是任务量变大、事情多而忙乱 → 不给分",
            "只是某道题不会做、某科成绩不好 → 不给分",
        ),
    ),
    ItemRubric(
        item="psychomotor_change",
        dimension=PsychologicalDimension.ATTENTION_THINKING,
        category="symptom",
        label_zh="精神运动性变化",
        definition="思维或动作明显变慢、说话明显变慢，或明显坐立不安、躁动。",
        signals=(
            "自己或他人提到其动作、说话明显变慢",
            "说坐不住、静不下来、来回走动、烦躁到停不下来",
            "句级视觉指标显示微表情强度、参与度、唤醒度同时偏低"
            "（间接提示反应/动作偏少）",
            "句级视觉指标显示注视点不稳定且唤醒度偏高（间接提示坐立不安）",
        ),
        exclusions=(
            "**不得依据“今天有点懒”判断** → 不给分",
            "单纯性格慢热、一贯说话偏慢 → 不给分",
            "**视觉指标只是间接证据**：仅凭视觉指标最多给 1 分；"
            "要给 2 分及以上，必须有被评估者本人或他人的明确描述",
            "视觉指标缺失，或各指标相互矛盾 → 按“未观察到”处理，给 0 分",
        ),
    ),
    # -- social_daily（功能影响类） ---------------------------------------
    ItemRubric(
        item="study_work_impairment",
        dimension=PsychologicalDimension.SOCIAL_DAILY,
        category="functional",
        label_zh="学习 / 工作功能受损",
        definition="注意、精力或情绪方面的问题已经**实际影响**学习或工作。",
        signals=(
            "说作业交不上、任务完不成、进度明显落下",
            "说缺课、旷课、无法正常上课或上班",
            "说效率明显下降，原本能完成的现在完不成",
        ),
        exclusions=(
            "**不得仅因“压力大”判定功能受损**",
            "必须有实际功能影响的证据（具体后果）；只是忙、累，但事情都完成了 → 不给分",
        ),
    ),
    ItemRubric(
        item="social_daily_impairment",
        dimension=PsychologicalDimension.SOCIAL_DAILY,
        category="functional",
        label_zh="社交与日常功能受损",
        definition=(
            "明显减少社交或回避他人，日常活动减少，作息或生活规律明显受到影响，"
            "原本能完成的生活事务变得难以完成。"
        ),
        signals=(
            "说不想见人、推掉约好的事、回避朋友或家人",
            "说日常活动明显减少、作息或生活规律乱了",
            "说原本能正常完成的生活事务（吃饭、洗漱、收拾）变得难以完成",
        ),
        exclusions=(
            "一贯喜欢独处、本来就很少社交 → 不给分（需要相对以往的变化）",
            "只是这段时间忙、没空聚会 → 不给分",
        ),
    ),
)

#: 按小项字段名索引的 rubric，便于按项取用。
RUBRIC_BY_ITEM: Final[dict[str, ItemRubric]] = {r.item: r for r in ITEM_RUBRICS}


def get_item_rubric(item: str) -> ItemRubric:
    """按小项字段名取 rubric；未知小项名直接报错。"""
    try:
        return RUBRIC_BY_ITEM[item]
    except KeyError:
        raise KeyError(
            f"未知的小项 {item!r}；必须是以下之一：{', '.join(ITEM_KEYS)}"
        ) from None
