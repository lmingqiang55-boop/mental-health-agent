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

from backend.core.text_polarity import text_polarity
from backend.core.visual_acknowledgment import TONE_LABELS, VISUAL_LABELS
from backend.models.dialogue import (
    DialogueAgentRequest,
    DialogueCurrentUserInput,
    DialogueDecision,
    DialogueHistoryMessage,
    DialogueRouteRequest,
    DialogueUserMemory,
    DialogueVisual,
)

__all__ = [
    "DIALOGUE_AGENT_SYSTEM_PROMPT",
    "DIALOGUE_ROUTER_SYSTEM_PROMPT",
    "REFUSAL_PHRASES",
    "build_dialogue_user_prompt",
    "build_dialogue_route_prompt",
    "is_refusal",
]

# 外观线索与语气的说法直接取视觉模块的那一份，不在本文件另抄一份：
# 两处各存一份同样内容的表时，改文案只会改到一处，于是"后端允许说的"
# 和"提示词里说的"会悄悄分家（VISUAL_LABELS / TONE_LABELS 见
# backend/core/visual_acknowledgment.py）。

#: 用户明确表示「不想说 / 不想继续这个话题」的说法。
#:
#: 这是一份**词表**，不做语义推断：命中即认为用户表达了拒绝，本轮不追问。
#: 之所以要单独判一次，是因为"拒绝"常常长得很短（"我不想说"只有 5 个字），
#: 会被下面的"简短回答 → 直接推进"规则接管，反过来催他回答——正是要避免的行为。
#: 因此拒绝判定必须排在简短回答判定**之前**。
REFUSAL_PHRASES: tuple[str, ...] = (
    "不想说", "不想聊", "不想谈", "不想提", "不想讲",
    "不愿说", "不愿意说", "不想回答", "不愿意回答", "不方便说", "不好说",
    "别问了", "不要问了", "没什么好说", "没什么可说", "没什么说的",
    "换个话题", "说点别的", "不想继续",
)


def is_refusal(text: str) -> bool:
    """用户这句话是否明确表达了拒绝（不想说 / 不想继续这个话题）。"""
    if not text:
        return False
    stripped = text.strip()
    return any(phrase in stripped for phrase in REFUSAL_PHRASES)


def _polarity_phrase(value: float) -> str:
    """把 -1~1 的极性说成人话，供核对句描述用。"""
    return "积极（轻松、开心一类）" if value > 0 else "消极（低落、疲惫一类）"


def _visual_section(request: DialogueAgentRequest) -> str:
    """【本轮视觉观察】的正文；四种情况互斥，只有一种会出现。

    优先核对而不是顺口一提：当后端判定"说的和显示的反着来"，先按核对的要求写，
    免得同一句里既报出一个情绪名字又要去核对，前后打架。说不出名字时退一步
    只用整体语气，措辞上**不许把语气说成某个具体情绪**——那正是这一档要避免的
    过度解读。
    """
    discordance = request.visual_discordance
    if discordance is not None:
        return (
            f"这一句说出来的情绪偏{_polarity_phrase(discordance.text_polarity)}，"
            f"但画面上的表情偏{_polarity_phrase(discordance.vision_valence)}，两者方向相反。"
            "先用一句话接住他说出来的内容，再用试探的语气核对一次，"
            "例如“你说还好，不过看你好像有点累，是这样吗？”。"
            "只核对一次：不下结论，不说他在掩饰、逞强或不诚实，不把它变成新的情绪话题，"
            "主要问题仍必须围绕 decision.topic。"
            "整句由你根据上下文组织，不要提摄像头、检测器或数值。"
        )
    if request.visual_observation:
        return (
            f"可靠画面提供的外观线索：{VISUAL_LABELS[request.visual_observation]}。"
            "请把这项线索自然融入执行 decision 的完整回复，例如用‘你看起来……’带出当前问题；"
            "主要问题仍必须围绕 decision.topic，不要转而追问表情或另一个情绪话题。"
            "整句由你根据上下文组织，不要套固定开头。语气保持试探，不把表情当作用户内心感受或诊断，"
            "不要提摄像头、检测器或数值。"
        )
    if request.visual_tone:
        return (
            f"可靠画面显示他此刻的状态{TONE_LABELS[request.visual_tone]}，"
            "这是**外观线索**，不是他说的内容，也**不是**一个具体情绪，"
            "只是画面整体的轻重方向。"
            "必须用一句外观描述把它带进回复（如“你看起来有点累”“感觉你今天没什么精神”），"
            "不能只当成上下文背景；"
            "但不能命名具体情绪（不说“你很伤心”“你在焦虑”），也不能当成对他内心的判断。"
            "先接住他说出来的内容，再带一次外观描述，只提一次；"
            "主要问题仍必须围绕 decision.topic。"
            "整句由你根据上下文组织，不要提摄像头、检测器或数值。"
        )
    return "本轮没有可口头提及的视觉观察。"


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
   - 只有本轮明确给出 visual_observation、visual_discordance 或 visual_tone 时，
     才可以自然提及用户看起来的状态；
   - 三者都没有时，不要根据原始视觉标签自行描述用户的表情；
   - 给出 visual_discordance 时，只做一次温和核对：先接住他说的内容，再用试探的
     语气确认一句，不下任何结论，不说他在掩饰、逞强或不诚实，也不要反复追问同一件事；
   - 给出 visual_tone 时，那只是画面整体的轻重方向，不是情绪名字：可以说“你看起来
     有点累”这类语气描述，不可以说“你很伤心”“你在焦虑”，也不要把它当成对内心的判断；
   - 不得出现“我检测到你的 valence 是 -0.5”这类表达。

