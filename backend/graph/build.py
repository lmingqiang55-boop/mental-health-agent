# -*- coding: utf-8 -*-
"""编译单轮筛查对话图。

拓扑（Phase 2）::

    START ─▶ prepare_turn ─▶ closing_check ─┬─(收尾)─▶ dialogue_close ───────────────────▶ commit ─▶ END
                                            │
                                            └─(普通)─▶ dialogue_route ─┬─(需要新策略)─▶ decision ─┐
                                                                       │                        │
                                                                       └─(复用已有效策略)───────┤
                                                                                                ▼
                                                                          resolve_topic ─▶ visual_prepare
                                                                                ─▶ dialogue_execute ─▶ commit

与 Phase 1 的差别只有一处：``decision`` 由**无条件**执行改为**按需**执行
（入口是 ``dialogue_route`` 的条件边）。收尾分支、视觉准备顺序、响应载荷
组装全部保持不变。

两条分支在 ``resolve_topic`` 收口，因此"下一条回答算在哪个话题下"只有一个
负责人；图**没有回边**，节点不会被重复执行，话题计数与冷却不会被重复更新。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.core.dialogue_manager import DialogueManager
from backend.graph.nodes import TurnNodes
from backend.graph.state import TurnState

__all__ = ["build_turn_graph"]


def build_turn_graph(manager: DialogueManager) -> Any:
    """编译一轮对话的图。

    Args:
        manager: 与 ``legacy`` 路径共用的 ``DialogueManager`` 实例。

    Returns:
        已编译的图；用 ``graph.invoke(state)`` **同步**调用。

    为什么用同步 ``invoke``：``DialogueManager._generate_reply`` / ``route_turn``
    内部沿用 ``asyncio.run(...)``（与迁移前一致）。若改成
    ``asyncio.run(graph.ainvoke(...))``，节点里再调 ``asyncio.run`` 就会抛
    ``asyncio.run() cannot be called from a running event loop``。
    ``graph.invoke()`` 全程同步、图内不存在事件循环，因此既有业务代码
    的执行模型与迁移前完全相同，也不需要新增任何 ``asyncio.run``。
    """
    nodes = TurnNodes(manager)
    graph = StateGraph(TurnState)
    graph.add_node("prepare_turn", nodes.prepare_turn)
    graph.add_node("closing_check", nodes.closing_check)
    graph.add_node("dialogue_route", nodes.dialogue_route)
    graph.add_node("decision", nodes.decision)
    graph.add_node("resolve_topic", nodes.resolve_topic)
    graph.add_node("visual_prepare", nodes.visual_prepare)
    graph.add_node("dialogue_execute", nodes.dialogue_execute)
    graph.add_node("dialogue_close", nodes.dialogue_close)
    graph.add_node("commit", nodes.commit)

    graph.add_edge(START, "prepare_turn")
    graph.add_edge("prepare_turn", "closing_check")
    graph.add_conditional_edges(
        "closing_check", nodes.route_after_closing,
        {"closing": "dialogue_close", "open": "dialogue_route"})
    graph.add_conditional_edges(
        "dialogue_route", nodes.route_after_dialogue,
        {"need_decision": "decision", "reuse_decision": "resolve_topic"})
    graph.add_edge("decision", "resolve_topic")
    graph.add_edge("resolve_topic", "visual_prepare")
    graph.add_edge("visual_prepare", "dialogue_execute")
    graph.add_edge("dialogue_execute", "commit")
    graph.add_edge("dialogue_close", "commit")
    graph.add_edge("commit", END)
    return graph.compile()
