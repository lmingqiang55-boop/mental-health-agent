from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def new_session() -> str:
    return client.post("/api/session").json()["session_id"]


def test_chat_without_multimodal_or_api_key() -> None:
    session_id = new_session()
    first = client.post("/api/chat", json={
        "session_id": session_id, "text": "最近总是觉得压力很大"
    })
    assert first.status_code == 200
    body = first.json()
    assert body["reply"]
    assert body["next_strategy"]
    assert body["risk"]["risk_level"] == "low"
    assert body["turn_count"] == 1

    second = client.post("/api/chat", json={
        "session_id": session_id, "text": "晚上常常睡不着"
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
        "session_id": session_id,
        "state": {"emotion": "sad", "emotion_confidence": 0.8,
                  "face_detected": True},
    })
    audio = client.post("/api/audio", json={
        "session_id": session_id,
        "state": {"energy": 0.4, "audio_available": True},
    })
    assert vision.status_code == 200
    assert audio.status_code == 200
    assert client.post("/api/chat", json={
        "session_id": session_id, "text": "最近心情不好"
    }).status_code == 200
    session = client.get(f"/api/session/{session_id}").json()
    assert session["latest_vision_state"]["emotion"] == "sad"
    assert session["latest_audio_state"]["energy"] == 0.4


def test_vision_merge_does_not_reset_other_fields() -> None:
    session_id = new_session()
    client.post("/api/vision", json={
        "session_id": session_id,
        "state": {"emotion": "sad", "valence": -0.4, "face_detected": True},
    })
    # 第二次只传 engagement，其他字段应保留
    client.post("/api/vision", json={
        "session_id": session_id,
        "state": {"engagement": 0.7, "face_detected": True},
    })
    session = client.get(f"/api/session/{session_id}").json()
    state = session["latest_vision_state"]
    assert state["emotion"] == "sad"
    assert state["valence"] == -0.4
    assert state["engagement"] == 0.7


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
    answers = (
        "我想说说最近的情况",
        "这个问题我想一下",
        "让我考虑一下怎么说",
        "这个有点难回答但是我试试",
        "我尽量描述一下",
        "我回忆一下时间",
        "好的我知道了",
    )
    strategies = []
    for answer in answers:
        response = client.post("/api/chat",
                               json={"session_id": session_id, "text": answer})
        assert response.status_code == 200
        strategies.append(response.json()["next_strategy"])
    assert strategies[:6] == [
        "explore_mood", "explore_pressure", "explore_interpersonal",
        "explore_self_cognition", "explore_study_life", "explore_duration",
    ]
    assert strategies[6] == "finish_assessment"


def test_clarify_has_a_limit_and_then_advances() -> None:
    session_id = new_session()
    # 第一轮先进入 mood
    client.post("/api/chat", json={
        "session_id": session_id, "text": "我想做筛查"})
    # 连续模糊回答：前两次 clarify，第三次强制推进到 pressure
    strategies = []
    for vague in ("嗯", "哦", "不知道"):
        r = client.post("/api/chat", json={
            "session_id": session_id, "text": vague})
        strategies.append(r.json()["next_strategy"])
    assert strategies[0] == "clarify_answer"
    assert strategies[1] == "clarify_answer"
    assert strategies[2] == "explore_pressure"


def test_high_risk_message_enters_crisis_mode() -> None:
    session_id = new_session()
    response = client.post("/api/chat", json={
        "session_id": session_id, "text": "我想自杀"
    })
    assert response.status_code == 200
    body = response.json()
    assert body["risk"]["requires_intervention"] is True
    assert body["current_stage"] == "crisis"
    assert "急救" in body["reply"]

    # 危机模式后继续发消息，不推进评估维度
    follow = client.post("/api/chat", json={
        "session_id": session_id, "text": "我真的很难受"
    })
    assert follow.json()["current_stage"] == "crisis"


def test_negation_does_not_trigger_high_risk() -> None:
    session_id = new_session()
    response = client.post("/api/chat", json={
        "session_id": session_id, "text": "我不想自杀，我只是有点难过"
    })
    assert response.json()["risk"]["risk_level"] != "high"


def test_finish_assessment_generates_stored_result() -> None:
    session_id = new_session()
    answers = (
        "我想说说最近的情况",
        "这个问题我想一下",
        "让我考虑一下怎么说",
        "这个有点难回答但是我试试",
        "我尽量描述一下",
        "我回忆一下时间",
        "持续两个星期了",
    )
    last = None
    for answer in answers:
        last = client.post("/api/chat",
                           json={"session_id": session_id, "text": answer})
    assert last.json()["next_strategy"] == "finish_assessment"

    session = client.get(f"/api/session/{session_id}").json()
    assert session["assessment_result_id"]
    assert session["vision_summary"] is not None
    assert session["audio_summary"] is not None

    # 记忆库可查到记录
    history = client.get(f"/api/history/{session_id}").json()
    assert history["total"] == 1