【执行 decision 的方式】
8. 如果 decision 包含“共情安慰”：针对明确的痛苦简短回应即可，
   不需要每次用“嗯”“听起来”“听你这么说”开头，也不需要复述用户的话来证明你听见了。
   但他这句话本身带着明显情绪时（累、烦、难受、撑不住、没意思、睡不好……），
   即使 decision 的 action 里没有“共情安慰”，也要先用一条消息接住这个情绪，
   再按 decision 推进话题——不要跳过情绪、只丢下一个问题。
   他明确表示不想说时，按【本轮表达要求】处理（先接纳，不追问）。
9. 切换话题时让问题与上下文相关；需要时用一句简短过渡，
   同一话题的追问可以直接问，不必每次重复上一句话再承接。
10. 如果 decision 要求继续当前话题：根据 conversation_history 判断已经问过什么，
    不要重复同一个问题，应围绕当前 topic 进行新的、合理的追问。
    用户已经明确回答的内容不再换个说法问一遍；只补充尚缺的时间、频率或生活影响。
    用户短答“是”“没有”“一个月”“每天”时，直接推进，不逐字复述或反复确认。
    但如果他刚才只是在倾诉、或者上一个问题他还没答完，可以先只回应，把追问留到下一轮。
11. 每轮**最多**提出一个主要问题，也**可以一个问题都不提**。允许这几种回复：
    - 纯共情：只接住他的感受，不提问；
    - 共情 + 追问：先回应，再问一个问题；
    - 回应 / 安慰 / 简单建议：说完就停，不追加问题；
    - 尊重拒绝：他不想说时先接纳，不追问。
    一条消息里只放**一个**问题：不要在一个气泡里连问两个
    （“是不是……？平时……？”就是两个，要拆成两轮或只留一个）。
    评估仍然要推进：需要了解的信息还没问到、且他情绪平稳时，
    仍应用一个自然的问题推进当前话题；但不必每一轮都提问——
    连续追问会让对话变成问卷。

【表达风格】
12. 回复应当：自然、简洁、口语化、像真实对话；不要像问卷，不要像心理医生照着量表逐条念。
13. 不得暴露任何内部系统信息，包括：action、decision、topic、visual、memory、
    “决策 Agent”、“上游”、“评估维度”等字样。
14. 不要输出解释、分析或推理过程。
15. 最终只生成真正要对用户说的话，并按下面的【输出格式】组织成 1~3 条消息。
16. 不做医学诊断，不说“你就是抑郁症”“你已经患有重度抑郁”这类结论性判断。
17. 当用户表达明显痛苦时，语言应更加温和，不要机械跳题；但依然必须服从最终 decision。
18. finish_screening=true 时只做简短收尾并提示可以生成本次对话的初步结果；
    不再提问、不引入新话题、不宣称已经完成诊断或所有信息已完整。

