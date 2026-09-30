import random

TOPICS = [
    "精神状态",
    "睡眠",
    "情绪",
    "自杀倾向",
    "躯体症状",
    "食欲",
    "社会功能",
    "兴趣",
]

MAX_TOPIC_COUNT = 3


class TopicConstraint:
    """
    对决策 Agent 输出的话题进行次数约束。

    规则：
    1. 只统计 8 个核心话题。
    2. 其它 / 共情安慰 / 筛查等动作不计数。
    3. 同一个话题前 3 次正常通过。
    4. 第 4 次再次出现时：
       - 优先随机转向一个从未聊过的话题；
       - 如果所有话题都聊过，则随机选择一个出现次数 < 3 的其他话题。
    5. 开始一次新的测评时调用 reset()，全部计数清零。
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """开始新一轮测评时，将所有话题计数清零。"""
        self.counts = {
            topic: 0
            for topic in TOPICS
        }

    def apply(self, actions: list[str]) -> list[str]:
        """
        对 Policy 输出的 actions 进行后处理。
        """

        final_actions: list[str] = []

        for action in actions:

            # 共情安慰 / 其它 / 筛查等非核心话题直接通过
            if action not in TOPICS:
                final_actions.append(action)
                continue

            # 前 3 次正常通过
            if self.counts[action] < MAX_TOPIC_COUNT:
                self.counts[action] += 1
                final_actions.append(action)
                continue

            # -----------------------------
            # 当前话题已经出现 3 次
            # 第 4 次开始自动转话题
            # -----------------------------

            # 优先选择从未聊过的话题
            candidates = [
                topic
                for topic in TOPICS
                if topic != action
                and self.counts[topic] == 0
            ]

            # 如果所有话题都聊过
            # 则选择还没有达到 3 次的话题
            if not candidates:
                candidates = [
                    topic
                    for topic in TOPICS
                    if topic != action
                    and self.counts[topic] < MAX_TOPIC_COUNT
                ]

            # 如果所有话题都已经达到 3 次
            # 则不再强制转话题
            if not candidates:
                final_actions.append(action)
                continue

            new_topic = random.choice(candidates)

            # 新话题记一次
            self.counts[new_topic] += 1

            # 给后面的对话 Agent 明确的转场指令
            final_actions.append(
                f"当前话题从{action}转到{new_topic}"
            )

        return final_actions


# 整个程序使用这一份约束器
topic_constraint = TopicConstraint()