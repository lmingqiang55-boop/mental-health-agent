# -*- coding: utf-8 -*-
"""一轮对话的 Agent 运行轨迹（演示用，默认关闭）。

设计边界：

- **只搬运、不生产。** trace 里每个字段都来自本轮**已经算出来**的结果
  （Safety 结论、图内调度状态、视觉反馈、气泡条数），不新增任何模型调用，
  也不参与任何业务判定——关掉它，系统的行为逐字节不变。
- **默认关闭。** ``AGENT_TRACE`` 未开启时 ``/api/chat`` 的 ``trace`` 为 ``null``，
  前端不渲染面板。
- **不外传图内状态。** 只给 5 项演示所需的结论；完整 ``TurnState``、提示词、
  模型推理文本、API Key、视觉原始数值一律不出现在 trace 里。
- **Safety 如实标为图外前置。** Safety 目前在 LangGraph **之外**执行
  （``backend/api/chat.py`` 的第一道闸门），因此 trace 用
  ``placement="pre_graph"`` 显式标注，不把它描述成图内节点。

``state`` 字段是给前端的统一词表，五段共用一套取值，方便一眼区分
"已调用 / 跳过 / 安全分支提前结束 / 该引擎不提供"：

- ``ran``           本轮真的执行了；
- ``skipped``       本轮有意跳过（如复用已有效策略，未调用决策模型）；
- ``short_circuit`` 安全分支提前结束，本轮没有走到这里；
- ``unavailable``   当前对话引擎不提供该信息（legacy 顺序执行没有图内调度）。
"""

from __future__ import annotations

import os

from backend.core.visual_acknowledgment import (
    TONE_LABELS, VISUAL_LABELS, mentions_appearance,
)
from backend.models.responses import (
    AgentTrace, DialogueResponsePayload, TraceDecision, TraceDialogue,
    TraceOutput, TraceSafety, TraceVision, TurnScheduling,
)
from backend.safety.schemas import SafetyRoute, SafetyVerdict

__all__ = [
    "CHANNEL_LABELS",
    "FORCED_REASON_LABELS",
    "ROUTE_REASON_LABELS",
    "TRACE_ENV",
    "build_agent_trace",
    "summarize_scheduling",
    "trace_enabled",
]

#: 演示开关。默认关闭；取值 1/true/on/yes（大小写不敏感）时开启。
TRACE_ENV = "AGENT_TRACE"
_TRUTHY = frozenset({"1", "true", "on", "yes"})

#: Dialogue 自主路由的原因码 → 说给评委听的说法。
#: 取值口径见 ``backend/prompts/dialogue_prompt`` 的路由提示词。
ROUTE_REASON_LABELS: dict[str, str] = {
    "continue_topic": "当前话题还值得追问",
    "clarify": "先澄清刚说的内容",
    "topic_exhausted": "当前话题问得差不多了",
    "user_wants_change": "学生想换话题",
    "off_topic": "说的与当前话题无关",
}

#: 后端强制重新决策的原因码 → 说法。取值见 ``backend.core.screening_flow``。
FORCED_REASON_LABELS: dict[str, str] = {
    "no_active_decision": "还没有有效策略",
    "active_decision_invalid": "已存策略失效",
    "no_active_topic": "还没有当前话题",
    "active_topic_invalid": "当前话题失效",
    "topic_budget_exhausted": "当前话题已问满两轮",
    "sensitive_topic": "敏感话题不做自主追问",
    "coverage_lag": "优先补齐还没聊过的话题",
}

#: 视觉关怀的三条通道 → 说法。与 ``select_visual_channels`` 的三选一对应。
CHANNEL_LABELS: dict[str, str] = {
    "emotion": "表情名字",
    "discordance": "温和核对",
    "tone": "整体语气",
}

#: 这些 ``visual_feedback.reason`` 说明本轮**确实选出了**一条外观线索
#: （用在拿不到图内调度事实时的兜底判断上）。
_CUE_REASONS = frozenset({"mentioned", "generation_omitted", "tone", "discordance"})

_SAFETY_OUTCOMES = {
    SafetyRoute.CONTINUE.value: "continue",
    SafetyRoute.SAFETY_REVIEW.value: "review",
    SafetyRoute.SAFETY_STOP.value: "stop",
}


def trace_enabled() -> bool:
    """是否开启演示轨迹；每次调用都重新读环境变量，便于测试与现场切换。"""
    return (os.getenv(TRACE_ENV) or "").strip().lower() in _TRUTHY


def _cue_label(channel: str | None, cue: str | None) -> str | None:
    """把线索名翻成给学生看过的说法；复用语视觉模块里那两份唯一的标签表。"""
    if channel == "emotion" and cue:
        return VISUAL_LABELS.get(cue)  # type: ignore[arg-type]
    if channel == "tone" and cue:
        return TONE_LABELS.get(cue)  # type: ignore[arg-type]
    if channel == "discordance":
        return "表情与表达对不上"
    return None


