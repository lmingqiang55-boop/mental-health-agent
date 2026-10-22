"""编译访谈图：安全检查在图外；每个普通轮取得新目标，模型可主动结束。"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.core.dialogue_manager import DialogueManager
from backend.graph.nodes import TurnNodes
from backend.graph.state import TurnState


def build_turn_graph(manager: DialogueManager) -> Any:
    nodes = TurnNodes(manager)
    graph = StateGraph(TurnState)
    for name in ("prepare_turn", "closing_check", "decision", "resolve_target",
                 "visual_prepare", "dialogue_execute", "dialogue_close", "commit"):
        graph.add_node(name, getattr(nodes, name))
    graph.add_edge(START, "prepare_turn")
    graph.add_edge("prepare_turn", "closing_check")
    graph.add_conditional_edges(
        "closing_check", nodes.route_after_closing,
        {"closing": "dialogue_close", "open": "decision"})
    graph.add_conditional_edges(
        "decision", nodes.route_after_closing,
        {"closing": "dialogue_close", "open": "resolve_target"})
    graph.add_edge("resolve_target", "visual_prepare")
    graph.add_edge("visual_prepare", "dialogue_execute")
    graph.add_edge("dialogue_execute", "commit")
    graph.add_edge("dialogue_close", "commit")
    graph.add_edge("commit", END)
    return graph.compile()
