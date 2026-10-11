"""Bound demo conversations without adding a trained policy action or scores."""

import re

from backend.models.states import SessionState
from backend.policy.client import DialogueAction, PolicyDecision

TOPICS = (
    DialogueAction.MOOD, DialogueAction.INTEREST, DialogueAction.SLEEP,
    DialogueAction.MENTAL_STATE, DialogueAction.APPETITE, DialogueAction.SOCIAL,
    DialogueAction.PHYSICAL, DialogueAction.SUICIDE,
)
MIN_TURNS = 10
MAX_TURNS = 20
MAX_TOPIC_TURNS = 2
END_REQUEST = re.compile(
    r"^(?:今天|这次)?(?:先)?(?:不聊了|不想聊了|聊到这里|聊到这儿|结束对话|结束筛查|"
    r"停止对话|停止筛查|生成结果|我要生成结果|结束|停止)[吧了。！!\s]*$")


def record_answer(session: SessionState) -> None:
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
