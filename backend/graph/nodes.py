# -*- coding: utf-8 -*-
"""LangGraph 节点：把一轮普通筛查拆成可独立调度与单独测试的步骤。

每个节点都只调用 :mod:`backend.core.dialogue_manager` /
:mod:`backend.core.screening_flow` 里已有的函数，不在图里重写业务逻辑，
因此 ``legacy`` 与 ``graph`` 两条路径不会各写一份而漂移。

当前拓扑（Phase 2，``decision`` 已改为**按需**执行）::

    START -> prepare_turn -> closing_check -+-(收尾)-> dialogue_close ------------> commit -> END
                                            |
                                            +-(普通)-> dialogue_route -+-(需要)-> decision -+
                                                                       |                     |
                                                                       +-(复用)--------------+
                                                                                 |
                                                                          resolve_topic
                                                                                 |
                                                    visual_prepare -> dialogue_execute -> commit

【职责严格分离】这是本阶段最重要的结构约定，因为节点一旦重复执行，
历史、话题计数与冷却都会被重复更新：

- ``prepare_turn``   ：只做"消费"——视觉新鲜度、阶段守卫、登记上一轮回答的话题。
- ``closing_check``  ：只读地判断本轮是否收尾，不做任何写入。
- ``dialogue_route`` ：只判断"要不要新的全局策略"，不选话题、不写话题。
- ``decision``       ：只调用决策模型，**不做**话题次数约束。
- ``resolve_topic``  ：本轮**唯一**的话题记账点，决定"下一条回答算在哪个话题下"。
- ``visual_prepare`` ：只挑视觉线索，不写会话状态。
- ``dialogue_execute``：生成回复并记录外观是否真的被提及（影响冷却）。
- ``commit``         ：只组装响应载荷。

话题次数约束（``limit_topic``）刻意从 ``decision`` 移到 ``resolve_topic``：
这样"取得新策略"与"决定下一条回答属于哪个话题"各自只有一个负责人，
两条分支（需要决策 / 复用决策）也在同一处收口。
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
from backend.core.screening_flow import (
    adopt_decision, carry_over_topic, should_force_decision,
)
from backend.graph.state import TurnState

__all__ = ["TurnNodes", "CLOSING_PATH", "OPEN_DECIDED_PATH", "OPEN_REUSED_PATH"]

#: 收尾轮次的节点顺序（供文档与测试断言使用）。
CLOSING_PATH = ("prepare_turn", "closing_check", "dialogue_close", "commit")
#: 普通轮次、本轮取了新策略的节点顺序。
OPEN_DECIDED_PATH = ("prepare_turn", "closing_check", "dialogue_route", "decision",
                     "resolve_topic", "visual_prepare", "dialogue_execute", "commit")
#: 普通轮次、本轮复用已有策略（Dialogue 自主追问）的节点顺序。
OPEN_REUSED_PATH = ("prepare_turn", "closing_check", "dialogue_route",
                    "resolve_topic", "visual_prepare", "dialogue_execute", "commit")


class TurnNodes:
    """一轮对话的全部节点。

    Args:
        manager: 与 ``legacy`` 路径**同一个** ``DialogueManager`` 实例。
            图不自己造决策/对话客户端，因此 ``tests/conftest.py`` 对
            ``dialogue_manager._policy`` / ``._dialogue_agent`` 的注入依然生效。
    """

    def __init__(self, manager: DialogueManager) -> None:
        self._manager = manager

    # -- 准备（只消费，不产生新话题）--------------------------------------

    def prepare_turn(self, state: TurnState) -> dict:
        """视觉新鲜度 -> 阶段守卫 -> 登记上一轮回答所属话题。

        顺序与 ``process_turn`` 一致；前两项必须在任何模型调用之前。
        """
        session = state["session"]
        current_vision = resolve_current_vision(
            session, state.get("vision_snapshot"),
            state.get("use_latest_states", True))
        ensure_screening_open(session)
        record_answer(session)
        return {"current_vision": current_vision}

    def closing_check(self, state: TurnState) -> dict:
        """只读地判断本轮是否收尾；不做任何会话写入。"""
        return {"ending": completion_reason(state["session"], state["user_text"])}

    @staticmethod
    def route_after_closing(state: TurnState) -> str:
        """收尾轮不再提问，普通轮进入路由判断。"""
        return "closing" if state.get("ending") is not None else "open"

    # -- 路由（只判断，不选话题）------------------------------------------

    def dialogue_route(self, state: TurnState) -> dict:
        """判断本轮是否需要**新的**全局策略。

        后端强制条件优先，并且**短路掉路由模型调用**——既然结论已经确定，
        就没有必要再花一次模型调用去问 Dialogue。Dialogue 只在真正有余地
        判断时才被问到。
        """
        session = state["session"]
        forced = should_force_decision(session)
        if forced is not None:
            return {"forced_reason": forced, "need_decision": True,
                    "route": None, "route_reason": forced}
        decision = self._manager.route_turn(
            session, state["user_text"], state.get("current_vision"))
        return {"forced_reason": None, "need_decision": decision.need_decision,
                "route": decision, "route_reason": decision.reason_code}

    @staticmethod
    def route_after_dialogue(state: TurnState) -> str:
        """需要新策略就调决策模型，否则复用已有效的那一条。"""
        return "need_decision" if state.get("need_decision") else "reuse_decision"

    # -- 决策（只调模型，不做话题约束）------------------------------------

    def decision(self, state: TurnState) -> dict:
        """调用决策模型取得新的全局动作；每轮最多一次。

        话题次数约束不在这里做——见 :meth:`resolve_topic`。
        """
        return {"decision": self._manager.decide(state["session"])}

    # -- 话题记账（本轮唯一写作者）----------------------------------------

    def resolve_topic(self, state: TurnState) -> dict:
        """决定"下一条用户回答算在哪个话题下"，并确定本轮要执行的动作。

        - 本轮取了新策略：先用话题次数约束器裁剪，再登记 ``active_*``；
        - 本轮复用策略：沿用当前全局话题（Dialogue 无权更换全局话题）。

        两条分支都会设置 ``pending_topic``，因此**下一条回答一定会被计数**，
        与"本轮是否调用过决策模型"无关。
        """
        session = state["session"]
        decision = state.get("decision")
        if decision is None:
            carry_over_topic(session)
            decision = self._manager.reuse_decision(session)
        else:
            constrained = limit_topic(session, decision)
            adopt_decision(session, constrained,
                           session.screening_progress.pending_topic)
            decision = constrained
        return {"decision": decision}

    # -- 普通轮次的生成 --------------------------------------------------

    def visual_prepare(self, state: TurnState) -> dict:
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
        """组装最终响应载荷；**不**做任何会话状态写入。"""
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
