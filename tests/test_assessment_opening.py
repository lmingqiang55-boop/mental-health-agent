"""The fixed introduction and first answer become persisted assessment demographics."""

from fastapi.testclient import TestClient

from backend.main import app
from evaluation_agent.opening import OPENING_QUESTION


client = TestClient(app)


def test_opening_answer_is_used_in_assessment_and_history(policy_stub, evaluation_stub):
    policy_stub()
    created = client.post("/api/session").json()
    session_id = created["session_id"]
    assert created["opening_message"] == OPENING_QUESTION
    session = client.get(f"/api/session/{session_id}").json()
    assert session["turn_count"] == 0
    assert len(session["conversation_history"]) == 1
    assert session["conversation_history"][0]["role"] == "assistant"
    assert session["conversation_history"][0]["content"] == OPENING_QUESTION

    chat = client.post("/api/chat", json={
        "session_id": session_id,
        "text": "我今年12岁，上初一，最近总觉得压力很大。",
    })
    assert chat.status_code == 200, chat.json()
    assert chat.json()["turn_count"] == 1

    response = client.post("/api/assessment", json={"session_id": session_id})
    assert response.status_code == 200, response.json()
    result = response.json()["result"]
    assert result["age"] == 12
    assert result["grade"] == "初一"
    assert evaluation_stub.inputs[0].dialogue_history[0].content == OPENING_QUESTION
    assert evaluation_stub.inputs[0].dialogue_history[1].content.startswith("我今年12岁")

    saved = client.get(f"/api/assessment/result/{result['result_id']}", params={
        "session_id": session_id,
    })
    assert saved.status_code == 200
    assert saved.json()["result"]["age"] == 12
    assert saved.json()["result"]["grade"] == "初一"


def test_opening_alone_cannot_be_assessed(evaluation_stub):
    session_id = client.post("/api/session").json()["session_id"]
    response = client.post("/api/assessment", json={"session_id": session_id})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_EVALUATION_INPUT"
    assert not evaluation_stub.inputs
