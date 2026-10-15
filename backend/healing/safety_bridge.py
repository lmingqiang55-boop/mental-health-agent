# -*- coding: utf-8 -*-
"""Healing 与「新版 Safety」之间的只读桥接层。

本模块**不做任何风险判定**：不扫关键词、不做正则、不构造 ``RiskResult``。
它只负责三件事：

1. 给出 ``SafetyLevel`` 的序（NORMAL < UNCERTAIN < HIGH < IMMINENT）。
   旧代码用 ``RiskLevel`` 的序比较「新的风险更高才更新」；换成 Safety 之后，
   该序刻意放在 ``backend/safety/schemas.py`` **之外**，不改动安全结论本身。
2. 把会话上的安全状态（``latest_safety`` / ``safety_halted`` / ``safety_stage``）
   解析成本轮 Healing 使用的 :class:`~backend.safety.schemas.SafetyVerdict`。
3. 给出面向用户的危机/支持文案：优先 Safety 结论自带的 ``messages``，
   为空时用 ``backend/safety/support.py`` 的澄清/支持兜底文案。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.safety.projection import (
    SAFETY_LEVEL_ORDER,
    most_severe_verdict as _most_severe_verdict,
    safety_level_priority,
    verdict_is_more_severe,
)
from backend.safety.schemas import (
    ModelStatus,
    SafetyLevel,
    SafetyRoute,
    SafetyVerdict,
    derive_risk_detected,
    derive_route,
)
from backend.safety.support import (
    REVIEW_MODE_CONTINUATION_MESSAGE,
    SUPPORT_MODE_CONTINUATION_MESSAGE,
    safety_reply_messages,
)

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，避免运行期循环导入
    from backend.models.states import SessionState

__all__ = [
    "SAFETY_LEVEL_ORDER",
    "safety_level_priority",
    "verdict_is_more_severe",
    "most_severe_verdict",
    "neutral_safety_verdict",
    "review_verdict",
    "session_safety_verdict",
    "safety_text",
]


def most_severe_verdict(*verdicts: SafetyVerdict | None) -> SafetyVerdict:
    """取最严重的一份结论；调用方保证至少给出一份。

    等级序与 ``backend.safety.projection`` 共用同一份口径，此处不重复定义。
    """
    if not any(verdict is not None for verdict in verdicts):
        raise ValueError("至少需要一份安全结论")
    return _most_severe_verdict(*verdicts)  # type: ignore[return-value]


def neutral_safety_verdict() -> SafetyVerdict:
    """会话尚无安全结论时的中性默认值（NORMAL + CONTINUE）。

    它**不是**风险判定结果，只是 Healing 状态的初值：是否继续普通治愈
    只看 ``safety_blocks_normal_flow`` 与会话上的安全状态，不看这个对象。
    """
    return SafetyVerdict(
        risk_detected=derive_risk_detected(SafetyLevel.NORMAL),
        risk_level=SafetyLevel.NORMAL,
        route=derive_route(SafetyLevel.NORMAL),
        model_status=ModelStatus.ok,
    )


def review_verdict(rationale: str = "") -> SafetyVerdict:
    """支持阶段模型显式标记安全信号时的**澄清**结论（fail-to-review）。

    它只产出 UNCERTAIN + SAFETY_REVIEW，**永远不会**自行升级为 HIGH/停止：
    高危与安全支持只能来自权威的 Safety 结论，Healing 不自行判定风险。
    """
    return SafetyVerdict(
        risk_detected=True,
        risk_level=SafetyLevel.UNCERTAIN,
        route=SafetyRoute.SAFETY_REVIEW,
        messages=[REVIEW_MODE_CONTINUATION_MESSAGE],
        model_status=ModelStatus.unavailable,
        rationale=rationale or None,
    )


def session_safety_verdict(session: "SessionState") -> SafetyVerdict:
    """只读会话上的安全状态，得到本轮 Healing 生效的安全结论。

    Healing 不自行判定风险：结论要么来自 ``session.latest_safety``
    （新版 Safety Agent 的结论），要么由会话上的安全阶段还原出等价的
    SafetyVerdict（停止锁 / 澄清阶段）。拿不到结论时既不放行成高危，
    也不把自己当成低风险判定——是否继续普通治愈由
    ``safety_blocks_normal_flow`` 决定。
    """
    from backend.models.states import SessionState  # 运行期导入，避免循环引用

    if not isinstance(session, SessionState):  # pragma: no cover - 契约保护
        raise TypeError("session_safety_verdict 只接受 SessionState")
    if session.latest_safety is not None:
        return session.latest_safety
    if session.safety_halted or session.safety_stage == "stopped":
        # 停止锁是单向的：会话一旦进入安全支持模式就永不自动解除。
        # ``model_status=ok`` 是准确的口径：这份停止结论当初由一次**成功**的
        # Safety 判定建立，这里只是从会话状态复原它。标成 failure 会让
        # ``project_to_risk_result`` 往报告的风险原因里写入
        # 「安全判定服务状态：unavailable」，对复核者是误导。
        return SafetyVerdict(
            risk_detected=True,
            risk_level=SafetyLevel.HIGH,
            route=SafetyRoute.SAFETY_STOP,
            messages=[SUPPORT_MODE_CONTINUATION_MESSAGE],
            model_status=ModelStatus.ok,
            rationale="会话已处于安全支持模式；停止锁不自动解除。",
        )
    if session.safety_stage == "review":
        return review_verdict("会话处于安全澄清阶段，普通治愈先暂停。")
    return neutral_safety_verdict()


def safety_text(verdict: SafetyVerdict, *, already_halted: bool = False) -> str:
    """面向用户的安全文案：Safety 的 messages 优先，为空时用 support 兜底。"""
    messages = safety_reply_messages(verdict, already_halted=already_halted)
    return messages[0] if messages else REVIEW_MODE_CONTINUATION_MESSAGE
