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

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "MAX_REPLY_MESSAGES",
    "DialogueVisual",
    "DialogueHistoryMessage",
    "DialogueUserMemory",
    "DialogueDecision",
    "DialogueCurrentUserInput",
    "DialogueAgentRequest",
    "DialogueAgentResponse",
    "DialogueRouteDecision",
    "DialogueRouteRequest",
]

#: 一轮回复最多拆成几条独立消息（聊天气泡）。
#:
#: 上限刻意很小：气泡的作用是让对话节奏像真实聊天，不是把一段话切碎。
#: 模型可以自主选择 1~3 条，但超过就合并——**不丢正文**。
MAX_REPLY_MESSAGES = 3


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


class DialogueVisualDiscordance(BaseModel):
    """本轮"说出来的情绪"与"脸上的效价"方向相反。

    只在后端判定为矛盾时给出；两项极性放在一起是为了让对话 Agent 知道
    *哪一边是哪一边*，从而能组织出"你刚说还好，不过看你好像有点累"这类
    核对句，而不是把两个数字念出来。
    """

    text_polarity: float = Field(
        ..., description="这一句文字自述的极性，[-1, 1]，正为积极、负为消极"
    )
    vision_valence: float = Field(
        ..., description="这一句对应的人脸效价，[-1, 1]，正为积极、负为消极"
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
    visual_observation: Optional[Literal["happy", "sad", "fearful", "angry"]] = Field(
        default=None, description="本轮允许自然提及的一项可靠视觉线索；为空则不主动提及外观"
    )
    visual_discordance: Optional[DialogueVisualDiscordance] = Field(
        default=None,
        description=(
            "本轮文字自述与面部表现方向相反时给出；有值时按温和核对的表达要求回应，"
            "允许提及用户看起来的状态，但只核对一次、不下结论"
        ),
    )
    visual_tone: Optional[Literal["low", "bright"]] = Field(
        default=None,
        description=(
            "本轮允许只凭连续效价提及的整体感受（low=偏低落，bright=偏轻松）；"
            "模型给不出说得出口的情绪名字时才用它，有值时同样只顺口提一句"
        ),
    )
    finish_screening: bool = Field(default=False, description="本轮仅收尾，不能继续提出问题")
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="扩展位：请求级别未来字段"
    )


class DialogueAgentResponse(BaseModel):
    """Dialogue Agent 的输出：本轮要对用户说的话，拆成 1~3 条独立消息。

    【哪个字段是权威】``messages`` 是权威字段，**由模型自己决定分段**（见
    ``DIALOGUE_AGENT_SYSTEM_PROMPT`` 的【输出格式】）。``reply`` 是它的向后兼容
    投影：用换行把 ``messages`` 拼回一段完整文本。

    这样安排有两个好处：

    1. 既有的调用方、离线桩、质量检查与历史记录都继续按"一段文本"工作，
       不需要为了多条消息改一遍；
    2. 前端只按 ``messages`` 渲染气泡，**不再单独渲染 ``reply``**，
       因此不会出现同一句话显示两遍。

    校验器强制两条不变量：``messages`` 至少一条非空、且
    ``reply == "\\n".join(messages)``。因此不存在"reply 与 messages 各说各话"。
    """

    reply: str = Field(
        default="", description="本轮回复全文（等价于 messages 用换行拼接）"
    )
    messages: List[str] = Field(
        default_factory=list,
        description=f"1~{MAX_REPLY_MESSAGES} 条独立消息，按顺序显示为聊天气泡",
    )

    @model_validator(mode="after")
    def _normalize_messages(self) -> "DialogueAgentResponse":
        items = [item.strip() for item in self.messages if item and item.strip()]
        if not items:
            # 只给了 reply（例如离线桩、旧调用方）：退化成单条消息。
            items = [self.reply.strip()]
        if not items[0]:
            raise ValueError("reply 与 messages 不能同时为空")
        if len(items) > MAX_REPLY_MESSAGES:
            # 超上限时合并而不是截断：正文一个字都不能少。
            items = items[:MAX_REPLY_MESSAGES - 1] + [
                "\n".join(items[MAX_REPLY_MESSAGES - 1:])]
        self.messages = items
        self.reply = "\n".join(items)
        return self


class DialogueRouteDecision(BaseModel):
    """Dialogue Agent 对「这一轮要不要重新决策」的判断。

    这是 Dialogue 主控权的**唯一**体现：它只能说"需要/不需要新的全局策略"。
    它**不能**表达要换成哪个话题——选话题是 Decision Agent 与
    话题次数约束器的职责。因此本结构里刻意没有 topic 字段。
    """

    need_decision: bool = Field(
        ..., description="是否需要重新调用决策模型，取得新的全局评估策略"
    )
    reason_code: str = Field(
        default="", description="简短原因码，供调试与统计；不向用户展示"
    )
    reason: str = Field(
        default="", description="一句话理由，仅供调试，不向用户展示"
    )


class DialogueRouteRequest(BaseModel):
    """Dialogue 路由判断的完整输入。

    只提供判断"是否该换全局策略"所需的信息：当前策略、当前话题及其已用轮数、
    整体进度。刻意不提供话题候选列表——Dialogue 不该替决策模型挑话题。
    """

    conversation_history: List[DialogueHistoryMessage] = Field(
        default_factory=list, description="当前这一轮之前的完整历史（不含本轮输入）"
    )
    current_user_input: DialogueCurrentUserInput = Field(
        ..., description="用户当前最新的一句话"
    )
    active_actions: List[str] = Field(
        default_factory=list, description="当前生效的全局动作；为空表示还没有有效策略"
    )
    active_topic: Optional[str] = Field(
        default=None, description="当前正在推进的全局评估话题；None 表示还没确定"
    )
    active_topic_turns: int = Field(
        default=0, description="当前话题已经完成计数的轮数"
    )
    topic_turns: Dict[str, int] = Field(
        default_factory=dict, description="各话题已完成的轮数"
    )
    topic_limit: int = Field(..., description="单个话题的轮数上限")
    turn_count: int = Field(default=0, description="本次筛查已完成的用户轮数")
    min_turns: int = Field(..., description="可以收尾的最少轮数")
    max_turns: int = Field(..., description="强制收尾的轮数上限")
