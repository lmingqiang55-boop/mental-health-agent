# -*- coding: utf-8 -*-
"""离线比较 legacy 与 graph 的每轮决策次数及35轮收尾。

两个模型使用离线桩，执行真实的图与 DialogueManager。
固定返回同一评估小项，用于观察后端是否仍会按次数改题。

运行::

    python scripts/compare_decision_budget.py
    python scripts/compare_decision_budget.py --turns 35
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from backend.core.dialogue_manager import DialogueManager  # noqa: E402
from backend.graph.engine import (  # noqa: E402
    DIALOGUE_ENGINE_ENV, ENGINE_GRAPH, ENGINE_LEGACY, DialogueTurnRunner,
)
from backend.models.dialogue import DialogueAgentResponse  # noqa: E402
from backend.models.enums import MessageRole  # noqa: E402
from backend.models.states import Message, SessionState  # noqa: E402
from backend.policy.client import HttpPolicyClient  # noqa: E402
from backend.policy.schemas import MAX_INTERVIEW_TURNS  # noqa: E402

FIXED_DECISION = {
    "target_item": "sleep_disturbance",
    "question_goal": "了解尚未说明的睡眠表现",
}


class DialogueStub:
    """离线对话 Agent：记录调用次数，不碰网络。"""

    def __init__(self) -> None:
        self.reply_calls = 0

    async def generate_reply(self, request) -> DialogueAgentResponse:
        self.reply_calls += 1
        if request.finish_screening:
            return DialogueAgentResponse(reply="本次访谈结束，可以生成评估结果了。")
        return DialogueAgentResponse(reply=f"继续了解{request.decision.target_label}。")


def build_policy_client(counter: list) -> HttpPolicyClient:
    """决策模型桩：每次返回同一目标，并记录请求。"""

    def handle(request: httpx.Request) -> httpx.Response:
        counter.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(
                FIXED_DECISION, ensure_ascii=False)}}]})

    return HttpPolicyClient(client=httpx.Client(transport=httpx.MockTransport(handle)))


def run_mode(engine: str, turns: int) -> dict:
    """跑一整段脚本会话，返回各模型的调用次数。"""
    os.environ[DIALOGUE_ENGINE_ENV] = engine
    policy_requests: list = []
    agent = DialogueStub()
    manager = DialogueManager(policy_client=build_policy_client(policy_requests),
                              dialogue_agent=agent)
    runner = DialogueTurnRunner(manager)
    session = SessionState(session_id=f"evidence-{engine}")

    closed_at: int | None = None
    reason: str | None = None
    for index in range(turns):
        text = f"这是第 {index + 1} 句"
        # 复刻 /api/chat 的落库顺序：先记用户，再跑一轮，最后记助手并计数。
        session.conversation_history.append(
            Message(role=MessageRole.USER, content=text))
        payload = runner.process_turn(text, session)
        session.conversation_history.append(
            Message(role=MessageRole.ASSISTANT, content=payload.reply))
        session.turn_count += 1
        if payload.assessment_ready:
            closed_at = session.turn_count
            reason = payload.completion_reason
            break

    return {
        "decisions": len(policy_requests),
        "replies": agent.reply_calls,
        "turns": session.turn_count,
        "topics": dict(sorted(session.screening_progress.topic_turns.items())),
        "closed_at": closed_at,
        "reason": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=6,
                        help="每段脚本会话最多多少轮（默认 6）")
    args = parser.parse_args()

    if args.turns < 1:
        parser.error("--turns 必须大于0")
    print(f"每段会话最多 {args.turns} 轮；决策目标固定为 {FIXED_DECISION['target_item']}。\n")

    header = "| 模式 | 实际轮数 | 决策模型调用 | 回复生成调用 | 目标回答计数 |"
    print(header)
    print("| --- | --- | --- | --- | --- |")
    results = {}
    for engine in (ENGINE_LEGACY, ENGINE_GRAPH):
        result = run_mode(engine, args.turns)
        results[engine] = result
        topics = "、".join(f"{k} {v}" for k, v in result["topics"].items()) or "（无）"
        print(f"| {engine} | {result['turns']} | {result['decisions']} | "
              f"{result['replies']} | {topics} |")

    assert results[ENGINE_LEGACY] == results[ENGINE_GRAPH]
    expected = min(args.turns, MAX_INTERVIEW_TURNS - 1)
    assert results[ENGINE_LEGACY]["decisions"] == expected
    print()
    print(f"PASS：两种执行路径一致；普通轮每轮决策，上限第{MAX_INTERVIEW_TURNS}轮直接收尾。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
