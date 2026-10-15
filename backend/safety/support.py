# -*- coding: utf-8 -*-
"""安全分支的处理规则：澄清模式与支持模式。

这是新 Safety 的「操作规则」层。它只消费 :class:`SafetyVerdict`，
不含任何风险判定逻辑——判定完全由 Safety Agent 负责。

【两种安全模式的区别（按已确认口径）】

- ``UNCERTAIN`` -> **澄清模式**（``SAFETY_REVIEW``）：暂停普通评估。
  下一轮若 Safety 判为 NORMAL，可以恢复普通评估。用词是"暂停"。
- ``HIGH`` / ``IMMINENT`` -> **支持模式**（``SAFETY_STOP``）：停止普通评估。
  一旦进入就**会话内永不自动解除**，仅人工/管理端可解除。
  后续任何一条正常表达都不得让它自动恢复。

因此 ``safety_stage`` 是当前模式（可回退到 none），
``safety_halted`` 是单向的停止锁（只置 True，不自动复位）。
"""

from __future__ import annotations

from backend.models.enums import SessionStage
from backend.safety.schemas import SafetyRoute, SafetyVerdict

__all__ = [
    "SUPPORT_MODE_CONTINUATION_MESSAGE",
    "REVIEW_MODE_CONTINUATION_MESSAGE",
    "safety_blocks_normal_flow",
    "safety_reply_messages",
    "safety_next_strategy",
    "safety_stage_value",
    "safety_session_stage",
]

#: 已在支持模式时，若该轮 Safety 未给出面向用户的消息（例如判为 NORMAL），
#: 用它保证学生仍然收到有意义的回应，而不是空气泡。
SUPPORT_MODE_CONTINUATION_MESSAGE = (
    "我还在。你不用急着说清楚，我们可以慢慢来。"
    "如果你现在身边有人，可以让他们陪着你。"
)

#: 澄清模式的兜底消息。
REVIEW_MODE_CONTINUATION_MESSAGE = (
    "我想再确认一下你现在的状况。你可以多说一点，我在听。"
)


def safety_blocks_normal_flow(*, safety_halted: bool, safety_stage: str) -> bool:
    """普通对话/治愈入口的统一守卫。

    安全暂停或中止期间，Healing 等普通入口不得继续。
    """
    return bool(safety_halted) or safety_stage != "none"


def safety_reply_messages(verdict: SafetyVerdict, *, already_halted: bool) -> list[str]:
    """给出本轮面向用户的消息（1~3 条）。

    Args:
        verdict: 本轮 Safety 结论。
        already_halted: 本轮开始时会话是否已处于支持模式。
    """
    if verdict.messages:
        return list(verdict.messages)
    if already_halted:
        return [SUPPORT_MODE_CONTINUATION_MESSAGE]
    if verdict.route is SafetyRoute.SAFETY_REVIEW:
        return [REVIEW_MODE_CONTINUATION_MESSAGE]
    return []


def safety_next_strategy(verdict: SafetyVerdict, *, already_halted: bool) -> str:
    """安全分支的 next_strategy。与普通对话的动作词汇区分开。"""
    if verdict.route is SafetyRoute.SAFETY_STOP or already_halted:
        return "safety_support"
    return "safety_review"


def safety_stage_value(verdict: SafetyVerdict, previous_stage: str) -> str:
    """推进 safety_stage。只单向：stopped 不会被 review/none 覆盖。"""
    if previous_stage == "stopped" or verdict.route is SafetyRoute.SAFETY_STOP:
        return "stopped"
    if verdict.route is SafetyRoute.SAFETY_REVIEW:
        return "review"
    return "none"


def safety_session_stage(stage_value: str) -> SessionStage | None:
    """safety_stage -> SessionStage。``none`` 时不需要改动会话阶段。"""
    if stage_value == "stopped":
        return SessionStage.SAFETY_STOP
    if stage_value == "review":
        return SessionStage.SAFETY_REVIEW
    return None
