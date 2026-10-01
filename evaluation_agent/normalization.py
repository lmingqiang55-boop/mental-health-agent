# -*- coding: utf-8 -*-
"""大模型原始产出 → 内部严格值的**归一化层**，以及 evidence/reason 的后台记录。

数据流位置::

    EvaluationInput
          ↓
    [未来：强模型]
          ↓
    RawLLMAssessment（未归一化：score 可能是 2 / 2.0 / "2" / " 2 "）
          ↓  normalize_item_score() / extract_item_scores()      <- 本模块
    AssessmentItemScores（严格：11 个 0-3 整数）
          ↓  scoring.calculate_psychological_profile()
    PsychologicalProfile（五维）
          ↓  scoring.calculate_concern_index()
    concern_index
          ↓  scoring.get_overall_level()
    OverallLevel

分工原则
--------

- **宽松接收**：只接受"明确无歧义的数字写法"，把它们安全转成整数；
  模型输出的噪音形态（``2.0`` / ``" 2 "``）不该让整份评估失败。
- **严格拒绝**：非整数（``2.5``）、布尔（``True``）、越界（``-1`` / ``4``）、
  非数字（``"moderate"``）一律报错，**绝不猜测**模型想表达什么。
- **一次报全**：所有小项的分数一次性归一化，
  错误会汇总成 :class:`ItemScoreNormalizationError` 并列出每一个失败项与原因，
  而不是遇到第一个坏值就退出。

evidence / reason 的保存
------------------------

11 个小项的 ``score`` / ``evidence`` / ``reason`` 属于**后端内部审计数据**，
通过 :class:`ItemAssessmentDetails` 单独保存，
**不进入**用户可见的 ``EvaluationOutput``（该模型里没有任何相关字段）。

本模块**不包含**自伤 / 自杀或其他安全风险字段。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import Field, field_validator, model_validator

from .base import MAX_ITEM_SCORE, MIN_ITEM_SCORE, ItemScore, NonEmptyStr, StrictSchemaBase
from .raw_assessment import (
    EvidenceList,
    ItemAssessment,
    RawItemScore,
    RawLLMAssessment,
    wrap_evidence,
)
from .schemas import ITEM_KEYS, SCHEMA_VERSION, AssessmentItemScores

__all__ = [
    "MIN_ITEM_SCORE",
    "MAX_ITEM_SCORE",
    "ItemScoreNormalizationError",
    "normalize_item_score",
    "extract_item_scores",
    "ItemAssessmentRecord",
    "ItemAssessmentDetails",
    "build_item_details",
]


class ItemScoreNormalizationError(ValueError):
    """一个或多个小项的分数无法安全归一化。

    继承 ``ValueError``，因此调用方可以只写 ``except ValueError``；
    需要按小项重试 / 修复时，可以读取 :attr:`failures`。

    :param failures: ``{小项字段名: 失败原因}``，按 :data:`ITEM_KEYS` 顺序排列。
    """

    def __init__(self, failures: Mapping[str, str]) -> None:
        self.failures: dict[str, str] = dict(failures)
        detail = "；".join(f"{item}: {reason}" for item, reason in self.failures.items())
        super().__init__(
            f"{len(self.failures)} 个小项的分数无法归一化（{detail}）。"
            "小项分数必须是 0-3 的整数，请检查模型输出。"
        )


def normalize_item_score(value: Any) -> int:
    """把大模型返回的分数安全归一化为 0-3 的整数。

    允许（明确无歧义的数字写法）::

        2  ->  2        # 标准情形
        2.0 -> 2        # 整数值浮点
        "2" -> 2        # 数字字符串
        " 2 " -> 2      # 带空白
        "2.0" -> 2      # 整数值浮点字符串
        0 / 3.0 / "3" -> 0 / 3 / 3

    拒绝（绝不猜测）::

        2.5 / "2.5"     # 非整数，不做四舍五入
        True / False    # 布尔值（bool 是 int 的子类，必须显式拒绝）
        -1 / 4 / 100    # 越界
        "moderate" / "" / " " / None / [] / {}   # 非数字或空值

    注意：这里只做**类型与区间**的归一化，不改变数值大小、不做四舍五入、
    不做语义映射（例如不会把 ``"moderate"`` 猜成 2）。

    :param value: 模型返回的原始分数。
    :returns: 0-3 的整数。
    :raises ValueError: 无法安全归一化时，错误信息包含原始值与原因。
    """
    # bool 是 int 的子类，必须先于 int 判断，否则 True 会被当成 1。
    if isinstance(value, bool):
        raise ValueError(
            f"不能把布尔值 {value!r} 当作小项分数（True/False 不是 0-3 的分数）"
        )

    if isinstance(value, int):
        number: int = value
    elif isinstance(value, float):
        number = _int_from_float(value)
    elif isinstance(value, str):
        number = _int_from_str(value)
    else:
        raise ValueError(
            f"无法把小项分数 {value!r}（类型 {type(value).__name__}）归一化为整数；"
            "只接受整数、浮点数或数字字符串"
        )

    if not MIN_ITEM_SCORE <= number <= MAX_ITEM_SCORE:
        raise ValueError(
            f"小项分数 {value!r} 超出合法范围 "
            f"{MIN_ITEM_SCORE}-{MAX_ITEM_SCORE}"
        )
    return number


def _int_from_float(value: float) -> int:
    """整数值浮点转 int；非整数、nan、inf 一律拒绝。"""
    if not value.is_integer():
        raise ValueError(
            f"小项分数 {value!r} 不是整数；不做四舍五入，请让模型给出 0-3 的整数"
        )
    return int(value)


def _int_from_str(value: str) -> int:
    """数字字符串转 int；允许两侧空白与整数值浮点写法。"""
    text = value.strip()
    if not text:
        raise ValueError("小项分数是空字符串或纯空白，无法归一化")

    try:
        return int(text)
    except ValueError:
        pass

    # 退回浮点解析，接受 "2.0" 这类整数值写法；"2.5" 随后会被判为非整数。
    try:
        parsed = float(text)
    except ValueError:
        raise ValueError(
            f"小项分数 {value!r} 不是可识别的数字；"
            "只接受 0-3 的整数（如 2 / 2.0 / \"2\"）"
        ) from None
    return _int_from_float(parsed)


def _normalized_scores(raw: RawLLMAssessment) -> dict[str, int]:
    """把 11 个小项的分数全部归一化，失败项汇总后一次性报错。"""
    scores: dict[str, int] = {}
    failures: dict[str, str] = {}

    for item in ITEM_KEYS:
        assessment: ItemAssessment = getattr(raw, item)
        try:
            scores[item] = normalize_item_score(assessment.score)
        except ValueError as error:
            failures[item] = str(error)

    if failures:
        raise ItemScoreNormalizationError(failures)
    return scores


def extract_item_scores(raw: RawLLMAssessment) -> AssessmentItemScores:
    """从模型原始产出中提取 11 个归一化后的小项分数。

    这是归一化层对外的唯一入口：返回值是**严格**的
    :class:`~evaluation_agent.schemas.AssessmentItemScores`，
    可以直接进入五维计算链路。

    :param raw: 已经通过结构校验的模型原始产出。
    :returns: 11 个 0-3 整数组成的小项分数。
    :raises ItemScoreNormalizationError: 任一分数无法安全归一化
        （一次性列出全部失败项）。
    """
    return AssessmentItemScores(**_normalized_scores(raw))


class ItemAssessmentRecord(StrictSchemaBase):
    """**后端内部**记录：单个小项的归一化分数 + 原始分数 + 依据 + 理由。

    该模型不进入用户可见报告，仅用于后端保存与审计：
    出问题时可以回答"这个分数是从哪句话、按什么理由得出的"。
    """

    item: str = Field(
        ...,
        description=f"小项字段名，必须是 11 个小项之一：{', '.join(ITEM_KEYS)}。",
    )
    score: ItemScore = Field(
        ...,
        description="归一化后的分数（0-3 整数），与 AssessmentItemScores 中的值一致。",
    )
    raw_score: RawItemScore = Field(
        ...,
        description="模型返回的原始分数（未经归一化），保留原形态以便排查模型输出漂移。",
    )
    evidence: EvidenceList = Field(
        ...,
        description=(
            "对话中的原始依据，至少 1 条（引用或贴近原话的转述）。"
            "对话未提及该方面时为 [\"对话中未提及相关表现\"]。"
        ),
    )
    reason: NonEmptyStr = Field(
        ..., description="为什么据此给出该分数：判断理由。"
    )

    @field_validator("evidence", mode="before")
    @classmethod
    def _accept_single_string_evidence(cls, value: Any) -> Any:
        """与原始产出层一致：允许裸字符串，自动包装成列表。"""
        return wrap_evidence(value)

    @model_validator(mode="after")
    def _check_item_is_known(self) -> "ItemAssessmentRecord":
        if self.item not in ITEM_KEYS:
            raise ValueError(
                f"item={self.item!r} 不是合法的小项字段名；"
                f"必须是以下之一：{', '.join(ITEM_KEYS)}"
            )
        return self


class ItemAssessmentDetails(StrictSchemaBase):
    """**后端内部**保存单元：11 个小项的 score / evidence / reason 明细。

    用途与边界：

    - 与用户可见报告通过 ``assessment_id`` 关联
      （即 ``EvaluationOutput.metadata.assessment_id``）；
    - **不进入** ``EvaluationOutput``，用户看不到 evidence 与 reason，
      也看不到原始分数；
    - 用 ``to_json_str()`` / ``to_json_file()`` 单独落库或写文件。

    必须**恰好** 11 条，且 11 个小项各出现一次、不重复、不遗漏。
    """

    assessment_id: NonEmptyStr = Field(
        ...,
        description="与 EvaluationOutput.metadata.assessment_id 相同的评估标识，用于关联。",
    )
    schema_version: Literal["1.0"] = Field(
        default="1.0",
        description=f"明细记录格式版本，当前固定为 {SCHEMA_VERSION!r}。",
    )
    items: list[ItemAssessmentRecord] = Field(
        ...,
        min_length=len(ITEM_KEYS),
        max_length=len(ITEM_KEYS),
        description="11 个小项的明细，每个小项恰好一条。",
    )

    @model_validator(mode="after")
    def _check_items_cover_all_keys(self) -> "ItemAssessmentDetails":
        seen = [record.item for record in self.items]
        duplicates = sorted({item for item in seen if seen.count(item) > 1})
        if duplicates:
            raise ValueError(f"items 中有重复的小项：{', '.join(duplicates)}")
        missing = [item for item in ITEM_KEYS if item not in seen]
        if missing:
            raise ValueError(
                f"items 缺少以下小项：{', '.join(missing)}"
                f"（必须完整覆盖 11 个小项）"
            )
        return self

    def by_item(self) -> dict[str, ItemAssessmentRecord]:
        """按小项字段名取明细，便于后端写入结构化存储。"""
        return {record.item: record for record in self.items}

    def to_json_str(self, *, indent: int = 2) -> str:
        """序列化为 JSON 字符串（中文不转义），用于后台保存。"""
        return self.model_dump_json(indent=indent)

    def to_json_file(self, path: str | Path, *, indent: int = 2) -> None:
        """写入 JSON 文件，末尾补一个换行。"""
        Path(path).write_text(self.to_json_str(indent=indent) + "\n", encoding="utf-8")

    @classmethod
    def from_json_str(cls, data: str) -> "ItemAssessmentDetails":
        """从 JSON 字符串读回并严格校验（例如从数据库取出的明细）。"""
        return cls.model_validate_json(data)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "ItemAssessmentDetails":
        """从 JSON 文件读回并严格校验。"""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


def build_item_details(
    raw: RawLLMAssessment, assessment_id: str
) -> ItemAssessmentDetails:
    """由模型原始产出生成**后台明细记录**（不只是分数，还含 evidence / reason）。

    与 :func:`extract_item_scores` 共用同一套归一化逻辑，
    因此两边的小项分数**必然一致**，不会出现"报告里是 2、明细里是 3"。

    :param raw: 模型原始产出。
    :param assessment_id: 本次评估的标识，应与报告的 ``metadata.assessment_id`` 相同。
    :returns: 含 11 条明细的后台记录。
    :raises ItemScoreNormalizationError: 任一分数无法安全归一化。
    """
    scores = _normalized_scores(raw)

    records = [
        ItemAssessmentRecord(
            item=item,
            score=scores[item],
            raw_score=getattr(raw, item).score,
            evidence=getattr(raw, item).evidence,
            reason=getattr(raw, item).reason,
        )
        for item in ITEM_KEYS
    ]
    return ItemAssessmentDetails(assessment_id=assessment_id, items=records)
