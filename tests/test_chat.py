import base64
import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.models.states import VisionState
from backend.vision.detector import MockVisionDetector, VisionDetector, set_detector

client = TestClient(app)


@pytest.fixture(autouse=True)
def _stub_decision_model(policy_stub):
    """本文件的对话用例一律使用模拟的决策模型响应，不启动真实模型。"""
    policy_stub()


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
    assert body["next_strategy"] == "情绪"
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
    # 六维固定提问状态机删除后，这两个公共字段不再存在
    assert "assessment_state" not in session
    assert "clarify_count" not in session


def test_chat_uses_decision_model_actions(policy_stub) -> None:
    """提问方向来自决策模型的动作，而不是按维度固定顺序推进。"""
    policy_stub(("睡眠",))
    session_id = new_session()
    body = client.post("/api/chat", json={
        "session_id": session_id, "text": "我最近总失眠"
    }).json()
    assert body["next_strategy"] == "睡眠"
    assert "睡眠" in body["reply"]
    # 不再出现六维状态机的策略名
    assert not body["next_strategy"].startswith("explore_")


def test_chat_sends_accumulated_history_to_decision_model(policy_stub) -> None:
    requests = []
    policy_stub(("共情安慰", "睡眠"), requests=requests)
    session_id = new_session()
    first = client.post("/api/chat", json={
        "session_id": session_id, "text": "我最近睡不好"})
    client.post("/api/chat", json={"session_id": session_id, "text": "经常凌晨醒"})

    first_prompt = json.loads(requests[0].content)["messages"][1]["content"]
    second_prompt = json.loads(requests[1].content)["messages"][1]["content"]
    assert first_prompt.endswith("用户：我最近睡不好")
    assert second_prompt.endswith(
        f"用户：我最近睡不好\n助手：{first.json()['reply']}\n用户：经常凌晨醒")


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
    assert session["conversation_history"][0]["vision_snapshot"] is None
    assert session["conversation_history"][0]["audio_snapshot"] is None


def test_chat_stores_only_exact_utterance_vision() -> None:
    session_id = new_session()
    response = client.post("/api/chat", json={
        "session_id": session_id,
        "text": "最近心情不好",
        "vision_snapshot": {"face_detected": True, "valence": -0.4},
    })
    assert response.status_code == 200
    message = client.get(f"/api/session/{session_id}").json()["conversation_history"][0]
    assert message["vision_snapshot"]["valence"] == -0.4
    assert message["audio_snapshot"] is None


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


def test_vision_frame_endpoint_uses_detector_and_discards_raw_frame() -> None:
    session_id = new_session()
    image = BytesIO()
    Image.new("RGB", (32, 32), color=(120, 140, 160)).save(image, format="JPEG")

    frame = "data:image/jpeg;base64," + base64.b64encode(image.getvalue()).decode()
    response = client.post("/api/vision/frame", json={
        "session_id": session_id, "image_base64": frame,
    })
    assert response.status_code == 200
    state = response.json()["vision_state"]
    assert state["face_detected"] is True
    session = client.get(f"/api/session/{session_id}").json()
    assert session["latest_vision_state"]["face_detected"] is True
    assert len(session["vision_state_log"]) == 1


def test_vision_frame_endpoint_does_not_merge_a_no_face_snapshot() -> None:
    class SequenceDetector(VisionDetector):
        def __init__(self, states: list[VisionState]) -> None:
            self._states = iter(states)

        def analyze_frame(self, frame=None) -> VisionState:
            return next(self._states)

    session_id = new_session()
    set_detector(SequenceDetector([
        VisionState(
            emotion="sad", emotion_confidence=0.8, valence=-0.4,
            arousal=0.3, engagement=0.7, face_detected=True,
        ),
        VisionState(face_detected=False),
    ]))
    image = BytesIO()
    Image.new("RGB", (32, 32), color=(120, 140, 160)).save(image, format="JPEG")

    frame = base64.b64encode(image.getvalue()).decode()
    try:
        first = client.post("/api/vision/frame", json={
            "session_id": session_id, "image_base64": frame,
        })
        second = client.post("/api/vision/frame", json={
            "session_id": session_id, "image_base64": frame,
        })
    finally:
        set_detector(MockVisionDetector())

    assert first.status_code == 200
    assert second.status_code == 200
    state = second.json()["vision_state"]
    assert state["face_detected"] is False
    assert state["emotion"] is None
    assert state["valence"] is None
    assert state["engagement"] is None


def test_vision_frame_endpoint_rejects_invalid_base64() -> None:
    response = client.post("/api/vision/frame", json={
        "session_id": new_session(), "image_base64": "!" * 40,
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FRAME"


def test_vision_frame_endpoint_rejects_non_image_bytes() -> None:
    response = client.post("/api/vision/frame", json={
        "session_id": new_session(),
        "image_base64": base64.b64encode(b"not-an-image" * 8).decode(),
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FRAME"


def test_vision_frame_endpoint_rejects_oversized_decoded_image() -> None:
    image = BytesIO()
    Image.new("RGB", (1921, 1080), color=(120, 140, 160)).save(image, format="JPEG")
    response = client.post("/api/vision/frame", json={
        "session_id": new_session(),
        "image_base64": base64.b64encode(image.getvalue()).decode(),
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_FRAME"


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

    # 危机模式后继续发消息，仍然只走危机支持话术
    follow = client.post("/api/chat", json={
        "session_id": session_id, "text": "我真的很难受"
    })
    assert follow.json()["current_stage"] == "crisis"
    assert "急救" in follow.json()["reply"]


def test_negation_does_not_trigger_high_risk() -> None:
    session_id = new_session()
    response = client.post("/api/chat", json={
        "session_id": session_id, "text": "我不想自杀，我只是有点难过"
    })
    assert response.json()["risk"]["risk_level"] != "high"


def test_chat_never_finishes_on_its_own_and_assessment_is_explicit(
    evaluation_stub,
) -> None:
    """对话没有结束信号：聊天不生成评估结果，只由 /api/assessment 触发。"""
    session_id = new_session()
    for text in ("我想说说最近的情况", "晚上常常睡不着", "和室友关系也一般"):
        assert client.post("/api/chat", json={
            "session_id": session_id, "text": text}).status_code == 200

    session = client.get(f"/api/session/{session_id}").json()
    assert session["assessment_result_id"] is None
    assert session["current_stage"] == "exploration"
    assert session["vision_summary"] is None
    assert session["audio_summary"] is None

    triggered = client.post("/api/assessment", json={"session_id": session_id})
    assert triggered.status_code == 200
    assert set(triggered.json()["result"]["psychological_profile"]) == {
        "emotion", "interest_motivation", "sleep_energy",
        "attention_thinking", "social_daily",
    }
    assert triggered.json()["result"]["concern_index"] == 0
    assert evaluation_stub.inputs[0].vision_summary is None

    session = client.get(f"/api/session/{session_id}").json()
    assert session["assessment_result_id"]
    assert session["current_stage"] == "completed"
    assert session["vision_summary"] is None
    assert session["audio_summary"] is None

    # 记忆库可查到记录
    history = client.get(f"/api/history/{session_id}").json()
    assert history["total"] == 1
