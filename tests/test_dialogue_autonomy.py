"""每轮决策、精确目标传递、模型结束，以及失败时的事务边界。"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from conftest import create_consented_session

from backend.api import chat
from backend.agents.dialogue_agent import DialogueAgentError
from backend.core.session_manager import session_manager
from backend.main import app
from backend.policy.client import HttpPolicyClient
from backend.prompts.dialogue_prompt import build_dialogue_user_prompt
from backend.safety.schemas import SafetyLevel
from evaluation_agent.schemas import ITEM_KEYS

client = TestClient(app)


@pytest.fixture(params=["legacy", "graph"], autouse=True)
def engine(request, monkeypatch):
    monkeypatch.setenv("DIALOGUE_ENGINE", request.param)
    return request.param


def send(sid, text="最近还是这样", **extra):
    return client.post("/api/chat", json={"session_id": sid, "text": text, **extra})


def seed_covered_items(sid):
    session_manager.modify_session(sid, lambda state: state.screening_progress.topic_turns.update(
        {item: 1 for item in ITEM_KEYS}))


@pytest.mark.parametrize("item", ITEM_KEYS)
def test_exact_item_and_goal_reach_dialogue(item, policy_stub, dialogue_stub):
    goal = "学生已描述相关变化，本轮只补充过去两周的出现频率"
    requests = []
    policy_stub(item, question_goal=goal, requests=requests)
    sid = create_consented_session(client)
    response = send(sid)
    assert response.status_code == 200, response.text
    decision = dialogue_stub.requests[-1].decision
    assert decision.model_dump() == {"target_item": item, "question_goal": goal}
    prompt = build_dialogue_user_prompt(dialogue_stub.requests[-1])
    assert item in prompt and goal in prompt
    assert len(requests) == 1


def test_each_round_gets_fresh_goal_without_router_or_topic_limit(
        monkeypatch, dialogue_stub, safety_stub):
    payloads = []

    def handle(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "target_item": "sleep_disturbance",
            "question_goal": f"补充第{len(payloads)}个尚缺的信息点",
        }, ensure_ascii=False)}}]})

    monkeypatch.setattr(chat.dialogue_manager, "_policy", HttpPolicyClient(
        client=httpx.Client(transport=httpx.MockTransport(handle))))
    sid = create_consented_session(client)
    for index in range(1, 6):
        response = send(sid, f"第{index}次回答")
        assert response.status_code == 200, response.text
        decision = dialogue_stub.requests[-1].decision
        assert decision.target_item == "sleep_disturbance"
        assert decision.question_goal == f"补充第{index}个尚缺的信息点"
        assert f"当前为第 {index} 轮" in payloads[-1]["messages"][1]["content"]
    assert len(payloads) == len(safety_stub.calls) == 5
    assert dialogue_stub.route_requests == []
    progress = response.json()["screening_progress"]
    assert progress["topic_turns"] == {"sleep_disturbance": 4}


@pytest.mark.parametrize("completed_turns", [11, 20, 33])
def test_model_can_end_and_replay_does_not_decide_again(
        completed_turns, policy_stub, dialogue_stub):
    requests = []
    policy_stub(None, question_goal="结束访谈", requests=requests)
    sid = create_consented_session(client)
    session_manager.modify_session(sid, lambda state: setattr(state, "turn_count", completed_turns))
    seed_covered_items(sid)
    response = send(sid, utterance_id="finish")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assessment_ready"] is True
    assert body["completion_reason"] == "model_finished"
    assert body["current_stage"] == "assessment_ready"
    assert body["screening_progress"]["pending_topic"] is None
    assert dialogue_stub.requests[-1].finish_screening is True
    assert dialogue_stub.requests[-1].decision.model_dump() == {
        "target_item": None, "question_goal": "结束访谈"}
    assert send(sid, utterance_id="finish").json() == body
    assert len(requests) == 1
    assert send(sid, "继续普通访谈").status_code == 409


def test_safety_preempts_even_a_model_ended_session(policy_stub, safety_stub):
    requests = []
    policy_stub(None, question_goal="结束访谈", requests=requests)
    sid = create_consented_session(client)
    seed_covered_items(sid)
    assert send(sid).json()["completion_reason"] == "model_finished"
    safety_stub.force(SafetyLevel.HIGH)
    response = send(sid, "我现在想伤害自己")
    assert response.status_code == 200
    assert response.json()["current_stage"] == "safety_stop"
    assert response.json()["assessment_ready"] is False
    assert len(requests) == 1


@pytest.mark.parametrize("content", [
    '{"actions":["睡眠"]}',
    '{"target_item":null,"question_goal":"再问睡眠"}',
    '{"target_item":"sleep_disturbance","question_goal":"结束访谈"}',
    '{"target_item":"unknown","question_goal":"了解情况"}',
])
def test_invalid_decision_rolls_back_whole_turn(content, monkeypatch, policy_stub):
    policy_stub("sleep_disturbance")
    sid = create_consented_session(client)
    assert send(sid).status_code == 200
    before = session_manager.get_session(sid)
    monkeypatch.setattr(chat.dialogue_manager, "_policy", HttpPolicyClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]})))))
    response = send(sid, "新的回答", utterance_id="invalid")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "POLICY_UNAVAILABLE"
    assert session_manager.get_session(sid) == before


def test_failed_model_closing_can_retry_without_partial_state(
        monkeypatch, policy_stub, dialogue_stub):
    sid = create_consented_session(client)
    seed_covered_items(sid)
    before = session_manager.get_session(sid)
    policy_stub(None, question_goal="结束访谈")
    original = dialogue_stub.generate_reply

    async def fail(request):
        assert request.finish_screening
        raise DialogueAgentError("offline failure")

    monkeypatch.setattr(dialogue_stub, "generate_reply", fail)
    assert send(sid, utterance_id="retry").status_code == 503
    assert session_manager.get_session(sid) == before
    monkeypatch.setattr(dialogue_stub, "generate_reply", original)
    assert send(sid, utterance_id="retry").json()["completion_reason"] == "model_finished"


def test_model_ended_interview_can_generate_assessment(policy_stub, evaluation_stub, monkeypatch):
    saved = []
    monkeypatch.setattr("backend.api.assessment.memory_store.save_result", saved.append)
    sid = create_consented_session(client)
    policy_stub("sleep_disturbance", question_goal="了解入睡困难的持续时间")
    assert send(sid, "最近两周晚上经常睡不着").status_code == 200
    seed_covered_items(sid)
    policy_stub(None, question_goal="结束访谈")
    assert send(sid, "一周四晚左右").json()["assessment_ready"] is True
    response = client.post("/api/assessment", json={"session_id": sid})
    assert response.status_code == 200, response.text
    received = evaluation_stub.inputs[-1]
    statements = [message.content for message in received.dialogue_history
                  if message.role.value == "user"]
    assert statements == ["最近两周晚上经常睡不着", "一周四晚左右"]
    assert len(saved) == 1
