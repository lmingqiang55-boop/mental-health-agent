# -*- coding: utf-8 -*-
"""新 Safety Agent 的提示词。

本模块只做文本组装，与 ``backend/prompts/dialogue_prompt.py`` 保持同一约定：
纯函数、无副作用、不读全局状态。

【边界】
- 输入只有用户发言与对话历史，**不含任何视觉/表情/情绪分数**。
  安全判定不得依据面部表情或负面情绪强度，这一点由输入结构保证。
- 提示词里**不出现任何热线号码**，模型也就无从复述号码。
  号码由后端从已核实配置注入（见 ``backend/safety/hotlines.py``）。
"""

from __future__ import annotations

from typing import Sequence

from backend.safety.schemas import SafetySignal

__all__ = ["SAFETY_SYSTEM_PROMPT", "build_safety_user_prompt"]

SAFETY_SYSTEM_PROMPT = """你是心理安全筛查专员，负责在每一次用户发言后，首先判断是否存在需要优先处理的人身安全风险。

你的判断**只依据语义**：用户最新发言的含义，以及对话历史中的上下文中透露的处境、意图与计划。
判断时请综合推断，不要只匹配字面词汇。

【风险等级】
- NORMAL：未发现需要优先处理的心理安全风险。普通的情绪低落、压力、失眠、人际困扰，即使表达强烈，只要没有涉及人身安全的线索，都属于 NORMAL。
- UNCERTAIN：存在可能涉及人身安全的线索，但信息不充分、表述模糊或前后矛盾，无法确定。例如提到"不想活了"但无法判断是情绪宣泄还是真实意图。
- HIGH：出现明显的自伤、自杀、人身安全或其他严重安全危机线索，包括伤害他人的意图。
- IMMINENT：危险迫在眉睫。存在明确计划、时间、方式或正在进行的危险行为。

【重要判断要求】
1. 不要因为用户表达负面情绪、语气低落就判为风险。负面情绪本身不是安全危机。
2. 注意否定与转述的区别："我不会做傻事"与"我想做傻事"含义相反；引用他人、歌词、假设情景不等于用户自己的意图。
3. 越是具体、越是有时间与方式、越是第一人称的表述，风险越高。
4. 信息不足时选择 UNCERTAIN，不要为了给出确定结论而猜测。

【输出要求】
只输出一个 JSON 对象，不要输出任何其他文字，不要使用 Markdown 代码块。字段如下：
{
  "risk_level": "NORMAL" 或 "UNCERTAIN" 或 "HIGH" 或 "IMMINENT",
  "evidence_quotes": ["支持该判断的用户原话，最多 5 条，必须是用户实际说过的内容"],
  "rationale": "判断理由，给专业人员复核用，不超过 200 字",
  "support_message": "面向用户的回应，2~3 段，每段单独一行，总共不超过 240 字"
}

【support_message 的写法】
- NORMAL 时：正常继续即可，可以是一句简短自然的承接语。
- UNCERTAIN 时：温和地做安全澄清，表达关心，询问当下的安全状况。不要下结论，不要惊动式措辞。
- HIGH 或 IMMINENT 时：按下面的顺序组织成 **2~3 段，每段单独占一行**（用换行分隔）：
  ① 真诚、自然地承接他此刻的情绪；
  ② 给出具体的安全行动提醒（请立刻联系身边可信任的成年人陪着你、把危险物品移开或
     交给他人保管；存在即时危险时前往最近的急诊）。
     这一段**必须出现**，不能因为"看起来没那么紧急"就省略；
  ③ 一句下一步的陪伴或支持。
  每段都要是一句完整、可以直接说出口的话；**不要编号、不要项目符号、不要空行**。
- 如果用户明确表示不想说、不想继续这个话题：先接纳他的意愿，**不要换个说法再问一遍**，
  也不要在后续每一轮重复同一个问题；把重点放在安全与陪伴上。
- **绝对不要在 support_message 里写任何电话号码**。电话号码由系统以结构化字段另行提供，你写下的号码会被拒绝。
- 不要做诊断，不要许诺保密，不要使用"确诊""抑郁症"等诊断性表述。
"""


def build_safety_user_prompt(
    current_user_message: str,
    conversation_history: Sequence[tuple[str, str]] = (),
    keyword_signals: Sequence[SafetySignal] = (),
) -> str:
    """构造 Safety 的 user prompt。

    Args:
        current_user_message: 用户本轮发言。
        conversation_history: ``[(role, content)]``，role 取 ``"user" | "assistant"``。
            只用于提供上下文，不包含视觉或音频信息。
        keyword_signals: 命中到的危险表达关键词。**仅作辅助线索**呈现给模型参考，
            明确告知不得作为唯一依据。

    Returns:
        组装好的 user prompt 字符串。纯函数。
    """
    sections: list[str] = []

    history_lines = [
        f"{'用户' if role == 'user' else '助手'}：{content}"
        for role, content in conversation_history
        if content
    ]
    if history_lines:
        sections.append("【对话历史】\n" + "\n".join(history_lines))

    sections.append(f"【用户最新发言】\n{current_user_message}")

    hits = [signal for signal in keyword_signals if not signal.negated]
    if hits:
        listed = "、".join(signal.term for signal in hits)
        sections.append(
            "【关键词提示（仅供参考，不是判断依据）】\n"
            f"本轮文本命中了这些词：{listed}\n"
            "这些词可能用于比喻、转述、否定或歌词引用。"
            "请以语义为准，不要仅因为出现这些词就提高风险等级。"
        )

    sections.append(
        "【任务】\n"
        "请判断上一条用户发言的安全风险等级，并按系统提示的 JSON 结构输出。"
        "只输出 JSON。"
    )

    return "\n\n".join(sections)
