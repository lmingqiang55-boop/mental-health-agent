"""35轮硬上限、主动结束和历史安全补判；不按回答次数提前结束。"""

import pytest
from fastapi.testclient import TestClient
from conftest import create_consented_session

from backend.core.screening_flow import MAX_TURNS, completion_reason, record_answer
from backend.core.session_manager import session_manager
from backend.main import app
from backend.models.states import SessionState
from backend.prompts.dialogue_prompt import build_dialogue_user_prompt
from evaluation_agent.schemas import ITEM_KEYS

client = TestClient(app)


@pytest.mark.parametrize("engine", ["graph", "legacy"])
@pytest.mark.parametrize("current_turn", [1, 25, 34, 35])
@pytest.mark.parametrize("covered", [False, True])
def test_hard_limit_with_no_catch_up_reminder(
        monkeypatch, policy_stub, dialogue_stub, engine, current_turn, covered):
    monkeypatch.setenv("DIALOGUE_ENGINE", engine)
    requests = []
    policy_stub("sleep_disturbance", requests=requests)
    sid = create_consented_session(client)

    def seed(state):
        state.turn_count = current_turn - 1
        state.screening_progress.topic_turns = {item: 1 for item in ITEM_KEYS} if covered else {}

    session_manager.modify_session(sid, seed)
    response = client.post("/api/chat", json={"session_id": sid, "text": "最近还是这样"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert MAX_TURNS == 35
    assert body["turn_count"] == current_turn
    assert body["assessment_ready"] is (current_turn == 35)
    assert body["completion_reason"] == ("turn_limit" if current_turn == 35 else None)
    assert dialogue_stub.requests[-1].finish_screening is (current_turn == 35)
    assert len(requests) == (0 if current_turn == 35 else 1)
    assert "【后端话题补充要求】" not in build_dialogue_user_prompt(dialogue_stub.requests[-1])


@pytest.mark.parametrize("engine", ["graph", "legacy"])
def test_premature_model_finish_collects_each_item_before_ending(
        monkeypatch, policy_stub, dialogue_stub, engine):
    monkeypatch.setenv("DIALOGUE_ENGINE", engine)
    requests = []
    policy_stub(None, question_goal="结束访谈", requests=requests)
    sid = create_consented_session(client)

    for index, item in enumerate(ITEM_KEYS):
        text = "我13岁了，初一" if index == 0 else "这两周没有这种变化。"
        request = {"session_id": sid, "text": text, "utterance_id": f"answer-{index}"}
        response = client.post("/api/chat", json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert not body["assessment_ready"]
        assert body["completion_reason"] is None
        assert body["screening_progress"]["pending_topic"] == item
        assert body["screening_progress"]["topic_turns"] == {
            previous: 1 for previous in ITEM_KEYS[:index]}
        assert dialogue_stub.requests[-1].decision.target_item == item
        assert not dialogue_stub.requests[-1].finish_screening
        # 重试回执不多记一次回答，也不会触发第二次模型调用。
        assert client.post("/api/chat", json=request).json() == body
        assert len(requests) == index + 1

    # 第11个话题问出但尚未回复时，仍然不允许收尾；最后一个回复才补齐覆盖。
    response = client.post("/api/chat", json={"session_id": sid, "text": "这两周也没有这方面的困难。"})
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["assessment_ready"]
    assert body["completion_reason"] == "model_finished"
    assert body["turn_count"] == len(ITEM_KEYS) + 1
    assert body["screening_progress"]["topic_turns"] == {item: 1 for item in ITEM_KEYS}
    assert body["screening_progress"]["pending_topic"] is None
    assert dialogue_stub.requests[-1].finish_screening
    assert len(requests) == len(ITEM_KEYS) + 1


@pytest.mark.parametrize("current_turn", [1, 10, 25, 35])
def test_explicit_end_without_minimum(current_turn):
    session = SessionState(session_id="end", turn_count=current_turn - 1)
    assert completion_reason(session, "结束对话") == "user_requested"
    assert completion_reason(session, "不要结束对话") == (
        "turn_limit" if current_turn == 35 else None)


def test_answer_count_is_consumed_once_and_does_not_measure_evidence():
    session = SessionState(session_id="count")
    session.screening_progress.pending_topic = "sleep_disturbance"
    record_answer(session)
    record_answer(session)
    assert session.screening_progress.topic_turns == {"sleep_disturbance": 1}
    assert session.screening_progress.pending_topic is None


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
