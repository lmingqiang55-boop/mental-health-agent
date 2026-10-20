"""Bound demo conversations without adding a trained policy action or scores."""

import re

from backend.models.states import ScreeningProgress, SessionState
from backend.policy.client import DialogueAction, PolicyDecision

TOPICS = (
    DialogueAction.MOOD, DialogueAction.INTEREST, DialogueAction.SLEEP,
    DialogueAction.MENTAL_STATE, DialogueAction.APPETITE, DialogueAction.SOCIAL,
    DialogueAction.PHYSICAL, DialogueAction.SUICIDE,
)
MIN_TURNS = 10
COVERAGE_REMINDER_TURN = 25
MAX_TURNS = 35
MAX_TOPIC_TURNS = 2
END_REQUEST = re.compile(
    r"^(?:今天|这次)?(?:先)?(?:不聊了|不想聊了|聊到这里|聊到这儿|结束对话|结束筛查|"
    r"停止对话|停止筛查|生成结果|我要生成结果|结束|停止)[吧了。！!\s]*$")

#: 后端强制调用决策模型的原因码。这些条件下**不**交给 Dialogue 判断，
#: 因为继续沿用当前策略一定是错的或没有意义的。
FORCE_NO_ACTIVE_DECISION = "no_active_decision"
FORCE_ACTIVE_DECISION_INVALID = "active_decision_invalid"
FORCE_NO_ACTIVE_TOPIC = "no_active_topic"
FORCE_ACTIVE_TOPIC_INVALID = "active_topic_invalid"
FORCE_TOPIC_BUDGET = "topic_budget_exhausted"
FORCE_SENSITIVE_TOPIC = "sensitive_topic"
FORCE_COVERAGE_LAG = "coverage_lag"

_TOPIC_VALUES = frozenset(topic.value for topic in TOPICS)
_ACTION_VALUES = frozenset(action.value for action in DialogueAction)


def coverage_complete(progress: ScreeningProgress) -> bool:
    """是否每个话题都至少聊过一次——这是 ``topic_coverage`` 收尾的前提。"""
    return all(progress.topic_turns.get(topic.value, 0) >= 1 for topic in TOPICS)


def coverage_reminder(session: SessionState) -> str | None:
    """第 25 轮起，把轮数预算及尚未涉及的话题明确交给模型。

    ``turn_count`` 尚未包含正在处理的用户输入；本提示在登记该回答后构造。
    话题计数只描述交流进度，不代表评分证据已经充分。
    """
    current_turn = session.turn_count + 1
    missing = [topic.value for topic in TOPICS
               if session.screening_progress.topic_turns.get(topic.value, 0) < 1]
    if not COVERAGE_REMINDER_TURN <= current_turn < MAX_TURNS or not missing:
        return None
    return (
        f"当前是第 {current_turn} 轮，第 {MAX_TURNS} 轮必须结束对话。"
        f"从第 {COVERAGE_REMINDER_TURN} 轮起，请尽快补充尚未涉及的话题："
        f"{'、'.join(missing)}。"
        "优先了解这些缺失话题，避免在已经了解的话题上重复追问；"
        "保持自然，每轮最多一个主要问题，尊重用户不愿回答的意愿。"
        "这些记录只表示话题交流次数，不代表相关评估信息已经充分。"
    )


def record_answer(session: SessionState) -> None:
    """把上一条用户回答登记到它所属的评估话题下。

    幂等性来自**消费即清空**：``pending_topic`` 一旦被计数就置为 ``None``，
    因此同一轮里重复调用不会重复累加。这也是"同一条用户回答不得重复计数"
    的实现方式——不依赖本轮是否调用过决策模型，只看 ``pending_topic``。
    """
    progress = session.screening_progress
    if progress.pending_topic is not None:
        topic = progress.pending_topic
        progress.topic_turns[topic] = progress.topic_turns.get(topic, 0) + 1
        progress.pending_topic = None


def completion_reason(session: SessionState, text: str) -> str | None:
    if END_REQUEST.fullmatch(text.strip()):
        return "user_requested"
    next_count = session.turn_count + 1
    if next_count >= MAX_TURNS:
        return "turn_limit"
    if next_count >= MIN_TURNS and all(
            session.screening_progress.topic_turns.get(topic.value, 0) >= 1
            for topic in TOPICS):
        return "topic_coverage"
    return None


