# -*- coding: utf-8 -*-
"""正常筛查对话的 LangGraph 调度层。

一轮 = 一条用户输入。图内部状态只在这一轮内存在，不落库、不序列化：
:class:`backend.models.states.SessionState` 仍是唯一权威会话状态
（本阶段刻意不引入 LangGraph Checkpointer）。

普通访谈每轮执行 ``decision``，再由 Dialogue 执行一个评估目标。
模型申请结束时，后端检查11项是否各收到过回答；35轮强制结束。
不再执行旧 ``dialogue_route`` 或复用上一轮决策；安全流程独立优先处理。

【关于导入】本包**不**在导入时加载 ``langgraph``：只有真正调用
:func:`build_turn_graph` 才会导入。这样 ``DIALOGUE_ENGINE=legacy`` 的路径
完全不依赖图库，即便图依赖缺失也能按 legacy 跑完演示。
"""

from backend.graph.engine import (
    DEFAULT_ENGINE,
    DIALOGUE_ENGINE_ENV,
    ENGINE_GRAPH,
    ENGINE_LEGACY,
    DialogueEngineConfigError,
    DialogueTurnRunner,
    EngineSessionMismatch,
    dialogue_engine,
)
from backend.graph.state import GRAPH_RECURSION_LIMIT, TurnState

__all__ = [
    "DEFAULT_ENGINE",
    "DIALOGUE_ENGINE_ENV",
    "ENGINE_GRAPH",
    "ENGINE_LEGACY",
    "GRAPH_RECURSION_LIMIT",
    "DialogueEngineConfigError",
    "DialogueTurnRunner",
    "EngineSessionMismatch",
    "TurnState",
    "build_turn_graph",
    "dialogue_engine",
]


def __getattr__(name: str):
    """惰性暴露 :func:`build_turn_graph`（PEP 562）。

    只有真的要用图时才导入 :mod:`backend.graph.build`，从而把 ``langgraph``
    的导入推迟到 ``DIALOGUE_ENGINE=graph`` 的第一次调用。
    """
    if name == "build_turn_graph":
        from backend.graph.build import build_turn_graph
        return build_turn_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
