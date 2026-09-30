# -*- coding: utf-8 -*-
"""Dialogue Agent 的 Prompt 定义与 Prompt Builder。

本模块**只负责文本组装**：
- 不调用任何 LLM；
- 不发起任何网络/API 请求；
- 不包含任何业务决策逻辑（话题选择、action 选择一律由上游 decision 决定）。

【关键约定：current_user_input 与 conversation_history 的关系】
    conversation_history 表示**当前这一轮之前**的完整历史对话，
    current_user_input 表示**这一轮最新**的用户输入，两者互不重叠。
    即：调用方不应把 current_user_input 预先追加进 conversation_history。
    本模块据此分区渲染，不会把同一条用户消息重复输出两遍。

模块内容：
    DIALOGUE_AGENT_SYSTEM_PROMPT   -- System Prompt 常量
    build_dialogue_user_prompt     -- 把 DialogueAgentRequest 渲染成 User Prompt 的纯函数
"""

from __future__ import annotations

import json
from typing import List, Optional

from backend.models.dialogue import (
    DialogueAgentRequest,
    DialogueCurrentUserInput,
    DialogueDecision,
    DialogueHistoryMessage,
    DialogueUserMemory,
    DialogueVisual,
)

__all__ = [
    "DIALOGUE_AGENT_SYSTEM_PROMPT",
    "build_dialogue_user_prompt",
]


DIALOGUE_AGENT_SYSTEM_PROMPT = """你是心理状态评估系统中的 Dialogue Agent（对话生成 Agent）。

【职责】
你的职责只有一个：根据历史对话、用户每句话的视觉状态、用户记忆，以及上游给出的最终 decision，
生成下一句自然、连贯、可以直接对用户说的话。
你不是 Decision Agent。话题选择与 action 选择一律由上游决定。

【最高优先级约束：严格执行 decision】
1. 必须严格执行上游给出的最终 decision。
2. 不允许自行修改 decision，也不允许自己决定：下一步聊什么话题、是否切换话题、是否继续当前话题。
3. action 与 topic 是命令，不是建议。即使你认为别的方向更合适，也必须按 decision 执行。
4. decision.reason 只用于帮助你理解意图，不得原样或改写给用户看到。

【各输入字段的用途】
5. conversation_history：当前这一轮之前的完整历史。用来理解上下文、保持连续性、
   自然承接用户上一句话，并避免重复已经问过的问题。
6. user_memory：用来在合适时自然引用用户以前提到的信息，提升个性化与连续性。
   但必须遵守：
   - user_memory 为空时照常生成回复，不要因此改变行为；
   - 不得编造记忆中不存在的信息；
   - 不需要每一轮都强行使用记忆，只在自然的时候引用。
7. visual（视觉标签）：仅用于辅助理解用户当前表达状态，可以影响语气、共情程度、
   措辞的柔和程度、以及问句的表达方式。但必须遵守：
   - 不得把视觉标签作为医学诊断依据；
   - 不得把视觉标签直接说给用户听；
   - 不得出现“我检测到你的 valence 是 -0.5”这类表达。

【执行 decision 的方式】
8. 如果 decision 包含“共情安慰”这类动作：回复中应先做简短自然的回应或共情，
   然后再执行其他 action。
9. 如果 decision 要求切换话题：必须先自然承接上一句话，再平滑进入新话题，不允许生硬换题。
   反例（不要这样）：“你的食欲怎么样？”
   正例：“听起来最近睡眠确实让你有些困扰。除了睡眠之外，我也想了解一下最近吃饭的情况，食欲有没有什么变化？”
10. 如果 decision 要求继续当前话题：根据 conversation_history 判断已经问过什么，
    不要重复同一个问题，应围绕当前 topic 进行新的、合理的追问。
11. 默认每一轮只提出一个主要问题，避免一次连续问三四个问题。

【表达风格】
12. 回复应当：自然、简洁、口语化、像真实对话；不要像问卷，不要像心理医生照着量表逐条念。
13. 不得暴露任何内部系统信息，包括：action、decision、topic、visual、memory、
    “决策 Agent”、“上游”、“评估维度”等字样。
14. 不要输出解释、分析或推理过程。
15. 最终只生成真正要对用户说的下一句话。
16. 不做医学诊断，不说“你就是抑郁症”“你已经患有重度抑郁”这类结论性判断。
17. 当用户表达明显痛苦时，语言应更加温和，不要机械跳题；但依然必须服从最终 decision。
"""


# --------------------------------------------------------------------------
# 内部渲染工具（纯格式化，不含任何业务判断）
# --------------------------------------------------------------------------


def _dump_json(value: object) -> str:
    """把对象序列化为中文可读的 JSON 字符串（ensure_ascii=False）。"""
    return json.dumps(value, ensure_ascii=False)


