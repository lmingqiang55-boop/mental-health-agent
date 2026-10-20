"""第 25 轮提醒、第 35 轮收尾在两条执行路径上的边界回归。"""

import json

import pytest
from fastapi.testclient import TestClient
from conftest import create_consented_session

from backend.core.screening_flow import (
    TOPICS, coverage_reminder, record_answer, should_force_decision,
)
from backend.core.session_manager import session_manager
from backend.graph.engine import DIALOGUE_ENGINE_ENV, ENGINE_GRAPH, ENGINE_LEGACY
from backend.main import app
from backend.models.states import SessionState
from backend.prompts.dialogue_prompt import build_dialogue_user_prompt

client = TestClient(app)


@pytest.mark.parametrize("engine", [ENGINE_GRAPH, ENGINE_LEGACY])
@pytest.mark.parametrize("current_turn", [20, 24, 25, 34, 35])
def test_turn_budget_reaches_both_models_and_closes_at_35(
        monkeypatch, policy_stub, dialogue_stub, engine, current_turn):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, engine)
    requests = []
    policy_stub(("睡眠",), requests=requests)
    sid = create_consented_session(client)

    def seed(state):
        state.turn_count = current_turn - 1
        state.screening_progress.topic_turns = {"睡眠": 1}
        state.screening_progress.active_topic = "睡眠"
        state.screening_progress.active_actions = ["睡眠"]

    session_manager.modify_session(sid, seed)
    response = client.post("/api/chat", json={"session_id": sid, "text": "白天还好"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["turn_count"] == current_turn
    request = dialogue_stub.requests[-1]

    if current_turn == 35:
        assert body["assessment_ready"] is True
        assert body["completion_reason"] == "turn_limit"
        assert request.finish_screening is True
        assert "【后端话题补充要求】" not in build_dialogue_user_prompt(request)
        assert requests == [], "强制收尾不再决策或提问"
        assert client.post("/api/chat", json={
            "session_id": sid, "text": "还想再说一句"}).status_code == 409
        return

    assert body["assessment_ready"] is False
    assert request.finish_screening is False
    policy_prompt = json.loads(requests[-1].content)["messages"][1]["content"]
    dialogue_prompt = build_dialogue_user_prompt(request)
    for prompt in (policy_prompt, dialogue_prompt):
        if current_turn < 25:
            assert "【后端话题补充要求】" not in prompt
        else:
            assert "【后端话题补充要求】" in prompt
            assert f"当前是第 {current_turn} 轮" in prompt
            assert "第 35 轮必须结束" in prompt
            missing = [topic.value for topic in TOPICS if topic.value != "睡眠"]
            assert f"尚未涉及的话题：{'、'.join(missing)}。" in prompt


def test_reminder_uses_the_latest_answer_and_stops_when_topics_are_covered():
    session = SessionState(session_id="latest-coverage", turn_count=24)
    session.screening_progress.topic_turns = {
        topic.value: 1 for topic in TOPICS if topic.value != "食欲"
    }
    assert "尚未涉及的话题：食欲。" in coverage_reminder(session)
    session.screening_progress.pending_topic = "食欲"
    record_answer(session)
    assert coverage_reminder(session) is None


@pytest.mark.parametrize("engine", [ENGINE_GRAPH, ENGINE_LEGACY])
def test_user_can_end_during_the_reminder_phase_without_a_catch_up_request(
        monkeypatch, policy_stub, dialogue_stub, engine):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, engine)
    requests = []
    policy_stub(requests=requests)
    sid = create_consented_session(client)
    session_manager.modify_session(sid, lambda state: setattr(state, "turn_count", 24))
    response = client.post("/api/chat", json={"session_id": sid, "text": "结束对话"})
    assert response.json()["completion_reason"] == "user_requested"
    assert requests == []
    assert "【后端话题补充要求】" not in build_dialogue_user_prompt(dialogue_stub.requests[-1])


@pytest.mark.parametrize("completed_turns, expected", [(23, None), (24, "coverage_lag")])
def test_reminder_phase_cannot_skip_the_policy_model(completed_turns, expected):
    session = SessionState(session_id="route-budget", turn_count=completed_turns)
    session.screening_progress.active_topic = "睡眠"
    session.screening_progress.active_actions = ["睡眠"]
    assert should_force_decision(session) == expected


def test_imported_dialogue_checks_safety_through_the_35th_turn(monkeypatch, safety_stub):
    from importlib import import_module
    from evaluation_agent.inputs import EvaluationInput
    from backend.safety.schemas import SafetyLevel

    module = import_module("backend.core.evaluation_engine")

    def evaluate(text, history):
        safety_stub.force(SafetyLevel.HIGH if text == "第35次表达" else SafetyLevel.NORMAL)
        return safety_stub.evaluate(text, history)

    monkeypatch.setattr(module, "evaluate_safety", evaluate)
    messages = []
    for index in range(1, 36):
        messages.extend([
            {"role": "assistant", "content": "请继续说"},
            {"role": "user", "content": f"第{index}次表达"},
        ])
    verdicts = module._screen_user_messages(EvaluationInput(dialogue_history=messages))
    assert len(verdicts) == 35
    assert verdicts[-1].risk_level is SafetyLevel.HIGH
