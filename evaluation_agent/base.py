# -*- coding: utf-8 -*-
"""公共 pydantic 基类：严格层与宽松层。

本项目有三层数据：

1. **输入层**：``EvaluationInput``（后端自己构造）——严格；
2. **大模型原始输出层**：``RawLLMAssessment``（强模型产出，形态可能不规范）——宽松；
3. **正式协议层**：``AssessmentItemScores`` / ``EvaluationOutput``（对外契约）——严格。

严格与宽松的唯一区别是**未知字段**的处理方式，两条全局约束在此统一定义，
避免各模块各写一份：

- ``extra="forbid"``（严格）：出现未定义字段直接报错，防止协议被悄悄改变；
- ``extra="allow"``（宽松）：未知字段保留在 ``model_extra`` 而不报错。
  这是**故意**的：大模型经常多输出一些说明性字段，为了这种噪音让整份
  评估失败并不划算；保留下来还可以让后端观察模型漂移。
  注意这**不会**放过结构性错误——少字段、类型错、空字符串依旧报错。

两层都拒绝布尔值：``bool`` 是 ``int`` 的子类，若放行，
``True`` / ``False`` 会被静默转换成 1 / 0 分，属于调用错误。
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Final

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

__all__ = [
    "reject_bool",
    "ValueStrEnum",
    "StrictSchemaBase",
    "LenientSchemaBase",
    "UpstreamSchemaBase",
    "NonEmptyStr",
    "Score0To100",
    "NonNegativeCount",
    "UnitFloat",
    "SignedUnitFloat",
    "MIN_ITEM_SCORE",
    "MAX_ITEM_SCORE",
    "ItemScore",
]


class ValueStrEnum(str, Enum):
    """字符串枚举基类。

    继承 ``(str, Enum)`` 时，Python 3.11+ 的 f-string / ``str()`` 会输出
    ``"OverallLevel.LOW_CONCERN"`` 而不是枚举值 ``"low_concern"``，
    容易污染日志与错误信息，因此这里显式覆写 ``__str__``。
    """

    def __str__(self) -> str:
        return self.value


def reject_bool(value: Any, info: ValidationInfo) -> Any:
    """在字段校验前拒绝布尔值，并给出带字段名的错误说明。"""
    if isinstance(value, bool):
        raise ValueError(f"字段 {info.field_name} 不接受布尔值 True/False")
    return value


class _BoolGuardMixin(BaseModel):
    """只提供"拒绝布尔值"这一条全局约束的基类。"""

    @field_validator("*", mode="before")
    @classmethod
    def _reject_bool(cls, value: Any, info: ValidationInfo) -> Any:
        return reject_bool(value, info)


class StrictSchemaBase(_BoolGuardMixin):
    """严格层基类：``extra="forbid"`` + 拒绝布尔值。

    用于后端自己构造的输入，以及所有对外的正式协议模型。
    """

    model_config = ConfigDict(extra="forbid")


class LenientSchemaBase(_BoolGuardMixin):
    """宽松层基类：``extra="allow"`` + 拒绝布尔值。

    用于接收大模型的原始产出：未知字段进入 ``model_extra`` 而不报错，
    但字段缺失、类型错误、空字符串等结构性问题仍然会被拒绝。

    ``model_extra`` 只用于后端诊断，**不参与任何计算**。
    """

    model_config = ConfigDict(extra="allow")


class UpstreamSchemaBase(BaseModel):
    """上游 B 模块（多模态）产出的值对象基类。

    与 :class:`LenientSchemaBase` 有两点不同，都是被上游数据形态逼出来的：

    1. **不做全局布尔守卫**。``LenientSchemaBase`` 的守卫是为了防止 ``True``
       被静默当成 1 分；但上游的 ``face_detected`` 这类字段**本来就是布尔**，
       全局守卫会把合法数据拦下来。需要防布尔的数值字段单独用
       :data:`NonNegativeCount` 声明。
    2. ``extra="allow"``：上游可能同时送来本阶段不处理的字段（例如音频相关的
       ``audio_snapshot``）。我们只"读取"上游数据、不定义上游协议，
       因为多一个字段就拒收整份数据并不划算。

    注意这**不会**放过结构性错误：类型不对、数值超范围依旧报错。
    """

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# 公共字段类型（各模块共用，避免同一约束写多份）
# ---------------------------------------------------------------------------

#: 非空字符串：既不允许空串，也不允许纯空白；**不会**自动 trim 原始内容。
NonEmptyStr = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]

#: 0-100 的整数分数。具体方向由各字段自己的说明定义，不使用浮点数。
Score0To100 = Annotated[int, Field(ge=0, le=100)]

#: 0~1 的浮点量（置信度、效价以外的强度类指标）。
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]

#: -1~1 的浮点量（情绪效价）。
SignedUnitFloat = Annotated[float, Field(ge=-1.0, le=1.0)]

#: 非负计数。带布尔守卫：``True`` 是 ``int`` 的子类，当计数用属于调用错误。
NonNegativeCount = Annotated[int, BeforeValidator(reject_bool), Field(ge=0)]

#: 小项分数的合法区间（闭区间）。归一化层与计算层共用同一组常量。
MIN_ITEM_SCORE: Final[int] = 0
MAX_ITEM_SCORE: Final[int] = 3

#: 单个底层小项的分数：0-3 的整数。
#:
#: 两类小项的 0-3 语义不同（症状类按出现频率，功能影响类按受损程度），
#: 详见 README「理论依据」与 ``schemas.AssessmentItemScores``。
#:
#: 这里使用 ``strict=True``：小项分数是 rubric **直接指定的类别值**，
#: 不是计算得到的聚合值，因此 ``2.0``、``"2"`` 这类写法一律拒绝，
#: 由 ``normalization.normalize_item_score()`` 负责先归一化再进入本类型。
ItemScore = Annotated[
    int, Field(ge=MIN_ITEM_SCORE, le=MAX_ITEM_SCORE, strict=True)
]