【输出格式（会直接决定聊天气泡的条数）】
19. 每轮输出 1~3 条消息，**每条消息单独占一行**。
    不要编号、不要项目符号、不要用空行分隔两条消息、不要输出代码块或引号。
20. 条数按**表达单元**决定，不按句子长短，也不要为了凑数量而拆分或添加内容：
    - 只有一个表达单元（只回应感受，或只问一个问题）：**1 条**；
    - 同时有“回应/共情”和“追问”两个单元：**必须拆成 2 条**，一条一行，
      不要用逗号或句号把这两个单元连在同一行；
    - 除了回应与追问还确实要说第三件事（说明、建议、提醒）：最多 **3 条**。
21. 每条消息都必须是完整、能直接说出口的一句话，不能出现半句或只有标点。
    不要把一个完整句子从中间断开——分段要分在句子之间，不要分在句子内部。
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
        + (f"\n话题交流记录：{_dump_json(decision.extra['topic_turns'])}"
           if 'topic_turns' in decision.extra else "")
        + (f"\n【后端话题补充要求】\n{decision.extra['coverage_reminder']}"
           if decision.extra.get('coverage_reminder') else "")
    )


# --------------------------------------------------------------------------
# Prompt Builder
# --------------------------------------------------------------------------


def _turn_requirement(request: DialogueAgentRequest) -> str:
    """渲染【本轮表达要求】：这一轮到底该"只回应"还是"回应+追问"。

    判定顺序是刻意的：**收尾 > 拒绝 > 简短且无情绪 > 一般情况**。

    "我不想说"只有 5 个字，如果先落进"简短回答 → 直接推进"那一档，
    就会变成催他回答——所以拒绝必须在简短回答之前拦下来。

    而"简短"这一档还要再过一道**情绪**闸门。这一条是被实机验收逼出来的：
    原先只按 ``len <= 12`` 判断，于是"我最近真的好累。"（8 字）、
    "晚上睡不好，白天没精神。"（12 字）这类**又短又带情绪**的自述全部落进
    "直接推进……不套共情前缀"那一档，模型于是每次都只丢回一个问题——
    这正是"每轮都在问、从不接住情绪"的机制性来源。

    闸门用的是项目自己的 :func:`~backend.core.text_polarity.text_polarity`：
    读得出情绪词（"累""烦""闷""睡不好"…）就说明这不是一句单纯的信息性回答，
    不该被当成"是/每天/一个月"那样处理；读不出时才走"直接推进"。
    这样不新增任何模型调用，判据也只有一个来源。
    """
    if request.finish_screening:
        return "本轮只收尾，不提出任何问题；提示可点击‘生成结果’，不自行生成评估。"

    text = request.current_user_input.text
    if is_refusal(text):
        return (
            "用户表示不想说、不想继续这个话题。先接纳他的意愿，"
            "**不要追问他不愿说的那件事**，也不要换个说法再问一遍；"
            "可以只陪伴、不提问，或用一句简短的过渡把话题自然带开。"
        )
    if len(text.strip()) <= 12 and text_polarity(text) is None:
        return "用户是简短回答，请直接推进尚未了解的信息，不复述这句回答，不套共情前缀。"
    return (
        "根据实际需要决定是只回应、还是回应后追问一个问题："
        "可以一个问题都不提；不要每一轮先复述再提问，避免重复最近回复的开头。"
    )


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
        "【本轮表达要求】\n" + _turn_requirement(request),
        "【本轮视觉观察】\n" + _visual_section(request),
        (
            "【任务】\n"
            "请严格按照上游最终决策，结合其他上下文生成下一轮回复。\n"
            "- 当前用户输入就是历史对话之后新的一轮，不要与历史中的消息混淆或重复。\n"
            "- 按【输出格式】组织：1~3 条消息，每条消息单独占一行，一行就是一条。"
        ),
    ]
    return "\n\n".join(sections)