def summarize_scheduling(
    *, engine: str, routed: bool, need_decision: bool,
    route_reason_code: str = "", forced_reason: str | None = None,
    channels: object | None = None,
) -> TurnScheduling:
    """从图内最终状态里摘出演示所需的最小调度事实。

    参数都是**已经算好的值**（由 :mod:`backend.graph.engine` 从最终状态取出），
    本函数不做判断、不读会话、不调模型。
    """
    channel: str | None = None
    cue: str | None = None
    if channels is not None:
        acknowledgment = getattr(channels, "acknowledgment", None)
        if acknowledgment is not None:
            channel, cue = "emotion", acknowledgment
        elif getattr(channels, "discordance", None) is not None:
            channel = "discordance"
        elif getattr(channels, "tone", None) is not None:
            channel, cue = "tone", channels.tone  # type: ignore[attr-defined]
    return TurnScheduling(
        engine=engine, routed=routed, need_decision=need_decision,
        route_reason_code=route_reason_code, forced_reason=forced_reason,
        visual_channel=channel, visual_cue=cue,
    )


def _vision_from_scheduling(
    payload: DialogueResponsePayload, scheduling: TurnScheduling,
) -> TraceVision:
    channel = scheduling.visual_channel
    cue_valid = channel is not None
    return TraceVision(
        state="ran",
        cue_valid=cue_valid,
        channel=channel,
        channel_label=CHANNEL_LABELS.get(channel) if channel else None,
        cue=_cue_label(channel, scheduling.visual_cue),
        # "真的说出口"用的是与冷却记账**同一个**判据，不是另写一套。
        spoken=cue_valid and mentions_appearance(payload.reply),
        reason=payload.visual_feedback.reason,
    )


def _vision_without_scheduling(payload: DialogueResponsePayload) -> TraceVision:
    """legacy 引擎：拿不到图内选中的通道，只能按视觉反馈兜底判断。"""
    reason = payload.visual_feedback.reason
    cue_valid = reason in _CUE_REASONS
    return TraceVision(
        state="ran",
        cue_valid=cue_valid,
        channel=None,
        channel_label="外观线索（legacy 引擎不区分通道）" if cue_valid else None,
        cue=VISUAL_LABELS.get(payload.visual_feedback.emotion)  # type: ignore[arg-type]
        if payload.visual_feedback.emotion else None,
        spoken=cue_valid and mentions_appearance(payload.reply),
        reason=reason,
    )


def build_agent_trace(
    *, safety: SafetyVerdict, payload: DialogueResponsePayload | None,
    messages: list[str], engine: str,
) -> AgentTrace:
    """组装本轮交给演示面板的轨迹。**不产生任何副作用。**

    Args:
        safety: 本轮 Safety 结论（图外前置闸门产出）。
        payload: 普通分支的对话载荷；安全分支为 ``None``。
        messages: 本轮最终面向学生的消息（用来数气泡）。
        engine: 当前生效的对话引擎名，仅作展示。
    """
    short_circuit = safety.route is not SafetyRoute.CONTINUE
    scheduling = payload.scheduling if payload is not None else None

    safety_trace = TraceSafety(
        engine=safety.engine,
        risk_level=safety.risk_level.value,
        route=safety.route.value,
        model_status=safety.model_status.value,
        outcome=_SAFETY_OUTCOMES[safety.route.value],
    )

    if short_circuit or payload is None:
        # 安全分支：Dialogue / Decision / 视觉通道本轮都没有执行。
        dialogue = TraceDialogue(state="short_circuit")
        decision = TraceDecision(state="short_circuit", label="安全分支未调用")
        vision = TraceVision(state="short_circuit", cue_valid=False,
                             reason="safety_branch")
    elif scheduling is None:
        dialogue = TraceDialogue(state="unavailable")
        decision = TraceDecision(state="unavailable",
                                 label="该引擎不提供图内调度信息")
        vision = _vision_without_scheduling(payload)
    else:
        forced = scheduling.forced_reason
        dialogue = TraceDialogue(
            state="ran",
            routed=scheduling.routed,
            need_decision=scheduling.need_decision,
            reason_code=scheduling.route_reason_code,
            reason_label=ROUTE_REASON_LABELS.get(scheduling.route_reason_code, ""),
            forced_reason=forced,
            forced_label=FORCED_REASON_LABELS.get(forced) if forced else None,
        )
        called = scheduling.need_decision
        decision = TraceDecision(
            state="ran" if called else "skipped",
            called=called,
            label="本轮已调用决策模型" if called else "复用当前策略",
            strategy=payload.next_strategy,
        )
        vision = _vision_from_scheduling(payload, scheduling)

    return AgentTrace(
        engine=engine, safety=safety_trace, dialogue=dialogue,
        decision=decision, vision=vision,
        output=TraceOutput(bubbles=len(messages)),
    )
