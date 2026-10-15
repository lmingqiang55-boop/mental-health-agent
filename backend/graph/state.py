# -*- coding: utf-8 -*-
"""LangGraph 单轮对话的共享状态定义。

一轮 = 一条用户输入。图状态只在这一轮内存在，**不落库、不序列化**：
``SessionState`` 仍是唯一权威会话状态，本阶段刻意不引入 Checkpointer，
因此不需要考虑历史会话的反序列化与版本迁移。

合并语义：节点返回的字典按 key **覆盖**进状态；没有返回的 key 保持原值。
``session`` 是按引用传递的权威对象，节点就地修改它，不靠状态通道回传。
"""

from __future__ import annotations

from typing import TypedDict

from backend.core.dialogue_manager import VisualChannels
from backend.models.dialogue import DialogueRouteDecision
from backend.models.responses import DialogueResponsePayload, VisualFeedback
from backend.models.states import SessionState, VisionState
from backend.policy.client import PolicyDecision

__all__ = ["GRAPH_RECURSION_LIMIT", "TurnState"]

#: 图的硬性递归上限。
#:
#: Phase 1 的图没有回边，正常远达不到；这是给 Phase 2 的
#: 「Dialogue → Decision → Dialogue」与「Visual Review 重写回边」预留的兜底，
#: 触发时抛 ``GraphRecursionError``，由调用方转成明确错误，绝不挂死。
GRAPH_RECURSION_LIMIT = 25


class TurnState(TypedDict, total=False):
    """单轮对话的共享状态（所有键可选，便于分阶段填充）。"""

    # -- 输入 ------------------------------------------------------------
    session: SessionState
    user_text: str
    vision_snapshot: VisionState | None
    use_latest_states: bool
    utterance_id: str | None

    # -- 中间量 ----------------------------------------------------------
    current_vision: VisionState | None
    #: 收尾原因（``topic_coverage`` / ``turn_limit`` / ``user_requested``）；非空即收尾轮。
    ending: str | None
    #: 后端强制调用决策模型的原因码；非空即**不做**路由判断，直接决策。
    forced_reason: str | None
    #: Dialogue 路由结论；为 None 表示本轮被后端强制，没有问过 Dialogue。
    route: DialogueRouteDecision | None
    #: 本轮是否需要新的全局策略（后端强制 OR Dialogue 建议）。
    need_decision: bool
    #: 本轮生效的原因码：被强制时用 ``forced_reason``，否则用路由的 ``reason_code``。
    route_reason: str
    #: 本轮实际使用的全局决策（新取得的，或复用的上一条有效决策）。
    decision: PolicyDecision | None
    channels: VisualChannels | None
    reply: str | None
    visual_feedback: VisualFeedback | None

    # -- 输出 ------------------------------------------------------------
    payload: DialogueResponsePayload | None
