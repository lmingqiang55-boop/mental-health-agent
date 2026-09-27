from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def new_session() -> str:
    return client.post("/api/session").json()["session_id"]


def test_chat_without_multimodal_or_api_key() -> None:
    session_id = new_session()
    first = client.post("/api/chat", json={
        "session_id": session_id, "text": "最近总是觉得没什么精神"
    })
    assert first.status_code == 200
    body = first.json()
    assert body["reply"]
    assert body["next_strategy"]
    assert body["risk"]["risk_level"] == "low"
    assert body["turn_count"] == 1

    second = client.post("/api/chat", json={
        "session_id": session_id, "text": "我晚上常常睡不着"
    })
    assert second.status_code == 200
    assert second.json()["turn_count"] == 2

    session = client.get(f"/api/session/{session_id}").json()
    assert len(session["conversation_history"]) == 4
    assert session["latest_vision_state"] is None
    assert session["latest_audio_state"] is None


def test_multimodal_state_is_saved_and_chat_still_works() -> None:
    session_id = new_session()
    vision = client.post("/api/vision", json={
        "session_id": session_id, "emotion": "sad", "emotion_confidence": 0.8,
        "face_detected": True,
    })
    audio = client.post("/api/audio", json={
        "session_id": session_id, "energy": 0.4, "audio_available": True,
    })
    assert vision.status_code == 200
    assert audio.status_code == 200
    assert client.post("/api/chat", json={
        "session_id": session_id, "text": "最近心情不好"
    }).status_code == 200
    session = client.get(f"/api/session/{session_id}").json()
    assert session["latest_vision_state"]["emotion"] == "sad"
    assert session["latest_audio_state"]["energy"] == 0.4


def test_unknown_session_and_invalid_text() -> None:
    missing = client.post("/api/chat", json={
        "session_id": "bad", "text": "hello"
    })
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SESSION_NOT_FOUND"

    invalid = client.post("/api/chat", json={
        "session_id": new_session(), "text": "   "
    })
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


def test_covered_dimensions_are_not_repeated() -> None:
    session_id = new_session()
    strategies = []
    for answer in ("我还好", "还愿意做", "睡得还行", "精力正常", "能集中", "两个星期", "谢谢"):
        response = client.post("/api/chat", json={"session_id": session_id, "text": answer})
        assert response.status_code == 200
        strategies.append(response.json()["next_strategy"])
    assert strategies[:6] == [
        "explore_mood", "explore_interest", "explore_sleep", "explore_energy",
        "explore_concentration", "explore_duration",
    ]
    assert strategies[6] == "finish_assessment"


def test_high_risk_message_gets_supportive_reply() -> None:
    session_id = new_session()
    response = client.post("/api/chat", json={
        "session_id": session_id, "text": "我想自杀"
    })
    assert response.status_code == 200
    assert response.json()["risk"]["requires_intervention"] is True
    assert "急救" in response.json()["reply"]
