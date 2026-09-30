"""决策模型的输入提示词。"""

from backend.models.enums import MessageRole
from backend.models.states import Message

POLICY_SYSTEM_PROMPT = """你是心理状态评估对话中的策略决策模型。
根据截至当前用户发言的完整对话历史，决定助手下一步的对话动作。
可选动作只有：其它、共情安慰、精神状态、睡眠、情绪、自杀倾向、躯体症状、食欲、社会功能、兴趣、筛查。
一次可以输出多个动作，按执行顺序排列。
严格输出 JSON：{"actions": ["动作1", "动作2"]}
不要输出解释或具体回复。"""


def build_policy_user_prompt(conversation_history: list[Message]) -> str:
    lines = ["请根据以下对话历史决定下一步动作。", "", "【对话历史】"]
    for message in conversation_history:
        if message.role == MessageRole.USER:
            lines.append(f"用户：{message.content}")
        elif message.role == MessageRole.ASSISTANT:
            lines.append(f"助手：{message.content}")
    return "\n".join(lines)
