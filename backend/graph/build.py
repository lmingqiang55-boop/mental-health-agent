# -*- coding: utf-8 -*-
"""编译单轮筛查对话图。

拓扑（Phase 1）::

    START ─▶ prepare_turn ─┬─(ending)─▶ dialogue_close ──────────────────────▶ commit ─▶ END
                           │
                           └─(open)──▶ decision ─▶ prepare_vision ─▶ dialogue_execute ─▶ commit

``decision`` 目前是**无条件**执行，与迁移前的"每轮必调决策"一致；
Phase 2 会在 ``prepare_vision`` 与 ``decision`` 之间插入 ``dialogue_route``，
把它改成按需调用。
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

    为什么用同步 ``invoke``：``DialogueManager._generate_reply`` 内部沿用
    ``asyncio.run(...)``（与迁移前一致）。若改成``asyncio.run(graph.ainvoke(...))``，
    节点里再调 ``asyncio.run`` 就会抛
    ``asyncio.run() cannot be called from a running event loop``。
    ``graph.invoke()`` 全程同步、图内不存在事件循环，因此既有业务代码
    的执行模型与迁移前完全相同，也不需要新增任何 ``asyncio.run``。
    """
    nodes = TurnNodes(manager)
    graph = StateGraph(TurnState)
    graph.add_node("prepare_turn", nodes.prepare_turn)
    graph.add_node("decision", nodes.decision)
    graph.add_node("prepare_vision", nodes.prepare_vision)
    graph.add_node("dialogue_execute", nodes.dialogue_execute)
    graph.add_node("dialogue_close", nodes.dialogue_close)
    graph.add_node("commit", nodes.commit)

    graph.add_edge(START, "prepare_turn")
    graph.add_conditional_edges(
        "prepare_turn", nodes.route_after_prepare,
        {"closing": "dialogue_close", "open": "decision"})
    graph.add_edge("decision", "prepare_vision")
    graph.add_edge("prepare_vision", "dialogue_execute")
    graph.add_edge("dialogue_execute", "commit")
    graph.add_edge("dialogue_close", "commit")
    graph.add_edge("commit", END)
    return graph.compile()
