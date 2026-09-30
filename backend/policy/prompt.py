from backend.models.states import Message


POLICY_SYSTEM_PROMPT = """你是一个抑郁评估对话中的策略决策模型。

你的任务是根据截至当前患者发言的完整对话历史，
决定医生下一步应该采取什么对话动作。

可选动作只有：
其它
共情安慰
精神状态
睡眠
情绪
自杀倾向
躯体症状
食欲
社会功能
兴趣
筛查

一次可以输出一个或多个动作。
多个动作必须按照执行顺序输出。

严格输出 JSON：
{"actions": ["动作1", "动作2"]}

不要输出任何解释，不要生成医生具体回复。"""


def build_policy_user_prompt(conversation_history: list[Message]) -> str:
    lines = ["请根据以下对话历史，决定医生下一步的对话动作。", "", "【对话历史】"]
    for message in conversation_history:
        if message.role == "user":
            lines.append(f"患者：{message.content}")
        elif message.role == "assistant":
            lines.append(f"医生：{message.content}")
    return "\n".join(lines)
