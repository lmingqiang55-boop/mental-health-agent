"""Mock 话术模板与策略命名。

策略命名规则：``explore_{dimension}``。真实 LLM Provider 接入后，
这些文案作为兜底，不改变 DialogueManager 的策略决定权。
"""

QUESTIONS = {
    # 六维评估
    "explore_mood": "最近心情整体怎么样？有没有觉得情绪比平时低落？",
    "explore_pressure": "最近会不会觉得压力比较大？主要来自哪些方面？",
    "explore_interpersonal": "最近和同学、朋友或家人的相处还顺利吗？",
    "explore_self_cognition": "你怎么看待最近的自己？会不会经常否定自己？",
    "explore_study_life": "最近学习或日常生活状态怎么样？有没有受到什么影响？",
    "explore_duration": "这种状态大概持续多久了？",
    # 对话控制
    "clarify_answer": "能再具体说一点吗？比如它从什么时候开始、对你有什么影响。",
    "follow_up": "谢谢你愿意分享。还有什么最近的变化想补充吗？",
    "crisis_support": "听起来你现在可能很难受。请尽快联系身边可信任的人、当地急救服务或专业危机支持，确保自己此刻有人陪伴。",
    "finish_assessment": "谢谢你的分享。初步问题已经问完，我来整理一下你的状态，请稍等。",
    "post_assessment": "评估结果已经生成。如果这些变化持续影响生活，可以考虑联系专业人士进一步交流。",
}