def limit_topic(session: SessionState, decision: PolicyDecision) -> PolicyDecision:
    """Let policy select until its topic budget is exhausted, then visit gaps."""
    counts = session.screening_progress.topic_turns
    candidates = [action for action in decision.actions if action in TOPICS]
    topic = candidates[-1] if candidates else None
    replace = (topic is not None and counts.get(topic.value, 0) >= MAX_TOPIC_TURNS) or (
        topic is None and session.turn_count >= 2)
    if replace:
        available = [item for item in TOPICS if counts.get(item.value, 0) < MAX_TOPIC_TURNS]
        if available:
            topic = min(available, key=lambda item: counts.get(item.value, 0))
            prefix = [DialogueAction.EMPATHY] if DialogueAction.EMPATHY in decision.actions else []
            decision = PolicyDecision(actions=[*prefix, topic])
    session.screening_progress.pending_topic = topic.value if topic else None
    return decision


def should_force_decision(session: SessionState) -> str | None:
    """后端必须重新调用决策模型时返回原因码，否则返回 ``None`` 交给 Dialogue 判断。

    "必须"的情形：还没有任何有效的全局策略；已存策略或当前话题已失效；
    当前话题已到次数上限（继续追问一定是重复的）；以及高风险话题不做自主追问。
    """
    progress = session.screening_progress
    if not progress.active_actions:
        return FORCE_NO_ACTIVE_DECISION
    if any(action not in _ACTION_VALUES for action in progress.active_actions):
        return FORCE_ACTIVE_DECISION_INVALID
    if progress.active_topic is None:
        return FORCE_NO_ACTIVE_TOPIC
    if progress.active_topic not in _TOPIC_VALUES:
        return FORCE_ACTIVE_TOPIC_INVALID
    if progress.topic_turns.get(progress.active_topic, 0) >= MAX_TOPIC_TURNS:
        return FORCE_TOPIC_BUDGET
    if progress.active_topic == DialogueAction.SUICIDE.value:
        # 高风险话题刻意**不**让 Dialogue 自主追问：每一轮都回到决策模型，
        # 由既有规则决定是否继续、换向还是收尾，避免在同一敏感方向上连问两轮。
        return FORCE_SENSITIVE_TOPIC
    if (session.turn_count + 1 >= COVERAGE_REMINDER_TURN
            and not coverage_complete(progress)):
        # 补充阶段不能只复用旧策略：让决策模型也收到最新缺项提醒。
        return FORCE_COVERAGE_LAG
    if (session.turn_count + 1 >= MIN_TURNS
            and progress.topic_turns.get(progress.active_topic, 0) >= 1
            and not coverage_complete(progress)):
        # 已经过了可以收尾的最少轮数，但话题覆盖还不全：此时让 Dialogue 继续
        # 追问会把话轮花在同一个话题上，覆盖面推进变慢（自主追问模式下每个
        # 话题都会用满 2 轮）。这里优先补齐没聊过的话题，保证覆盖率不被
        # "减少决策调用"牺牲掉。
        return FORCE_COVERAGE_LAG
    return None


def adopt_decision(session: SessionState, decision: PolicyDecision,
                   topic: str | None) -> None:
    """决策模型给出的新方向生效：记录 ``active_*``，并登记下一条回答的话题。

    ``topic`` 由 :func:`limit_topic` 决定后传入，避免这里再算一遍话题而分家。

    决策只返回非评估动作（``其它``、或``共情安慰 + 其它``）时 **没有** 任何
    评估话题可言，这不是"继续上一个话题"的有效决定，因此：

    * ``active_topic`` 清空 —— 否则旧话题会被当成仍然有效；
    * ``pending_topic`` 置空 —— 下一条回答**不计入任何话题**，
      避免无依据地累计旧话题次数；
    * ``active_actions`` 照样记录 —— 决策本身是有效的，下一轮
      :func:`should_force_decision` 会因 ``active_topic is None`` 重新决策，
      于是能重新进入一个有效评估话题。
    """
    progress = session.screening_progress
    progress.active_topic = topic
    progress.active_actions = [action.value for action in decision.actions]
    progress.pending_topic = topic


def carry_over_topic(session: SessionState) -> None:
    """Dialogue 自主追问：只把当前话题续到下一轮。

    刻意**不改动** ``active_topic`` / ``active_actions``：Dialogue 无权选择
    或更换全局话题，它只能继续当前话题。
    """
    session.screening_progress.pending_topic = session.screening_progress.active_topic
