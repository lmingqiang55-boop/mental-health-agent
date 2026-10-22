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
from backend.models.dialogue import DialogueAgentResponse
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
    #: 收尾原因（model_finished / turn_limit / user_requested）。
    ending: str | None
    #: 每个普通轮新取得的目标，或模型主动结束的标记。
    decision: PolicyDecision | None
    channels: VisualChannels | None
    #: 本轮生成的完整响应对象；``commit`` 直接用它组装载荷，不再拼一遍。
    response: DialogueAgentResponse | None
    visual_feedback: VisualFeedback | None

    # -- 输出 ------------------------------------------------------------
    payload: DialogueResponsePayload | None
