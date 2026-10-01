# -*- coding: utf-8 -*-
"""Evaluation Agent（心理状态评估 Agent）最终输出 Schema —— 版本 v1.0。

本模块只负责两件事：

1. 定义 Evaluation Agent 面向用户的最终报告结构（Schema v1.0）；
2. 做基础数据校验（类型、取值范围、必填字段、枚举取值、列表长度）。

本模块**不包含**以下内容（均属于后续阶段）：

- 大模型 API 调用（DeepSeek / OpenAI / Qwen 等）；
- Prompt 构造；
- 真实评估逻辑（关注指数的计算规则）；
- 语言信息与视觉信息的融合算法；
- 个性化建议的生成逻辑；
- **LLM 输出解析层**（raw model response → extract/normalize → 本 Schema 严格校验）。
  当前阶段只提供最后一步的严格校验入口，不实现前面的宽松解析。

分数语义（v1.0 正式定义）
------------------------
所有 0-100 的指数/分数都遵循同一方向：**分数越高，表示本次对话中值得关注的
心理状态信号越突出**。

- 0   = 当前未发现明显的关注信号
- 100 = 关注信号非常突出

对 ``multimodal_observation.consistency_score`` 而言，方向相反地定义为
"语言信息与视觉观察的一致程度越高分数越高"（见该字段说明）。

这些分数都是系统内部生成的心理状态**展示指标**，用于帮助用户理解本次对话，
**不是临床量表分数，也不构成医学诊断结果**。

派生关系（v1.0 固定，由 evaluation_agent.scoring 提供纯函数实现）
----------------------------------------------------------------

.. code-block:: text

    AssessmentItemScores（11 个底层小项，0-3）
                ↓  维度内求和 / (3 × 小项数) × 100，四舍五入
        PsychologicalProfile（五维分数，0-100）
                ↓  0.7 × 平均分 + 0.3 × 最高分
        concern_index（0-100 整数：派生值）
                ↓  固定阈值 0-24 / 25-49 / 50-74 / 75-100
        OverallLevel（四档枚举：二次派生值）

也就是说 11 个小项是唯一的源数据，五维画像、``concern_index`` 与 ``level``
全都是派生值，**不参与任何独立判定**。``EvaluationOutput`` 在构造时会重新推导
``concern_index`` 与 ``level`` 并比对，矛盾时直接报校验错误。

五维画像本身也是由小项算出来的，因此报告内部不存在"手工填的五维分数"。

设计约定
--------
- 所有模型继承私有基类 ``_SchemaBase``，统一设置 ``extra="forbid"``。
  正式业务模型不会为了将来接 LLM 而放宽为宽松模式：未来单独实现解析层，
  由它负责把模型原始输出清洗成合法输入，再交给本模块做严格校验。
- ``_SchemaBase`` 统一拒绝"布尔值充当数字"：Python 中 ``bool`` 是 ``int`` 的子类，
  若不拦截，``True`` 会被静默当成 1 分、``False`` 被当成 0 分。
- 数值约束统一写成 ``Annotated[int, Field(ge=0, le=100)]``（``Score0To100``），
  文本约束统一写成 ``Annotated[str, StringConstraints(...)]``（``NonEmptyStr``）；
  这些公共字段类型与基类定义在 ``evaluation_agent.base``，本模块直接复用。
  这两者都会导出**标准** JSON Schema 关键字（``minimum`` / ``maximum`` /
  ``minLength`` / ``pattern``），可供前端等非 Python 消费方直接使用；
  若改用自定义 validator 包装，Pydantic 会退化为输出非标准的 ``ge`` / ``le``。
- 枚举字段使用字符串枚举，序列化结果为枚举值字符串；
  注意 ``model_dump()``（python 模式）返回枚举成员与 ``datetime`` 对象，
  需要 JSON 安全的 dict 时请使用 ``to_dict()`` / ``model_dump(mode="json")``。
- 文本字段**不会被自动 trim**，纯空白字符串按非法值直接拒绝。

依赖：pydantic>=2
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import (
    Field,
    model_validator,
)

from .base import ItemScore, NonEmptyStr, Score0To100
from .base import StrictSchemaBase as _SchemaBase
from .base import ValueStrEnum

__all__ = [
    "SCHEMA_VERSION",
    "MIN_KEY_FINDINGS",
    "MAX_KEY_FINDINGS",
    "MIN_SUGGESTIONS",
    "MAX_SUGGESTIONS",
    "OverallLevel",
    "PsychologicalDimension",
    "ConsistencyLevel",
    "TrendDirection",
    "DIMENSIONS",
    "DIMENSION_LABELS",
    "Score0To100",
    "NonEmptyStr",
    "ItemScore",
    "SYMPTOM_ITEMS",
    "FUNCTIONAL_ITEMS",
    "ITEM_KEYS",
    "AssessmentItemScores",
    "EvaluationMetadata",
    "OverallStatus",
    "PsychologicalProfile",
    "PrimaryConcern",
    "KeyFinding",
    "MultimodalObservation",
    "TrendAndSuggestions",
    "EvaluationOutput",
]


# ---------------------------------------------------------------------------
# 版本与长度约束常量
# ---------------------------------------------------------------------------

#: 当前 Schema 版本。必须与 EvaluationMetadata.schema_version 的 Literal 保持一致。
SCHEMA_VERSION: Final[str] = "1.0"

#: key_findings 的条数下限 / 上限（正式报告 2-4 条）。
MIN_KEY_FINDINGS: Final[int] = 2
MAX_KEY_FINDINGS: Final[int] = 4

#: suggestions 的条数下限 / 上限（正式报告 2-4 条）。
MIN_SUGGESTIONS: Final[int] = 2
MAX_SUGGESTIONS: Final[int] = 4


# ---------------------------------------------------------------------------
# 枚举定义
# ---------------------------------------------------------------------------


class _StrEnum(ValueStrEnum):
    """字符串枚举基类（实现见 ``evaluation_agent.base.ValueStrEnum``）。"""


class OverallLevel(_StrEnum):
    """整体关注等级（``overall_status.level``）。

    只表示"本次对话中值得关注的心理状态信号的突出程度"，
    不代表任何医学诊断结论。

    ``pending`` 之类"尚未完成评估"的状态**不在本枚举内**：
    正式 ``EvaluationOutput`` 只表示一次**已经完成**的评估，
    评估未完成时不应构造 ``EvaluationOutput``。
    """

    LOW_CONCERN = "low_concern"
    MILD_CONCERN = "mild_concern"
    MODERATE_CONCERN = "moderate_concern"
    HIGH_CONCERN = "high_concern"


class PsychologicalDimension(_StrEnum):
    """五维心理画像的维度键（固定五项，不得增删）。"""

    EMOTION = "emotion"
    INTEREST_MOTIVATION = "interest_motivation"
    SLEEP_ENERGY = "sleep_energy"
    ATTENTION_THINKING = "attention_thinking"
    SOCIAL_DAILY = "social_daily"


class ConsistencyLevel(_StrEnum):
    """语言信息与视觉观察的一致程度等级。

    ``UNKNOWN`` 用于视觉数据缺失或不足以判断的情况。
    """

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class TrendDirection(_StrEnum):
    """整段对话中心理状态的变化方向。"""

    IMPROVING = "improving"
    STABLE = "stable"
    FLUCTUATING = "fluctuating"
    WORSENING = "worsening"
    UNCLEAR = "unclear"


#: 五维维度键，顺序即报告展示顺序。
DIMENSIONS: tuple[str, ...] = tuple(d.value for d in PsychologicalDimension)

#: 维度键 -> 中文名，供报告渲染与错误信息使用。
DIMENSION_LABELS: dict[str, str] = {
    PsychologicalDimension.EMOTION.value: "情绪状态",
    PsychologicalDimension.INTEREST_MOTIVATION.value: "兴趣与动力",
    PsychologicalDimension.SLEEP_ENERGY.value: "睡眠与精力",
    PsychologicalDimension.ATTENTION_THINKING.value: "专注与思考",
    PsychologicalDimension.SOCIAL_DAILY.value: "社交与日常功能",
}


# ---------------------------------------------------------------------------
# 通用字段类型
# ---------------------------------------------------------------------------
#
# 本模块所有模型继承的 ``_SchemaBase``（``extra="forbid"`` + 拒绝布尔值）
# 以及公共字段类型 ``NonEmptyStr`` / ``Score0To100`` / ``ItemScore``
# 统一定义在 ``evaluation_agent.base`` 中，此处直接复用，避免各模块重复实现。
#


# ---------------------------------------------------------------------------
# 底层小项（item）分数 —— 五维画像的源数据
#
# 注意：``AssessmentItemScores`` **不是** ``EvaluationOutput`` 的一部分，
# 它是上游（评分 rubric / Prompt）产出的源数据，用来计算五维画像。
# 报告本身目前只携带派生后的五维分数。
# ---------------------------------------------------------------------------

#: 单个小项的分数类型：0-3 的整数，定义见 ``evaluation_agent.base.ItemScore``。
#:
#: 两类小项的 0-3 语义不同：
#:
#: - **症状 / 行为类小项**（前 9 项）参考 PHQ-9 的 0-3 频率式评分思想：
#:   0 = 当前评估中基本未发现相关表现；1 = 偶尔 / 少数时间出现；
#:   2 = 经常出现 / 表现已较明显；3 = 几乎每天、持续出现或表现非常突出。
#: - **功能影响类小项**（后 2 项）按实际功能受损程度：
#:   0 = 未发现实际功能影响；1 = 轻微影响，但总体仍能正常完成；
#:   2 = 明显影响，部分活动或任务已受干扰；
#:   3 = 严重或持续影响，正常学习/工作/社交/日常活动明显受限。
#:
#: ``ItemScore`` 是严格整数类型（``2.0`` / ``"2"`` 会被拒绝）；
#: 大模型原始产出先由 ``normalization.normalize_item_score()`` 安全转换，
#: 再进入本 Schema。两者分工见 ``evaluation_agent.normalization``。

#: 症状 / 行为类小项（9 项）。
SYMPTOM_ITEMS: tuple[str, ...] = (
    "depressed_mood",
    "low_self_worth_guilt",
    "anhedonia",
    "reduced_activity_initiative",
    "sleep_disturbance",
    "fatigue_low_energy",
    "appetite_change",
    "concentration_indecision",
    "psychomotor_change",
)

#: 功能影响类小项（2 项）。依据 NICE 对个人功能与社会功能的要求加入，
#: 不是 PHQ-9 的 9 个症状项目。
FUNCTIONAL_ITEMS: tuple[str, ...] = (
    "study_work_impairment",
    "social_daily_impairment",
)

#: 全部 11 个小项，顺序 = 五维顺序 + 维度内顺序。
ITEM_KEYS: tuple[str, ...] = SYMPTOM_ITEMS + FUNCTIONAL_ITEMS


class AssessmentItemScores(_SchemaBase):
    """11 个底层小项的 0-3 打分：五维心理画像的**源数据**。

    分组与来源（详见 README「理论依据」）：

    - ``emotion``：``depressed_mood``、``low_self_worth_guilt``
    - ``interest_motivation``：``anhedonia``、``reduced_activity_initiative``
    - ``sleep_energy``：``sleep_disturbance``、``fatigue_low_energy``、``appetite_change``
    - ``attention_thinking``：``concentration_indecision``、``psychomotor_change``
    - ``social_daily``：``study_work_impairment``、``social_daily_impairment``

    11 个字段全部必填，分数只能是 0-3 的整数，未定义字段一律拒绝。

    **自伤 / 自杀相关想法、计划与行为不在本模型中**：本项目决定这类安全风险
    信号不参与五维画像与 ``concern_index`` 计算，将由独立的 safety module 处理。
    """

    # -- emotion ---------------------------------------------------------
    depressed_mood: ItemScore = Field(
        ...,
        description=(
            "情绪低落：持续低落、悲伤、空虚、明显消沉、悲观情绪。"
            "对应 PHQ-9 depressed mood / WHO depressed mood / NICE 抑郁核心症状。"
        ),
    )
    low_self_worth_guilt: ItemScore = Field(
        ...,
        description=(
            "自我价值降低与内疚：明显自我否定、失败感、无价值感、过度或不恰当的内疚。"
            "对应 PHQ-9 feelings of worthlessness / excessive guilt 与 WHO low self-worth。"
        ),
    )

    # -- interest_motivation ---------------------------------------------
    anhedonia: ItemScore = Field(
        ...,
        description=(
            "兴趣或愉悦感下降：对原本喜欢的活动兴趣下降、很难获得愉悦感、爱好明显减少。"
            "对应 PHQ-9 little interest or pleasure in doing things。"
        ),
    )
    reduced_activity_initiative: ItemScore = Field(
        ...,
        description=(
            "主动性下降：主动做事的意愿下降、开始任务困难、活动减少、明显缺少主动性。"
            "注意：这不是 PHQ-9 的独立原始题目，而是依据 NICE 关于 inactivity / "
            "doing fewer things / social withdrawal 与 ICD 关于 reduced energy、"
            "diminished activity 的描述，为本项目「兴趣与动力」维度增加的工程化指标。"
        ),
    )

    # -- sleep_energy ----------------------------------------------------
    sleep_disturbance: ItemScore = Field(
        ...,
        description=(
            "睡眠异常：入睡困难、夜间易醒、早醒、睡眠过多、睡眠质量明显下降。"
            "对应 PHQ-9 sleep 与 Tseng et al. 2024 Somatic factor 的 Sleep。"
        ),
    )
    fatigue_low_energy: ItemScore = Field(
        ...,
        description=(
            "疲劳与精力不足：疲劳、精力不足、很容易累、日常活动明显缺乏精力。"
            "对应 PHQ-9 fatigue 与 Tseng et al. 2024 Somatic factor 的 Fatigue。"
        ),
    )
    appetite_change: ItemScore = Field(
        ...,
        description=(
            "食欲变化：食欲下降、食欲明显增加、与近期状态相关的明显进食变化。"
            "对应 PHQ-9 appetite 与 Tseng et al. 2024 Somatic factor 的 Appetite。"
            "不得仅凭体重变化推断。"
        ),
    )

    # -- attention_thinking ----------------------------------------------
    concentration_indecision: ItemScore = Field(
        ...,
        description=(
            "注意力与决策困难：注意力难以集中、学习时难以持续专注、思考效率下降、"
            "明显决策困难。对应 PHQ-9 concentration 与 WHO/NICE concentration / "
            "indecisiveness，属 Tseng et al. 2024 Sensorimotor factor。"
        ),
    )
    psychomotor_change: ItemScore = Field(
        ...,
        description=(
            "精神运动性变化：思维或动作明显变慢、说话明显变慢、明显坐立不安、躁动。"
            "对应 PHQ-9 psychomotor 与 ICD/NICE 描述，属 Tseng et al. 2024 "
            "Sensorimotor factor。不得依据普通的「今天有点懒」判断。"
        ),
    )

    # -- social_daily（功能影响类） ---------------------------------------
    study_work_impairment: ItemScore = Field(
        ...,
        description=(
            "学习 / 工作功能受损：学习效率下降、无法正常完成任务、注意或精力问题"
            "已经**实际影响**学习或工作能力。依据 NICE 对个人功能的要求加入。"
            "不得仅因「压力大」判定功能受损，必须有实际功能影响的证据。"
        ),
    )
    social_daily_impairment: ItemScore = Field(
        ...,
        description=(
            "社交与日常功能受损：明显减少社交、回避朋友或家人、日常活动减少、"
            "作息或生活规律受到明显影响、原本能正常完成的生活事务难以完成。"
            "依据 NICE 对社会功能的要求加入。"
        ),
    )


# ---------------------------------------------------------------------------
# metadata —— 技术字段（不属于用户界面报告区块）
# ---------------------------------------------------------------------------


class EvaluationMetadata(_SchemaBase):
    """报告的技术元信息，用于后端追踪与后续报告对齐。

    注意：``metadata`` **不属于用户界面的报告区块**，不展示给普通用户，
    因此这里不包含任何用户可读文案，也不包含 ``user_id``。
    """

    schema_version: Literal["1.0"] = Field(
        ...,
        description=(
            '本次输出遵循的 Schema 版本，当前固定为 "1.0"；'
            "格式不符时直接报错，避免不同版本的报告混用。"
        ),
    )
    assessment_id: NonEmptyStr = Field(
        ...,
        description="本次评估的唯一标识，用于后端追踪与报告对齐；必须为非空字符串。",
    )
    generated_at: datetime = Field(
        ...,
        description=(
            "报告生成时间（标准 datetime）。建议传带时区的时间，"
            "便于与其他报告做先后比较。"
        ),
    )


# ---------------------------------------------------------------------------
# 1. overall_status —— 本次心理状态
# ---------------------------------------------------------------------------


class OverallStatus(_SchemaBase):
    """本次心理状态：给用户的第一印象，回答"这次整体怎么样"。

    ``concern_index`` 是系统内部的**综合心理状态关注指数**，
    不是医学诊断结果，也不代表任何临床量表分数。
    """

    level: OverallLevel = Field(
        ...,
        description=(
            "本次心理状态关注等级，只能取 low_concern / mild_concern / "
            "moderate_concern / high_concern。"
        ),
    )
    concern_index: Score0To100 = Field(
        ...,
        description=(
            "0-100 的整数综合心理状态关注指数。"
            "分数越高，代表本次对话中值得关注的心理状态信号越突出："
            "0 = 当前未发现明显关注信号，100 = 关注信号非常突出。"
            "该指数是系统内部的展示指标，不代表医学诊断结果。"
        ),
    )
    summary: NonEmptyStr = Field(..., description="给用户看的简短总体说明。")


# ---------------------------------------------------------------------------
# 2. psychological_profile —— 五维心理状态画像
# ---------------------------------------------------------------------------


class PsychologicalProfile(_SchemaBase):
    """五维心理状态画像，五个维度固定且缺一不可。

    每项都是 0-100 的**整数**，方向统一为"分数越高，表示该维度当前
    值得关注的信号越明显"（即分数高 = 更值得关注，不是"分数高 = 更好"）。
    """

    emotion: Score0To100 = Field(..., description=DIMENSION_LABELS["emotion"])
    interest_motivation: Score0To100 = Field(
        ..., description=DIMENSION_LABELS["interest_motivation"]
    )
    sleep_energy: Score0To100 = Field(..., description=DIMENSION_LABELS["sleep_energy"])
    attention_thinking: Score0To100 = Field(
        ..., description=DIMENSION_LABELS["attention_thinking"]
    )
    social_daily: Score0To100 = Field(..., description=DIMENSION_LABELS["social_daily"])


# ---------------------------------------------------------------------------
# 3. primary_concern —— 最值得关注的问题
# ---------------------------------------------------------------------------


class PrimaryConcern(_SchemaBase):
    """本次最值得关注的一个方面。

    告诉用户"本次最值得关注的是哪一个维度"。
    例：dimension="sleep_energy"，description="本次对话中，睡眠与精力状态的变化最为明显。"

    v1.0 起 ``dimension`` 必须是五个维度之一，不再允许空字符串。
    """

    dimension: PsychologicalDimension = Field(
        ...,
        description=(
            "最值得关注的维度，必须是五维之一："
            f"{', '.join(DIMENSIONS)}；不允许空值。"
        ),
    )
    description: NonEmptyStr = Field(
        ..., description="用自然语言说明为什么关注这个维度。"
    )


# ---------------------------------------------------------------------------
# 4. key_findings —— 关键发现
# ---------------------------------------------------------------------------


class KeyFinding(_SchemaBase):
    """一条面向用户的核心发现。

    例如：title="睡眠状态"，description="你提到近期经常较晚入睡，并且白天容易感到疲惫。"

    本阶段不生成任何真实心理判断，只定义结构与长度约束。
    """

    title: NonEmptyStr = Field(..., description="发现的小标题，尽量短且用户能看懂。")
    description: NonEmptyStr = Field(..., description="该发现的具体说明。")


# ---------------------------------------------------------------------------
# 5. multimodal_observation —— 语言 × 视觉综合观察
# ---------------------------------------------------------------------------


class MultimodalObservation(_SchemaBase):
    """语言信息与视觉信息的综合观察。

    用于整合对话语言信息、摄像头视觉状态以及二者之间的综合观察。

    注意：``consistency_score`` / ``consistency_level`` 只表示**系统观察到的
    语言信号与视觉信号的一致程度**，用于提示"说法与表现是否对得上"，
    它**不代表诊断置信度**，也不表示用户"是否诚实"。
    """

    consistency_score: Score0To100 = Field(
        ...,
        description=(
            "0-100 的整数一致性分数。分数越高，代表对话语言信息与视觉观察"
            "的一致程度越高。注意方向与关注指数相反：这里分数高表示更一致。"
        ),
    )
    consistency_level: ConsistencyLevel = Field(
        ...,
        description=(
            "一致性等级，只能取 low / moderate / high / unknown；"
            "unknown 用于视觉数据缺失或不足以判断的情况。"
        ),
    )
    summary: NonEmptyStr = Field(
        ...,
        description="语言 × 视觉的综合观察总结，供用户直接阅读。",
    )


# ---------------------------------------------------------------------------
# 6. trend_and_suggestions —— 状态变化与个性化建议
# ---------------------------------------------------------------------------


class TrendAndSuggestions(_SchemaBase):
    """整段对话中的状态变化，以及给用户的个性化建议。

    当前只做"整段对话的一个总体趋势 + 一段说明"，不引入复杂时间序列。
    """

    trend: TrendDirection = Field(
        ...,
        description=(
            "整段对话中心理状态的变化方向，只能取 improving / stable / "
            "fluctuating / worsening / unclear。"
        ),
    )
    trend_summary: NonEmptyStr = Field(
        ..., description="描述整段对话中心理状态的变化。"
    )
    suggestions: list[NonEmptyStr] = Field(
        ...,
        min_length=MIN_SUGGESTIONS,
        max_length=MAX_SUGGESTIONS,
        description=(
            f"给用户的个性化建议列表，{MIN_SUGGESTIONS}-{MAX_SUGGESTIONS} 条，"
            "每条均为非空字符串。"
        ),
    )


# ---------------------------------------------------------------------------
# 最终输出
# ---------------------------------------------------------------------------


class EvaluationOutput(_SchemaBase):
    """Evaluation Agent 面向用户的最终输出：一份**已完成**的心理状态评估报告。

    固定包含 6 个报告区块（缺一不可），外加 1 个技术字段 ``metadata``：

    1. overall_status         本次心理状态
    2. psychological_profile  五维心理状态画像
    3. primary_concern        最值得关注的问题
    4. key_findings           关键发现（2-4 条）
    5. multimodal_observation 语言 × 视觉综合观察
    6. trend_and_suggestions  状态变化与个性化建议
    -  metadata               技术元信息（不展示给普通用户）

    未完成评估时**不要**构造本对象：报告一经构造即代表评估已完成，
    因此不存在 "pending" 之类的中间状态。

    派生关系（构造时会强制校验，三者矛盾直接报错）::

        psychological_profile（五维分数，源数据）
                    ↓  0.7 × 平均分 + 0.3 × 最高分（见 evaluation_agent.scoring）
            overall_status.concern_index
                    ↓  固定阈值分档
            overall_status.level
    """

    overall_status: OverallStatus = Field(..., description="1. 本次心理状态")
    psychological_profile: PsychologicalProfile = Field(
        ..., description="2. 五维心理状态画像"
    )
    primary_concern: PrimaryConcern = Field(..., description="3. 最值得关注的问题")
    key_findings: list[KeyFinding] = Field(
        ...,
        min_length=MIN_KEY_FINDINGS,
        max_length=MAX_KEY_FINDINGS,
        description=f"4. 关键发现，{MIN_KEY_FINDINGS}-{MAX_KEY_FINDINGS} 条",
    )
    multimodal_observation: MultimodalObservation = Field(
        ..., description="5. 语言 × 视觉综合观察"
    )
    trend_and_suggestions: TrendAndSuggestions = Field(
        ..., description="6. 状态变化与个性化建议"
    )
    metadata: EvaluationMetadata = Field(
        ..., description="技术元信息；不属于用户界面报告区块"
    )

    # -- 跨字段一致性（派生值不得与源数据矛盾） -----------------------------

    @model_validator(mode="after")
    def _check_derived_fields_are_consistent(self) -> "EvaluationOutput":
        """强制 concern_index 与 level 必须由五维画像推导得出。

        校验两步：

        1. ``overall_status.concern_index`` 必须等于
           ``calculate_concern_index(psychological_profile)``；
        2. ``overall_status.level`` 必须等于
           ``get_overall_level(concern_index)``。

        任何一步不一致都直接报错，防止报告内部自相矛盾
        （例如五维全为 20 却宣称 high_concern）。
        """
        # 局部导入：scoring 依赖本模块的类型，放在模块顶层会形成循环导入。
        from .scoring import calculate_concern_index, get_overall_level

        expected_index = calculate_concern_index(self.psychological_profile)
        if self.overall_status.concern_index != expected_index:
            raise ValueError(
                f"overall_status.concern_index="
                f"{self.overall_status.concern_index} 与五维画像推导出的 "
                f"{expected_index} 不一致；concern_index 是派生值，"
                "必须由 psychological_profile 计算得到。"
            )

        expected_level = get_overall_level(expected_index)
        if self.overall_status.level != expected_level:
            raise ValueError(
                f"overall_status.level={self.overall_status.level.value!r} 与 "
                f"concern_index={expected_index} 应处的 "
                f"{expected_level.value!r} 不一致；level 必须由 concern_index "
                "推导，不允许自由指定。"
            )

        return self

    # -- 序列化辅助（纯数据转换，不含任何业务逻辑） -------------------------

    def to_json_str(self, *, indent: int = 2) -> str:
        """序列化为 JSON 字符串；中文不转义，便于人工阅读。"""
        return self.model_dump_json(indent=indent)

    def to_dict(self) -> dict[str, Any]:
        """转为 JSON 安全的 dict（枚举转字符串、datetime 转 ISO 字符串）。

        注意 ``model_dump()`` 默认是 python 模式，会保留枚举成员与 datetime
        对象；需要交给 json.dumps / 前端时请使用本方法。
        """
        return self.model_dump(mode="json")

    @classmethod
    def from_json_str(cls, data: str) -> "EvaluationOutput":
        """从 JSON 字符串构造并严格校验；不合法时抛出 pydantic.ValidationError。"""
        return cls.model_validate_json(data)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "EvaluationOutput":
        """从 UTF-8 JSON 文件读取并严格校验。"""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def to_json_file(self, path: str | Path, *, indent: int = 2) -> None:
        """写入 UTF-8 JSON 文件（中文不转义）。"""
        Path(path).write_text(self.to_json_str(indent=indent) + "\n", encoding="utf-8")