def format_visual(visual: Optional[DialogueVisual]) -> Optional[str]:
    """把视觉标签渲染成单行文本。

    - visual 为 None 或没有任何有效信息时返回 None（调用方据此跳过，不伪造）；
    - 只输出有值的字段；
    - extra 中的扩展特征也一并输出，避免丢失上游信息。
    """
    if visual is None:
        return None

    parts: List[str] = []
    if visual.valence is not None:
        parts.append(f"valence={visual.valence}")
    if visual.arousal is not None:
        parts.append(f"arousal={visual.arousal}")
    if visual.engagement is not None:
        parts.append(f"engagement={visual.engagement}")

    extras = {k: v for k, v in visual.extra.items()}
    if extras:
        parts.append(f"extra={_dump_json(extras)}")

    if not parts:
        return None
    return "，".join(parts)


def _format_history(history: List[DialogueHistoryMessage]) -> str:
    """渲染【历史对话】分区。

    每条消息一行；user 消息若带 visual 则在同一行追加视觉标签；
    assistant 消息没有 visual 时不输出任何视觉占位，避免伪造数据。
    """
    if not history:
        return "（历史对话为空，这是本次对话的第一轮）"

    lines: List[str] = []
    for index, message in enumerate(history, start=1):
        speaker = "用户" if message.role == "user" else "助手"
        line = f"{index}. {speaker}：{message.content}"
        visual_text = format_visual(message.visual)
        if visual_text is not None:
            line += f"（当时的视觉标签：{visual_text}）"
        lines.append(line)
    return "\n".join(lines)


def _format_memory(memory: DialogueUserMemory) -> str:
    """渲染【用户记忆】分区；记忆为空时明确写出“暂无可用用户记忆”。"""
    lines: List[str] = []

    if memory.facts:
        lines.append("- 已知事实：" + "；".join(memory.facts))
    if memory.preferences:
        lines.append("- 用户偏好：" + "；".join(memory.preferences))
    if memory.important_events:
        lines.append("- 重要事件：" + "；".join(memory.important_events))
    if memory.previous_assessment_summary:
        lines.append("- 上一轮评估摘要：" + memory.previous_assessment_summary)
    if memory.extra:
        lines.append("- 其他记忆：" + _dump_json(memory.extra))

    if not lines:
        return "暂无可用用户记忆"
    return "\n".join(lines)


def _format_current_input(current: DialogueCurrentUserInput) -> str:
    """渲染【当前用户输入】分区，文本与视觉标签都完整保留。"""
    lines = [f"用户刚刚说：{current.text}"]
    visual_text = format_visual(current.visual)
    if visual_text is not None:
        lines.append(f"这句话的视觉标签：{visual_text}")
    else:
        lines.append("这句话的视觉标签：无")
    return "\n".join(lines)


def _format_decision(decision: DialogueDecision) -> str:
    """渲染【上游最终决策】分区，完整保留 actions / topic / reason。"""
    actions_text = "、".join(decision.actions)
    topic_text = decision.topic if decision.topic else "（未指定）"
    reason_text = decision.reason if decision.reason else "（无）"

    return (
        f"actions：{actions_text}\n"
        f"topic：{topic_text}\n"
        f"reason：{reason_text}"
    )


# --------------------------------------------------------------------------
# Prompt Builder
# --------------------------------------------------------------------------


def build_dialogue_user_prompt(request: DialogueAgentRequest) -> str:
    """把 DialogueAgentRequest 渲染成 Dialogue Agent 的 User Prompt。

    这是**纯函数**：只做格式化，不调用任何模型，也不加入任何新的业务决策。
    同一份 request 永远得到同一份字符串。

    分区结构：
        【历史对话】      -- 仅含当前轮之前的历史（不含本轮输入）
        【用户记忆】      -- 为空时写“暂无可用用户记忆”
        【当前用户输入】  -- 本轮最新的用户输入（文本 + 视觉标签）
        【上游最终决策】  -- actions / topic / reason 完整保留
        【任务】          -- 固定指令：严格按 decision 生成下一句

    Args:
        request: Dialogue Agent 的完整输入（conversation_history / user_memory /
            decision / current_user_input）。

    Returns:
        可直接作为 user message 内容使用的提示词文本。

    Note:
        调用方**不应**把 request.current_user_input 预先追加进
        request.conversation_history，否则本轮输入会在 Prompt 中出现两次。
    """
    sections = [
        "【历史对话】\n" + _format_history(request.conversation_history),
        "【用户记忆】\n" + _format_memory(request.user_memory),
        "【当前用户输入】\n" + _format_current_input(request.current_user_input),
        "【上游最终决策】\n" + _format_decision(request.decision),
        (
            "【任务】\n"
            "请严格按照上游最终决策，结合其他上下文生成下一句回复。\n"
            "- 当前用户输入就是历史对话之后新的一轮，不要与历史中的消息混淆或重复。\n"
            "- 只输出真正要对用户说的那一句话。"
        ),
    ]
    return "\n\n".join(sections)
