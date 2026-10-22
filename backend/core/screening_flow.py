"""访谈轮数边界、逐项覆盖记录及模型结束请求的校验。"""

import re

from backend.models.states import SessionState
from backend.policy.schemas import MAX_INTERVIEW_TURNS, PolicyDecision
from evaluation_agent.rubric import get_item_rubric
from evaluation_agent.schemas import ITEM_KEYS

MAX_TURNS = MAX_INTERVIEW_TURNS
END_REQUEST = re.compile(
    r"^(?:今天|这次)?(?:先)?(?:不聊了|不想聊了|聊到这里|聊到这儿|结束对话|结束筛查|"
    r"停止对话|停止筛查|生成结果|我要生成结果|结束|停止)[吧了。！!\s]*$")


def record_answer(session: SessionState) -> None:
    """记录上一目标收到几次回答；只表示次数，不表示证据充分或症状存在。"""
    progress = session.screening_progress
    if progress.pending_topic is not None:
        item = progress.pending_topic
        progress.topic_turns[item] = progress.topic_turns.get(item, 0) + 1
        progress.pending_topic = None


def completion_reason(session: SessionState, text: str) -> str | None:
    if END_REQUEST.fullmatch(text.strip()):
        return "user_requested"
    if session.turn_count + 1 >= MAX_TURNS:
        return "turn_limit"
    return None


def adopt_decision(session: SessionState, decision: PolicyDecision) -> None:
    """原样记录本轮目标；不按历史次数换题，也不复用旧决策。"""
    session.screening_progress.pending_topic = decision.target_item


def check_model_completion(session: SessionState, decision: PolicyDecision) -> PolicyDecision:
    """11项各收到一次回答后才接受模型收尾；否则补发一个未覆盖目标。

    覆盖只是访谈门槛，不代表评分信息充分。普通追问不改写，全部覆盖也不自动结束。
    """
    if not decision.is_finished:
        return decision
    missing = next((item for item in ITEM_KEYS
                    if session.screening_progress.topic_turns.get(item, 0) < 1), None)
    if missing is None:
        return decision
    rubric = get_item_rubric(missing)
    return PolicyDecision(
        target_item=missing,
        question_goal=(f"该评估小项尚未收到回答。了解学生最近两周与“{rubric.label_zh}”相关的具体情况，"
                       "先确认是否有相关表现或实际困难，不预设存在异常；历史中已明确的信息直接沿用。"),
    )
