# -*- coding: utf-8 -*-
"""按 ``DIALOGUE_ENGINE`` 把一轮普通筛查派发给 legacy 或 graph。

- ``legacy``（默认）：直接调用 :meth:`DialogueManager.process_turn`，即迁移前行为。
- ``graph``：交给 :mod:`backend.graph.build` 编译的 LangGraph 图调度。

**同一会话不得中途切换引擎。** 会话第一次跑普通轮时会把当时的引擎记在
``SessionState.dialogue_engine`` 上；之后若环境变量改成另一个引擎，
本模块会明确拒绝该轮（``EngineSessionMismatch``），而不是让两种调度路径
在同一会话里混用、产出口径不一致的历史。需要对比两个引擎时必须新建会话。

安全判定不在这里：``backend/api/chat.py`` 的 Safety 闸门在进入本模块**之前**
已经完成，且每轮恰好一次。
"""

from __future__ import annotations

import os

from backend.core.agent_trace import summarize_scheduling
from backend.core.dialogue_manager import DialogueManager, DialogueUnavailable
from backend.graph.state import GRAPH_RECURSION_LIMIT, TurnState
from backend.models.responses import DialogueResponsePayload
from backend.models.states import SessionState, VisionState

__all__ = [
    "DEFAULT_ENGINE",
    "DIALOGUE_ENGINE_ENV",
    "ENGINE_GRAPH",
    "ENGINE_LEGACY",
    "ENGINES",
    "DialogueEngineConfigError",
    "DialogueTurnRunner",
    "EngineSessionMismatch",
    "dialogue_engine",
]

DIALOGUE_ENGINE_ENV = "DIALOGUE_ENGINE"
ENGINE_LEGACY = "legacy"
ENGINE_GRAPH = "graph"
ENGINES = (ENGINE_LEGACY, ENGINE_GRAPH)
DEFAULT_ENGINE = ENGINE_LEGACY


class DialogueEngineConfigError(RuntimeError):
    """``DIALOGUE_ENGINE`` 取值非法。

    故意**不**静默回退：写错值时若悄悄按 legacy 跑，会让人误以为
    正在验证 graph，比直接报错更危险。
    """


class EngineSessionMismatch(RuntimeError):
    """同一个会话被要求换用另一个对话引擎。"""


def dialogue_engine() -> str:
    """读取当前生效的对话引擎；每次调用都重新读环境变量，便于测试替换。"""
    raw = (os.getenv(DIALOGUE_ENGINE_ENV) or DEFAULT_ENGINE).strip().lower()
    if raw not in ENGINES:
        raise DialogueEngineConfigError(
            f"{DIALOGUE_ENGINE_ENV} 只能是 {' 或 '.join(ENGINES)}，当前为 {raw!r}。")
    return raw


class DialogueTurnRunner:
    """一轮普通筛查的入口，按引擎分派。

    持有与 legacy 路径**同一个** ``DialogueManager`` 实例，因此图节点用的是
    同一套决策/对话客户端，注入替换客户端时两条路径同时生效。

    Args:
        manager: 路由层创建并共享的 ``DialogueManager``。
    """

    def __init__(self, manager: DialogueManager) -> None:
        self._manager = manager
        #: 惰性编译：legacy 模式下完全不导入 langgraph，
        #: 这样即便依赖缺失也仍能按 legacy 跑完演示。
        self._graph = None

    def process_turn(
        self, user_text: str, session: SessionState,
        vision_snapshot: VisionState | None = None,
        *, use_latest_states: bool = True,
        utterance_id: str | None = None,
    ) -> DialogueResponsePayload:
        engine = dialogue_engine()
        pinned = session.dialogue_engine
        if pinned is None:
            session.dialogue_engine = engine
        elif pinned != engine:
            raise EngineSessionMismatch(
                f"会话 {session.session_id} 已绑定对话引擎 {pinned!r}，"
                f"当前 {DIALOGUE_ENGINE_ENV}={engine!r}。"
                "不同引擎不得混用同一会话，请新建会话后重试。")

        if engine == ENGINE_GRAPH:
            return self._run_graph(
                user_text, session, vision_snapshot,
                use_latest_states=use_latest_states, utterance_id=utterance_id)
        return self._manager.process_turn(
            user_text, session, vision_snapshot,
            use_latest_states=use_latest_states, utterance_id=utterance_id)

    # -- graph 路径 ------------------------------------------------------

    def _compiled_graph(self):
        if self._graph is None:
            from backend.graph.build import build_turn_graph
            self._graph = build_turn_graph(self._manager)
        return self._graph

    def _run_graph(
        self, user_text: str, session: SessionState,
        vision_snapshot: VisionState | None,
        *, use_latest_states: bool, utterance_id: str | None,
    ) -> DialogueResponsePayload:
        from langgraph.errors import GraphRecursionError

        state: TurnState = {
            "session": session,
            "user_text": user_text,
            "vision_snapshot": vision_snapshot,
            "use_latest_states": use_latest_states,
            "utterance_id": utterance_id,
        }
        try:
            # 同步 invoke：图内不存在事件循环，既有 asyncio.run 行为不变。
            final = self._compiled_graph().invoke(
                state, config={"recursion_limit": GRAPH_RECURSION_LIMIT})
        except GraphRecursionError as exc:
            raise DialogueUnavailable(
                f"对话图超出递归上限 {GRAPH_RECURSION_LIMIT}，已中止本轮。") from exc

        payload = final.get("payload")
        if payload is None:  # pragma: no cover - 拓扑保证不会发生
            raise DialogueUnavailable("对话图未产生响应载荷。")
        # 演示轨迹：把本轮已经算出来的图内调度事实摘成一小份结论挂在载荷上。
        # 只是搬运，不改判定、不额外调用；没开 trace 时前端也不会看到它。
        payload.scheduling = summarize_scheduling(
            engine=ENGINE_GRAPH,
            routed=False,
            need_decision=final.get("decision") is not None,
            route_reason_code=("per_turn_decision" if final.get("decision") is not None
                               else final.get("ending") or ""),
            channels=final.get("channels"),
        )
        return payload
