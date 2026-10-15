# -*- coding: utf-8 -*-
"""对照实验：legacy 与 graph 两种调度下，决策模型被调用了多少次。

这是 Phase 2 的**调度层证据**，回答一个很窄的问题：
"Dialogue 主控之后，决策模型还会不会被每一轮都调用？"

它**不**回答"对话质量更好还是更差"——那需要跑真实模型并做过人工评估。
本脚本把两个模型都换成离线桩，只驱动真实的图与真实的 DialogueManager。

运行::

    python scripts/compare_decision_budget.py            # 6 轮 / 12 轮各跑一遍
    python scripts/compare_decision_budget.py --turns 20

桩的行为刻意固定成：

- 决策模型**永远**返回 ``["共情安慰", "睡眠"]``——话题能否切换完全取决于
  后端的次数约束，与模型无关；
- 路由桩按模式返回固定结论。

三种模式：

======================  ====================================================
``legacy``              迁移前行为：每轮都调决策模型，没有路由这一步
``graph / 每轮要新策略`` Dialogue 每轮都回答"需要"——用来证明图在
                        "总是要决策"时与 legacy **逐轮等价**
``graph / 按需``        Dialogue 自主判断，只在必要时才要新策略（Phase 2 的目标）
======================  ====================================================
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
from backend.models.dialogue import (  # noqa: E402
    DialogueAgentResponse, DialogueRouteDecision,
)
from backend.models.enums import MessageRole  # noqa: E402
from backend.models.states import Message, SessionState  # noqa: E402
from backend.policy.client import HttpPolicyClient  # noqa: E402

#: 决策模型固定返回的动作：话题一直是睡眠。
FIXED_ACTIONS = ["共情安慰", "睡眠"]

MODE_LEGACY = "legacy"
MODE_GRAPH_ALL = "graph / 每轮要新策略"
MODE_GRAPH_AUTO = "graph / 按需"

MODES = (
    (MODE_LEGACY, ENGINE_LEGACY, None),
    (MODE_GRAPH_ALL, ENGINE_GRAPH, True),
    (MODE_GRAPH_AUTO, ENGINE_GRAPH, False),
)


class DialogueStub:
    """离线对话 Agent：记录调用次数，不碰网络。"""

    def __init__(self, route_need_decision: bool | None) -> None:
        self.route_need_decision = route_need_decision
        self.route_calls = 0
        self.reply_calls = 0

    async def route(self, request) -> DialogueRouteDecision:
        self.route_calls += 1
        return DialogueRouteDecision(
            need_decision=bool(self.route_need_decision),
            reason_code="topic_exhausted" if self.route_need_decision else "continue_topic",
            reason="对照实验桩",
        )

    async def generate_reply(self, request) -> DialogueAgentResponse:
        self.reply_calls += 1
        topic = request.decision.topic or "现在的感受"
        return DialogueAgentResponse(
            reply=f"听起来你在说这件事。我们继续聊聊{topic}。")


def build_policy_client(counter: list) -> HttpPolicyClient:
    """决策模型桩：每次都返回同一组动作，并把请求记进 counter。"""

    def handle(request: httpx.Request) -> httpx.Response:
        counter.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(
                {"actions": FIXED_ACTIONS}, ensure_ascii=False)}}]})

    return HttpPolicyClient(client=httpx.Client(transport=httpx.MockTransport(handle)))


def run_mode(engine: str, route_need_decision: bool | None,
             turns: int) -> dict:
    """跑一整段脚本会话，返回各模型的调用次数。"""
    os.environ[DIALOGUE_ENGINE_ENV] = engine
    policy_requests: list = []
    agent = DialogueStub(route_need_decision)
    manager = DialogueManager(policy_client=build_policy_client(policy_requests),
                              dialogue_agent=agent)
    runner = DialogueTurnRunner(manager)
    session = SessionState(session_id=f"evidence-{engine}-{route_need_decision}")

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
        "routes": agent.route_calls,
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

    for label, engine, need in MODES:
        if need is not None and engine == ENGINE_LEGACY:
            continue
    print(f"每段会话最多 {args.turns} 轮；决策模型固定返回 {FIXED_ACTIONS}。\n")

    header = "| 模式 | 实际轮数 | 决策模型调用 | 路由模型调用 | 回复生成调用 | 话题计数 |"
    print(header)
    print("| --- | --- | --- | --- | --- | --- |")
    results = {}
    for label, engine, need in MODES:
        result = run_mode(engine, need, args.turns)
        results[label] = result
        topics = "、".join(f"{k} {v}" for k, v in result["topics"].items()) or "（无）"
        print(f"| {label} | {result['turns']} | {result['decisions']} | "
              f"{result['routes']} | {result['replies']} | {topics} |")

    legacy = results[MODE_LEGACY]["decisions"]
    auto = results[MODE_GRAPH_AUTO]["decisions"]
    same = results[MODE_GRAPH_ALL]["decisions"]
    print()
    print(f"- legacy / 每轮要新策略 的决策次数是否一致："
          f"{'是' if legacy == same else '否'}（{legacy} vs {same}）")
    print(f"- 按需决策相对 legacy 减少：{legacy} → {auto}"
          f"（少 {legacy - auto} 次，约 {round((legacy - auto) / legacy * 100)}%）")
    print()
    print("注意：以上是**离线桩上的调度次数**，只证明图的分支逻辑；")
    print("      真实模型下的对话质量与延迟需要用真模型实验，本脚本不下这个结论。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