# --------------------------------------------------------------------------
# Dialogue 路由（Phase 2）：判断这一轮是否需要新的全局策略
# --------------------------------------------------------------------------

DIALOGUE_ROUTER_SYSTEM_PROMPT = """你是心理状态评估系统中 Dialogue Agent 的**路由模块**。

【你的唯一职责】
判断"这一轮是否需要重新调用决策模型，取得新的**全局**评估策略"。

【你不是决策模型】
你不选择话题，也不决定换成哪个话题。
需要换话题时，你只能说"需要"，由决策模型决定换成哪一个。
因此你的输出里**没有**话题字段，也不要在 reason 里指定新话题。

【什么情况需要新策略（need_decision = true）】
1. 当前话题已经问得差不多，再追问只会重复用户已经答过的内容。
2. 用户表达了想换话题、不想聊这个，或明确说这个话题没什么可说的。
3. 用户这句话与当前话题关系不大，硬顺着当前话题问会显得生硬。
4. 你需要一个完全不同的方向才能继续推进评估。

【什么情况不需要（need_decision = false）】
1. 用户刚给出新的具体信息（时间、频率、程度、影响、例子），顺势再追问一句很自然。
2. 用户需要先被回应或被澄清，澄清完再继续当前话题即可。
3. 用户情绪明显，需要先共情承接；此时马上换话题会显得机械、不近人情。

【判断准则】
- 不要每一轮都要求新策略：追问是正常对话的一部分，不是异常。
- 也不要总是选择继续：同一个话题连续追问超过两轮就会像问卷。
- 拿不准时选 need_decision = true。多调一次决策模型是安全的，
  漏掉一次必要的话题推进不是。

只输出一个 JSON 对象，不要输出解释、前后缀或代码块以外的任何内容：
{"need_decision": true 或 false, "reason_code": "简短原因码", "reason": "一句话理由"}

reason_code 只能取以下之一：
- continue_topic     当前话题还值得追问
- clarify            需要先澄清用户刚说的内容
- topic_exhausted    当前话题问得差不多了，需要新方向
- user_wants_change  用户想换话题或不想继续当前话题
- off_topic          用户说的与当前话题无关，需要新方向
"""


def _format_route_progress(request: DialogueRouteRequest) -> str:
    """渲染【评估进度】分区：让路由模块知道当前话题用了多少轮、还剩多少轮。"""
    if request.active_topic:
        head = (f"当前话题：{request.active_topic}"
                f"（已完成 {request.active_topic_turns} 轮，"
                f"单话题上限 {request.topic_limit} 轮）")
    else:
        head = "当前话题：（尚未确定）"
    covered = "、".join(
        f"{topic} {count} 轮" for topic, count in request.topic_turns.items()) or "（暂无）"
    lines = [
        head,
        f"各话题轮数：{covered}",
        f"已完成轮数：{request.turn_count}"
        f"（第 {request.min_turns} 轮起才可能收尾，第 {request.max_turns} 轮强制收尾）",
    ]
    if request.coverage_reminder:
        lines.append(request.coverage_reminder)
    return "\n".join(lines)


def build_dialogue_route_prompt(request: DialogueRouteRequest) -> str:
    """把 DialogueRouteRequest 渲染成路由模块的 User Prompt。

    与 :func:`build_dialogue_user_prompt` 一样是**纯函数**：只做格式化，
    不调用模型、不做任何业务判断、不含话题候选列表。
    """
    actions_text = "、".join(request.active_actions) or "（尚无有效全局策略）"
    sections = [
        "【历史对话】\n" + _format_history(request.conversation_history),
        "【当前用户输入】\n" + _format_current_input(request.current_user_input),
        "【当前全局策略】\n" + f"actions：{actions_text}",
        "【评估进度】\n" + _format_route_progress(request),
        (
            "【任务】\n"
            "判断这一轮是否需要重新调用决策模型取得新的全局策略。\n"
            "- 只判断“需不需要”，不要指定新话题。\n"
            "- 只输出一个 JSON 对象。"
        ),
    ]
    return "\n\n".join(sections)
