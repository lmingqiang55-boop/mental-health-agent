# -*- coding: utf-8 -*-
"""正常筛查对话的 LangGraph 调度层。

一轮 = 一条用户输入。图内部状态只在这一轮内存在，不落库、不序列化：
:class:`backend.models.states.SessionState` 仍是唯一权威会话状态
（本阶段刻意不引入 LangGraph Checkpointer）。

本阶段（Phase 2）Dialogue 已成为正常对话的主控：由 ``dialogue_route`` 判断
这一轮是否需要**新的**全局策略，``decision`` 只在需要时执行。后端强制条件
（尚无有效策略、话题已到次数上限、话题失效、高风险话题）优先，并且短路掉
路由模型调用。话题次数、收尾规则与视觉机制均沿用既有实现。

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
