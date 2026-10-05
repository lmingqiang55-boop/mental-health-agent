"""Speech metadata survives chat retries and the existing evaluation boundary."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
SPEECH = {"capture_id": "capture-1", "recording_start_ms": 12000,
          "recording_end_ms": 16800}


def new_request():
    return {"session_id": client.post("/api/session").json()["session_id"],
            "utterance_id": "utterance-1", "text": "最近晚上经常睡不着",
            "speech": deepcopy(SPEECH)}


def test_retry_returns_original_response_after_later_turn(policy_stub):
    calls = []
    policy_stub(requests=calls)
    request = new_request()
    request["vision_snapshot"] = {"face_detected": True, "valence": -0.4}
    first = client.post("/api/chat", json=request)
    assert first.status_code == 200
    client.post("/api/chat", json={"session_id": request["session_id"], "text": "没有"})
    retry = client.post("/api/chat", json=request)
    assert retry.json() == first.json()
    assert len(calls) == 2
    session = client.get(f"/api/session/{request['session_id']}").json()
    assert session["turn_count"] == 2
    assert len(session["conversation_history"]) == 5
    assert "chat_receipts" not in session
    message = session["conversation_history"][1]
    assert message["utterance_id"] == "utterance-1"
    assert message["speech"] == SPEECH
    assert session["conversation_history"][2]["speech"] is None


@pytest.mark.parametrize("change", ["text", "speech", "vision_snapshot"])
def test_changed_retry_conflicts_without_new_turn(policy_stub, change):
    policy_stub()
    request = new_request()
    assert client.post("/api/chat", json=request).status_code == 200
    altered = deepcopy(request)
    if change == "text":
        altered["text"] = "睡得很好"
    elif change == "speech":
        altered["speech"]["recording_end_ms"] += 1
    else:
        altered["vision_snapshot"] = {"face_detected": False}
    response = client.post("/api/chat", json=altered)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "UTTERANCE_CONFLICT"
    assert client.get(f"/api/session/{request['session_id']}").json()["turn_count"] == 1


def test_simultaneous_retry_only_calls_policy_once(policy_stub):
    calls = []
    policy_stub(requests=calls)
    request = new_request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/api/chat", json=request), range(2)))
    assert all(item.status_code == 200 for item in responses)
    assert responses[0].json() == responses[1].json()
    assert len(calls) == 1


def test_policy_failure_can_retry_same_speech_id(policy_stub):
    policy_stub(status_code=503)
    request = new_request()
    failed = client.post("/api/chat", json=request)
    assert failed.status_code == 503
    before = client.get(f"/api/session/{request['session_id']}").json()
    assert before["turn_count"] == 0 and len(before["conversation_history"]) == 1
    policy_stub()
    assert client.post("/api/chat", json=request).status_code == 200
    assert client.get(f"/api/session/{request['session_id']}").json()["turn_count"] == 1


def test_speech_missing_modalities_do_not_use_stale_states(policy_stub):
    policy_stub()
    request = new_request()
    client.post("/api/vision", json={"session_id": request["session_id"], "state": {
        "face_detected": True, "valence": -0.9, "engagement": 0.01}})
    client.post("/api/audio", json={"session_id": request["session_id"], "state": {
        "energy": 0.01, "pause_ratio": 0.99, "audio_available": True}})
    response = client.post("/api/chat", json=request)
    assert response.status_code == 200
    assert response.json()["risk"]["risk_level"] == "low"
    message = client.get(f"/api/session/{request['session_id']}").json()["conversation_history"][1]
    assert message["vision_snapshot"] is None and message["audio_snapshot"] is None


@pytest.mark.parametrize("speech", [
    {**SPEECH, "recording_end_ms": 12000},
    {**SPEECH, "recording_start_ms": -1},
    {**SPEECH, "recording_start_ms": "NaN"},
    {**SPEECH, "recording_end_ms": "Infinity"},
    {**SPEECH, "capture_id": " "},
    {**SPEECH, "unexpected": True},
])
def test_invalid_recording_metadata_rejected(speech):
    request = new_request()
    request["speech"] = speech
    assert client.post("/api/chat", json=request).status_code == 422


def test_speech_requires_utterance_id():
    request = new_request()
    request.pop("utterance_id")
    assert client.post("/api/chat", json=request).status_code == 422


@pytest.mark.parametrize("full_input", [False, True])
def test_assessment_keeps_original_recording_metadata(
        policy_stub, evaluation_stub, full_input):
    policy_stub()
    request = new_request()
    first = client.post("/api/chat", json=request)
    before = client.get(f"/api/session/{request['session_id']}").json()
    body = {"session_id": request["session_id"]}
    if full_input:
        # Frontend can send only evaluation fields; backend retains authoritative metadata.
        body["evaluation_input"] = {"dialogue_history": [
            {"role": item["role"], "content": item["content"]}
            for item in before["conversation_history"]]}
    assert client.post("/api/assessment", json=body).status_code == 200
    after = client.get(f"/api/session/{request['session_id']}").json()
    assert after["conversation_history"] == before["conversation_history"]
    assert client.post("/api/chat", json=request).json() == first.json()


def test_changed_full_assessment_does_not_destroy_speech(policy_stub, evaluation_stub):
    policy_stub()
    request = new_request()
    client.post("/api/chat", json=request)
    before = client.get(f"/api/session/{request['session_id']}").json()
    response = client.post("/api/assessment", json={"session_id": request["session_id"],
        "evaluation_input": {"dialogue_history": [{"role": "user", "content": "改写内容"}]}})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "HISTORY_CONFLICT"
    assert evaluation_stub.inputs == []
    assert client.get(f"/api/session/{request['session_id']}").json() == before


def test_external_assessment_preserves_supplied_speech(evaluation_stub):
    session_id = client.post("/api/session").json()["session_id"]
    original_time = "2026-10-02T01:00:00Z"
    response = client.post("/api/assessment", json={"session_id": session_id,
        "evaluation_input": {"dialogue_history": [{"role": "user", "content": "没有",
            "utterance_id": "external-1", "speech": SPEECH, "created_at": original_time}]}})
    assert response.status_code == 200, response.json()
    message = client.get(f"/api/session/{session_id}").json()["conversation_history"][0]
    assert message["speech"] == SPEECH and message["utterance_id"] == "external-1"
    assert message["created_at"].replace("+00:00", "Z") == original_time
    response = client.post("/api/chat", json={"session_id": session_id, "text": "没有",
                                            "utterance_id": "external-1"})
    assert response.status_code == 409


def test_assessment_cannot_reassign_recording_id(policy_stub, evaluation_stub):
    policy_stub()
    request = new_request()
    client.post("/api/chat", json=request)
    history = client.get(f"/api/session/{request['session_id']}").json()["conversation_history"]
    history[1]["utterance_id"] = "wrong-id"
    response = client.post("/api/assessment", json={"session_id": request["session_id"],
        "evaluation_input": {"dialogue_history": history}})
    assert response.status_code == 409
    assert evaluation_stub.inputs == []


@pytest.mark.parametrize("full_input", [False, True])
def test_assessment_does_not_overwrite_concurrent_chat(policy_stub, evaluation_stub, monkeypatch, full_input):
    policy_stub()
    request = new_request()
    client.post("/api/chat", json=request)
    history = client.get(f"/api/session/{request['session_id']}").json()["conversation_history"]
    evaluate = evaluation_stub.evaluate
    def during_model(data):
        result = evaluate(data)
        assert client.post("/api/chat", json={"session_id": request["session_id"],
                                             "text": "还有点累"}).status_code == 200
        return result
    monkeypatch.setattr(evaluation_stub, "evaluate", during_model)
    body = {"session_id": request["session_id"]}
    if full_input:
        body["evaluation_input"] = {"dialogue_history": history}
    response = client.post("/api/assessment", json=body)
    assert response.status_code == 409
    state = client.get(f"/api/session/{request['session_id']}").json()
    assert len(state["conversation_history"]) == 5
    assert state["assessment_result_id"] is None
