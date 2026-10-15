# -*- coding: utf-8 -*-
"""LangGraph 节点：把一轮普通筛查拆成可独立调度与单独测试的步骤。

【Phase 1 过渡说明】
本阶段的节点拆分**不改变任何业务行为**——每个节点都直接调用
:mod:`backend.core.dialogue_manager` 里已有的模块级函数/公开方法，
两组实现共用同一份逻辑，因此不存在"图里又重写一遍"的漂移风险。

当前拓扑（``decision`` 仍是**无条件**执行，即原有的"每轮必调决策"）::

    START -> prepare_turn -> [收尾?] -> dialogue_close -----------------> commit -> END
                                   \\-> decision -> prepare_vision -> dialogue_execute -> commit

Phase 2 会在 ``prepare_vision`` 与 ``decision`` 之间插入 ``dialogue_route``，
把 ``decision`` 改成**按需**执行。因此本文件的节点划分即为 Phase 2 的挂载点，
不是最终的"单节点包装"。
"""

from __future__ import annotations

from backend.core.dialogue_manager import (
    DialogueManager,
    closing_payload,
    completion_reason,
    ensure_screening_open,
    finalize_visual_feedback,
    limit_topic,
    open_payload,
    record_answer,
    resolve_current_vision,
    select_visual_channels,
)
from backend.graph.state import TurnState

__all__ = ["TurnNodes"]

#: 正常轮次的节点顺序（供文档与测试断言使用）。
OPEN_PATH = ("prepare_turn", "decision", "prepare_vision", "dialogue_execute", "commit")
#: 收尾轮次的节点顺序。
CLOSING_PATH = ("prepare_turn", "dialogue_close", "commit")


class TurnNodes:
    """一轮对话的全部节点。

    Args:
        manager: 与 ``legacy`` 路径**同一个** ``DialogueManager`` 实例。
            图不自己造决策/对话客户端，因此 ``tests/conftest.py`` 对
            ``dialogue_manager._policy`` / ``._dialogue_agent`` 的注入依然生效。
    """

    def __init__(self, manager: DialogueManager) -> None:
        self._manager = manager

    # -- 准备 ------------------------------------------------------------

    def prepare_turn(self, state: TurnState) -> dict:
        """视觉新鲜度 -> 阶段守卫 -> 记账上一轮话题 -> 判断是否收尾。

        顺序与 ``process_turn`` 完全一致；四项都必须在决策之前。
        """
        session = state["session"]
        current_vision = resolve_current_vision(
            session, state.get("vision_snapshot"),
            state.get("use_latest_states", True))
        ensure_screening_open(session)
        record_answer(session)
        ending = completion_reason(session, state["user_text"])
        return {"current_vision": current_vision, "ending": ending}

    @staticmethod
    def route_after_prepare(state: TurnState) -> str:
        """本阶段真正的条件路由：收尾轮不再提问，普通轮继续评估。"""
        return "closing" if state.get("ending") is not None else "open"

    # -- 普通轮次 --------------------------------------------------------

    def decision(self, state: TurnState) -> dict:
        """取得本轮评估动作，并交由话题次数约束器裁剪。

        Phase 1 保持原有行为：**每轮都会调用决策模型**。
        """
        session = state["session"]
        return {"decision": limit_topic(session, self._manager.decide(session))}

    def prepare_vision(self, state: TurnState) -> dict:
        """三选一挑出本轮可用的视觉线索（说得出口的表情 / 温和核对 / 整体语气）。

        必须在生成**之前**完成，这样回复才有机会自然带上视觉信息。
        """
        session = state["session"]
        channels = select_visual_channels(
            session, state.get("utterance_id"), state.get("current_vision"),
            state["user_text"])
        return {"channels": channels}

    def dialogue_execute(self, state: TurnState) -> dict:
        """按决策生成回复，并在生成后记录外观是否真的被提及（影响冷却）。"""
        session = state["session"]
        channels = state.get("channels")
        if channels is None:  # pragma: no cover - 拓扑保证不会发生
            raise RuntimeError("dialogue_execute 缺少视觉线索状态")
        reply = self._manager.reply_for_decision(
            session, state["user_text"], state.get("current_vision"),
            state["decision"], channels)
        finalize_visual_feedback(session, channels, reply)
        return {"reply": reply, "visual_feedback": channels.feedback}

    # -- 收尾轮次 --------------------------------------------------------

    def dialogue_close(self, state: TurnState) -> dict:
        """收尾轮：只提示生成结果、不再提问，也不选集视觉线索。"""
        reply = self._manager.closing_reply(
            state["user_text"], state["session"], state.get("current_vision"),
            state["ending"])
        return {"reply": reply}

    # -- 出口 ------------------------------------------------------------

    def commit(self, state: TurnState) -> dict:
        """组装最终响应载荷。

        Phase 1 仅此一处收口；会话状态的写入目前仍跟随各自节点
        （与 ``process_turn`` 的位置一一对应），把写入集中到单一节点
        是 Phase 2 引入重写回边时才需要做的事。
        """
        session = state["session"]
        ending = state.get("ending")
        if ending is not None:
            payload = closing_payload(session, state["reply"], ending)
        else:
            decision = state.get("decision")
            if decision is None:  # pragma: no cover - 拓扑保证不会发生
                raise RuntimeError("commit 缺少决策结果")
            feedback = state.get("visual_feedback")
            if feedback is None:  # pragma: no cover - 拓扑保证不会发生
                raise RuntimeError("commit 缺少视觉反馈")
            payload = open_payload(session, state["reply"],
                                   decision.actions[-1].value, feedback)
        return {"payload": payload}
