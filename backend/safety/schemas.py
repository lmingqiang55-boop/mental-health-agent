# -*- coding: utf-8 -*-
"""心理安全判定的数据结构（新 Safety，系统唯一的心理安全检测入口）。

设计要点（与旧 risk_engine 完全无关）：

1. ``route`` 不由模型产出，而是由 :func:`derive_route` 从 ``risk_level`` 派生。
   模型输出结构 :class:`SafetyModelOutput` 里**没有** route 字段，
   因此「NORMAL 必须对应 CONTINUE」之类的规则不可能被违反。

2. ``hotline_numbers`` 也不由模型产出。模型输出里没有该字段，
   号码只能由后端从已核实配置注入，模型无从编造。

3. ``risk_detected`` 同样派生自 ``risk_level``，不给模型多一个出错的机会。

4. 模型失败（超时/解析失败/不可用）**不得**放行：
   :func:`build_failed_verdict` 只会产出 UNCERTAIN + SAFETY_REVIEW。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "SafetyLevel",
    "SafetyRoute",
    "ModelStatus",
    "SafetyStage",
    "SafetySignal",
    "SafetyModelOutput",
    "SafetyVerdict",
    "SafetyAgentError",
    "derive_route",
    "derive_risk_detected",
    "build_failed_verdict",
    "assemble_verdict",
    "PHONE_LIKE",
]


class SafetyLevel(str, Enum):
    """新版安全结论。注意：与评估域的 RiskLevel(low/medium/high) 是两套词汇。

    取值统一用小写，与项目其余枚举（RiskLevel / SessionStage / MessageRole）
    保持一致。提示词里为了醒目使用大写书写，解析时大小写不敏感（见
    :meth:`SafetyModelOutput.normalize_risk_level`），因此模型输出
    ``"HIGH"`` 或 ``"high"`` 都能正确解析。
    """

    NORMAL = "normal"
    UNCERTAIN = "uncertain"
    HIGH = "high"
    IMMINENT = "imminent"


class SafetyRoute(str, Enum):
    """安全路由。决定本轮是否进入普通评估对话循环。"""

    CONTINUE = "continue"
    SAFETY_REVIEW = "safety_review"
    SAFETY_STOP = "safety_stop"


class ModelStatus(str, Enum):
    """Safety 模型调用的结果状态。"""

    ok = "ok"
    timeout = "timeout"
    parse_error = "parse_error"
    unavailable = "unavailable"


#: 会话级安全阶段。与 SessionStage 的 SAFETY_REVIEW / SAFETY_STOP 对应。
#: 只会单向推进：none -> review -> stopped，**不会自动回退**。
SafetyStage = Literal["none", "review", "stopped"]


#: risk_level -> route 的唯一映射来源。覆盖全部枚举值，不存在 KeyError 分支。
_DERIVED_ROUTE: dict[SafetyLevel, SafetyRoute] = {
    SafetyLevel.NORMAL: SafetyRoute.CONTINUE,
    SafetyLevel.UNCERTAIN: SafetyRoute.SAFETY_REVIEW,
    SafetyLevel.HIGH: SafetyRoute.SAFETY_STOP,
    SafetyLevel.IMMINENT: SafetyRoute.SAFETY_STOP,
}

#: 疑似电话号码：连续 5 位以上数字，或 3-4 位 + 分隔符 + 4 位以上。
#: 只用于拦截模型把号码写进自然语言正文，不影响 110/120 这类行动提醒。
PHONE_LIKE = re.compile(r"\d{5,}|\d{3,4}[-\s]\d{4,}")


class SafetyAgentError(RuntimeError):
    """Safety Agent 无法给出结论（配置缺失等）。调用方必须按未放行处理。"""


class SafetySignal(BaseModel):
    """危险表达关键词命中。**只是辅助线索**，不参与 risk_level 的决定。"""

    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1, max_length=64)
    negated: bool = False
    source: Literal["latest_message", "history"]


class SafetyModelOutput(BaseModel):
    """Safety 模型的**全部**结构化输出。

    刻意不包含 route / risk_detected / hotline_numbers：
    前两者由后端派生，后者由后端从已核实配置注入。
    """

    model_config = ConfigDict(extra="forbid")

    risk_level: SafetyLevel
    evidence_quotes: list[str] = Field(default_factory=list, max_length=5)
    rationale: str = Field(default="", max_length=600)
    # NORMAL 无需面向用户的消息；非 NORMAL 必须有，否则无法履行安全义务。
    support_message: str = Field(default="", max_length=600)

    @field_validator("risk_level", mode="before")
    @classmethod
    def normalize_risk_level(cls, value: Any) -> Any:
        """大小写不敏感：提示词用大写书写，模型输出 `HIGH` 或 `high` 都要能收。

        未知等级**不放行**，会由枚举校验拒绝并转成 parse_error -> 人工复核。
        """
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @model_validator(mode="after")
    def non_normal_needs_message(self) -> "SafetyModelOutput":
        if self.risk_level is not SafetyLevel.NORMAL and not self.support_message.strip():
            raise ValueError("非 NORMAL 结论必须给出 support_message")
        return self


class SafetyVerdict(BaseModel):
    """后端组装后的最终安全结论。这是系统唯一的安全状态来源。"""

    model_config = ConfigDict(extra="forbid")

    risk_detected: bool
    risk_level: SafetyLevel
    route: SafetyRoute
    messages: list[str] = Field(default_factory=list, max_length=3)
    hotline_numbers: list[str] = Field(default_factory=list)

    # 引擎侧元数据（不展示给学生）
    model_status: ModelStatus
    keyword_signals: list[SafetySignal] = Field(default_factory=list)
    rationale: str | None = None
    evidence_quotes: list[str] = Field(default_factory=list)
    engine: Literal["graph_safety_v1"] = "graph_safety_v1"

    @model_validator(mode="after")
    def route_matches_level(self) -> "SafetyVerdict":
        """一致性校验：等级与路由必须匹配派生表。"""
        if _DERIVED_ROUTE[self.risk_level] is not self.route:
            raise ValueError(
                f"risk_level={self.risk_level.value} 与 route={self.route.value} 不一致"
            )
        return self

    @model_validator(mode="after")
    def risk_detected_matches_level(self) -> "SafetyVerdict":
        if self.risk_detected is not (self.risk_level is not SafetyLevel.NORMAL):
            raise ValueError("risk_detected 必须由 risk_level 派生")
        return self

    @model_validator(mode="after")
    def failure_never_continues(self) -> "SafetyVerdict":
        """模型失败绝不放行。"""
        if self.model_status is not ModelStatus.ok and self.route is SafetyRoute.CONTINUE:
            raise ValueError("模型未成功时不得返回 CONTINUE")
        return self

    @model_validator(mode="after")
    def no_phone_numbers_in_messages(self) -> "SafetyVerdict":
        """任务2 只允许通过 hotline_numbers 暴露号码，正文里不得内嵌。"""
        for message in self.messages:
            if PHONE_LIKE.search(message):
                raise ValueError("安全消息正文不得内嵌电话号码，号码须走 hotline_numbers")
        return self

    @property
    def halted(self) -> bool:
        """是否应停止普通评估循环。"""
        return self.route is not SafetyRoute.CONTINUE


def derive_route(level: SafetyLevel) -> SafetyRoute:
    """``risk_level`` -> ``route`` 的唯一映射来源。"""
    return _DERIVED_ROUTE[level]


def derive_risk_detected(level: SafetyLevel) -> bool:
    return level is not SafetyLevel.NORMAL


def build_failed_verdict(
    status: ModelStatus,
    keywords: Sequence[SafetySignal] = (),
    fallback_message: str = "",
) -> SafetyVerdict:
    """模型未成功时的兜底结论：进入安全澄清，绝不放行。

    关键词命中**不**用于升级等级——按已确认口径，孤立的危险关键词
    不直接判定 HIGH；这里只把命中项作为人工复核线索记录下来。
    """
    if status is ModelStatus.ok:
        raise ValueError("build_failed_verdict 只处理失败的模型状态")
    return SafetyVerdict(
        risk_detected=True,
        risk_level=SafetyLevel.UNCERTAIN,
        route=SafetyRoute.SAFETY_REVIEW,
        messages=[fallback_message] if fallback_message else [],
        hotline_numbers=[],
        model_status=status,
        keyword_signals=list(keywords),
        rationale="安全判定服务暂时不可用，先暂停普通评估并交由人工确认。",
    )


def assemble_verdict(
    *,
    output: SafetyModelOutput | None,
    status: ModelStatus,
    hotlines: Sequence[str] = (),
    allowed_hotlines: frozenset[str] = frozenset(),
    extra_signals: Sequence[SafetySignal] = (),
    fallback_message: str = "",
) -> SafetyVerdict:
    """把模型输出组装成最终结论。**号码白名单在此强制校验。**

    Args:
        output: 模型输出；失败时为 None。
        status: 模型调用状态。
        hotlines: 后端选择出的号码（仅 SAFETY_STOP 会用到）。
        allowed_hotlines: 已核实号码白名单；不在白名单内的号码直接拒绝。
        extra_signals: 关键词辅助线索。
        fallback_message: 失败时使用的安全侧模板。
    """
    if output is None or status is not ModelStatus.ok:
        return build_failed_verdict(status, extra_signals, fallback_message)

    route = derive_route(output.risk_level)
    numbers: list[str] = []
    if route is SafetyRoute.SAFETY_STOP:
        numbers = list(hotlines)
        unknown = [number for number in numbers if number not in allowed_hotlines]
        if unknown:
            raise ValueError(f"未在白名单中的热线号码：{unknown}")

    return SafetyVerdict(
        risk_detected=derive_risk_detected(output.risk_level),
        risk_level=output.risk_level,
        route=route,
        messages=[output.support_message] if output.support_message else [],
        hotline_numbers=numbers,
        model_status=status,
        keyword_signals=list(extra_signals),
        rationale=output.rationale or None,
        evidence_quotes=list(output.evidence_quotes),
    )
