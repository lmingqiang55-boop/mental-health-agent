"""在本地按决策动作生成基础回复，不额外传输对话内容。"""

from backend.policy.client import DialogueAction, PolicyDecision

QUESTIONS = {
    DialogueAction.OTHER: "你愿意多说说最近最困扰你的事吗？",
    DialogueAction.MENTAL_STATE: "最近你的精神状态怎么样？精力和注意力有变化吗？",
    DialogueAction.SLEEP: "最近睡眠怎么样？入睡或早醒有没有困扰你？",
    DialogueAction.MOOD: "最近心情怎么样？有没有什么情绪反复出现？",
    DialogueAction.SUICIDE: "有些人在特别难受时会想到伤害自己，你最近有过这样的想法吗？",
    DialogueAction.PHYSICAL: "最近身体有没有不舒服，或者经常疲惫、疼痛？",
    DialogueAction.APPETITE: "最近吃饭和食欲怎么样？和平时相比有变化吗？",
    DialogueAction.SOCIAL: "最近和家人、朋友或同学相处得怎么样？",
    DialogueAction.INTEREST: "最近还有什么事情能让你感到有兴趣吗？",
    DialogueAction.SCREENING: "为了更了解你的情况，接下来我想问几个方面。你现在最想先说哪一个？",
}

EMPATHY = "听起来这段时间对你并不容易。"


def reply_for_decision(decision: PolicyDecision) -> str:
    """遵循动作顺序；共情作为前缀，最后一个具体动作决定主要问题。"""
    has_empathy = DialogueAction.EMPATHY in decision.actions
    topics = [action for action in decision.actions if action != DialogueAction.EMPATHY]
    question = QUESTIONS[topics[-1]] if topics else "你愿意多说说现在的感受吗？"
    return f"{EMPATHY}{question}" if has_empathy else question
