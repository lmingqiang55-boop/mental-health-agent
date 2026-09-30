# -*- coding: utf-8 -*-
"""Dialogue Agent（对话生成 Agent）的输入输出数据结构定义。

本模块只负责定义数据结构（schema），不包含任何 LLM 调用、API、决策逻辑
或用户记忆的提取/写入/检索逻辑。

Dialogue Agent 的职责：根据上游（决策 Agent + 话题次数约束器）给出的决策，
生成"下一句对用户说的话"。它不决定话题，也不允许重新做决策，
因此 DialogueDecision 是它的**输入**而非输出。

依赖：pydantic>=2
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

__all__ = [
    "DialogueVisual",
    "DialogueHistoryMessage",
    "DialogueUserMemory",
    "DialogueDecision",
    "DialogueCurrentUserInput",
    "DialogueAgentRequest",
    "DialogueAgentResponse",
]


class DialogueVisual(BaseModel):
    """视觉标签：记录用户说话时（或当前这一句时）的情绪/参与度视觉特征。

    所有字段均为可选，且保留 extra 用于未来新增视觉特征，
    因此在视觉模块尚未接入时可以直接省略或传 {}。
    """

    valence: Optional[float] = Field(
        default=None, description="效价，通常取值 [-1, 1]，越大越积极"
    )
    arousal: Optional[float] = Field(
        default=None, description="唤醒度，通常取值 [0, 1]，越大越激动"
    )
    engagement: Optional[float] = Field(
        default=None, description="参与度/投入度，通常取值 [0, 1]"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        description="扩展位：未来新增的视觉特征统一放这里，保证向后兼容",
    )


class DialogueHistoryMessage(BaseModel):
    """一条历史对话消息。

    role 为 "user" 或 "assistant"；user 消息允许绑定 visual，
    assistant 消息的 visual 通常为 None。
    """

    role: Literal["user", "assistant"] = Field(..., description="消息角色")
    content: str = Field(..., description="该条消息的文本内容")
    visual: Optional[DialogueVisual] = Field(
        default=None, description="user 消息可绑定的视觉标签；assistant 消息一般为 None"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="扩展位，用于消息级别的未来字段"
    )


class DialogueUserMemory(BaseModel):
    """用户记忆接口（占位）。

    用户记忆模块尚未开发，本类只定义接口，不实现任何提取/写入/检索逻辑。
    所有字段都有默认值，因此 user_memory 可以直接传 {} 或整体省略。
    """

    facts: List[str] = Field(default_factory=list, description="用户客观事实类记忆")
    preferences: List[str] = Field(default_factory=list, description="用户偏好类记忆")
    important_events: List[str] = Field(
        default_factory=list, description="用户重要事件类记忆"
    )
    previous_assessment_summary: Optional[str] = Field(
        default=None, description="上一轮评估结果的文字摘要，可为空"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="扩展位：未来新增记忆类型统一放这里"
    )


class DialogueDecision(BaseModel):
    """决策 Agent + 话题次数约束器输出的最终决策。

    这是 Dialogue Agent 必须服从的输入：它只能按 actions/topic 生成话术，
    不允许自己重新决定话题。
    """

    actions: List[str] = Field(
        ...,
        min_length=1,
        description='要执行的动作列表，至少 1 项，例如 ["共情安慰", "当前话题从睡眠转到食欲"]',
    )
    topic: Optional[str] = Field(
        default=None, description="决策确定的当前话题；None 表示不指定话题"
    )
    reason: Optional[str] = Field(
        default=None, description="决策理由，例如“睡眠话题已达到次数限制”"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="扩展位：未来新增决策字段统一放这里"
    )


class DialogueCurrentUserInput(BaseModel):
    """用户当前最新的一句话（含可选的视觉标签）。"""

    text: str = Field(..., description="用户当前输入的文本内容")
    visual: Optional[DialogueVisual] = Field(
        default=None, description="用户当前这句话的视觉标签，可为空"
    )


class DialogueAgentRequest(BaseModel):
    """Dialogue Agent 的完整输入。

    严格必填：conversation_history、decision、current_user_input。
    其中 conversation_history 即使首次对话也由调用方显式传 []；
    decision 是“决策 Agent + 话题次数约束器”的最终决策，缺少则 Dialogue Agent
    不允许工作。唯一可缺省的是 user_memory（记忆模块尚未实现，允许不传或传 {}）。
    """

    conversation_history: List[DialogueHistoryMessage] = Field(
        ..., description="用户与系统的完整历史对话，首次对话显式传 []"
    )
    user_memory: DialogueUserMemory = Field(
        default_factory=DialogueUserMemory,
        description="用户记忆（可选；记忆模块未实现时可省略，或传 {}）",
    )
    decision: DialogueDecision = Field(
        ...,
        description="决策 Agent + 话题次数约束器给出的最终决策，必填；Dialogue Agent 必须服从",
    )
    current_user_input: DialogueCurrentUserInput = Field(
        ..., description="用户当前最新的一句话"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="扩展位：请求级别未来字段"
    )


class DialogueAgentResponse(BaseModel):
    """Dialogue Agent 的输出：只需要一句真正对用户说的话。"""

    reply: str = Field(..., description="下一句真正对用户说的话")
