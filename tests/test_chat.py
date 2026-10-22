import base64
import json
import sqlite3
from contextlib import contextmanager
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from conftest import create_consented_session
from PIL import Image

from backend.main import app
from backend.models.states import VisionState
from backend.safety.schemas import SafetyLevel
from backend.safety.support import SUPPORT_MODE_CONTINUATION_MESSAGE
from backend.vision.detector import MockVisionDetector, VisionDetector, set_detector

client = TestClient(app)


@pytest.fixture(autouse=True)
def _stub_decision_model(policy_stub):
    """本文件的对话用例一律使用模拟的决策模型响应，不启动真实模型。"""
    policy_stub()


def new_session() -> str:
    return create_consented_session(client)


def test_chat_without_multimodal_or_api_key() -> None:
    session_id = new_session()
    first = client.post("/api/chat", json={
        "session_id": session_id, "text": "最近总是觉得压力很大"
    })
    assert first.status_code == 200
    body = first.json()
    assert body["reply"]
    assert body["next_strategy"] == "情绪低落"
    # 安全结论来自新版 Safety，且普通对话必须给出 continue 路由
    assert body["safety"]["risk_level"] == "normal"
    assert body["safety"]["route"] == "continue"
    assert body["safety"]["risk_detected"] is False
    assert body["messages"] == [body["reply"]]
    assert body["turn_count"] == 1

    second = client.post("/api/chat", json={
        "session_id": session_id, "text": "晚上常常睡不着"
    })
    assert second.status_code == 200
    assert second.json()["turn_count"] == 2

    session = client.get(f"/api/session/{session_id}").json()
    assert len(session["conversation_history"]) == 5
    assert session["latest_vision_state"] is None
    assert session["latest_audio_state"] is None
    # 六维固定提问状态机删除后，这两个公共字段不再存在
    assert "assessment_state" not in session
    assert "clarify_count" not in session


def test_chat_uses_decision_model_actions(policy_stub) -> None:
    """提问方向来自决策模型的动作，而不是按维度固定顺序推进。"""
    policy_stub('sleep_disturbance')
    session_id = new_session()
    body = client.post("/api/chat", json={
        "session_id": session_id, "text": "我最近总失眠"
    }).json()
    assert body["next_strategy"] == "睡眠异常"
    assert "睡眠" in body["reply"]
    # 不再出现六维状态机的策略名
    assert not body["next_strategy"].startswith("explore_")


def test_chat_sends_accumulated_history_to_decision_model(policy_stub) -> None:
    requests = []
    policy_stub('sleep_disturbance', requests=requests)
    session_id = new_session()
    first = client.post("/api/chat", json={
        "session_id": session_id, "text": "我最近睡不好"})
    client.post("/api/chat", json={"session_id": session_id, "text": "经常凌晨醒"})

    first_prompt = json.loads(requests[0].content)["messages"][1]["content"]
    second_prompt = json.loads(requests[1].content)["messages"][1]["content"]
    assert first_prompt.split("\n\n【当前任务】")[0].endswith("用户：我最近睡不好")
    assert second_prompt.split("\n\n【当前任务】")[0].endswith(
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
    assert session["conversation_history"][1]["vision_snapshot"] is None
    assert session["conversation_history"][1]["audio_snapshot"] is None


def test_chat_stores_only_exact_utterance_vision() -> None:
    session_id = new_session()
    response = client.post("/api/chat", json={
        "session_id": session_id,
        "text": "最近心情不好",
        "vision_snapshot": {"face_detected": True, "valence": -0.4},
    })
    assert response.status_code == 200
    message = client.get(f"/api/session/{session_id}").json()["conversation_history"][1]
    assert message["vision_snapshot"]["valence"] == -0.4
    assert message["audio_snapshot"] is None


def test_chat_uses_aligned_vision_for_current_turn() -> None:
    session_id = new_session()
    response = client.post("/api/chat", json={
        "session_id": session_id,
        "text": "我最近睡不好",
        "vision_snapshot": {
            "face_detected": True, "valence": -0.7, "engagement": 0.1,
        },
    })
    assert response.status_code == 200, response.json()
    # 本句视觉快照必须绑定到本轮用户消息（对齐，不串句）
    message = client.get(f"/api/session/{session_id}").json()["conversation_history"][1]
    assert message["vision_snapshot"]["valence"] == -0.7
    assert message["vision_snapshot"]["engagement"] == 0.1


def test_safety_level_ignores_vision_and_depends_on_text(safety_stub) -> None:
    """新版 Safety 只做文本语义判定，视觉信号不再参与风险分级。

    旧实现用 ``assess_risk(fuse_turn(text, vision))``，负面效价会把等级
    抬到 medium。新版由 LLM 结合文本与对话历史判定，视觉不再进入风险结论。
    这里锁定该行为，避免日后误以为视觉仍在参与分级。
    """
    session_id = new_session()
    body = client.post("/api/chat", json={
        "session_id": session_id,
        "text": "我最近睡不好",
        "vision_snapshot": {
            "face_detected": True, "valence": -0.9, "engagement": 0.05,
        },
    }).json()
    assert body["safety"]["risk_level"] == "normal"
    assert body["safety"]["route"] == "continue"
    # Safety 只收到文本，且收到的是本轮文本
    assert safety_stub.calls[-1][0] == "我最近睡不好"


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


def test_vision_frame_endpoint_uses_detector_and_discards_raw_frame(monkeypatch) -> None:
    from backend.vision import detector as detection
    monkeypatch.setattr(detection, '_detector', MockVisionDetector())
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


def test_high_risk_message_enters_safety_stop_and_never_auto_resumes(
        safety_stub, dialogue_stub) -> None:
    """HIGH 进入安全支持模式；后续正常表达**不得**自动恢复普通评估。"""
    safety_stub.force(SafetyLevel.HIGH, message="我很担心你，请先联系身边可信任的人。")
    session_id = new_session()
    body = client.post("/api/chat", json={
        "session_id": session_id, "text": "我想自杀"
    }).json()

    assert body["safety"]["risk_level"] == "high"
    assert body["safety"]["route"] == "safety_stop"
    assert body["safety"]["risk_detected"] is True
    # 号码只来自后端已核实配置，且仅在 STOP 时下发
    assert body["safety"]["hotline_numbers"] == ["12356"]
    assert body["current_stage"] == "safety_stop"
    assert body["reply"] == "我很担心你，请先联系身边可信任的人。"
    assert body["messages"] == ["我很担心你，请先联系身边可信任的人。"]
    assert body["next_strategy"] == "safety_support"
    assert body["assessment_ready"] is False
    assert body["visual_feedback"]["reason"] == "safety_stop"
    assert body["turn_count"] == 1

    session = client.get(f"/api/session/{session_id}").json()
    assert session["safety_halted"] is True
    assert session["safety_stage"] == "stopped"
    assert session["latest_safety"]["route"] == "safety_stop"
    # 安全分支也要落库，保持 user/assistant 成对（外加 1 条开场消息）
    assert len(session["conversation_history"]) == 3
    assert session["conversation_history"][1]["role"] == "user"
    assert session["conversation_history"][2]["content"] == body["reply"]

    # 关键：下一轮 Safety 判为 NORMAL，也不得自动恢复普通评估
    safety_stub.force(SafetyLevel.NORMAL)
    dialogue_calls = len(dialogue_stub.requests)
    follow = client.post("/api/chat", json={
        "session_id": session_id, "text": "我今天心情还不错"
    }).json()
    # safety 反映的是**本轮判定**，current_stage 反映的是**会话锁定状态**
    assert follow["safety"]["risk_level"] == "normal"
    assert follow["safety"]["route"] == "continue"
    assert follow["current_stage"] == "safety_stop"
    assert follow["next_strategy"] == "safety_support"
    assert follow["assessment_ready"] is False
    # 支持模式持续对话：该轮 Safety 未给出文案，必须回落到支持模式续接文案，
    # 而不是空气泡、也不是普通问诊话术。
    # 续接文案是两句话，按气泡协议拆成 2 条；reply 是它们的全文投影。
    assert follow["reply"] == SUPPORT_MODE_CONTINUATION_MESSAGE
    assert follow["messages"] == SUPPORT_MODE_CONTINUATION_MESSAGE.splitlines()
    assert len(follow["messages"]) == 2
    # 并且完全没有进入普通对话链路
    assert len(dialogue_stub.requests) == dialogue_calls
    assert follow["turn_count"] == 2

    session = client.get(f"/api/session/{session_id}").json()
    assert session["safety_halted"] is True
    assert session["current_stage"] == "safety_stop"


def test_uncertain_message_enters_review_and_can_resume_on_normal(safety_stub) -> None:
    """UNCERTAIN 进入安全澄清模式：暂停普通评估，下一轮 NORMAL 可恢复。"""
    safety_stub.force(SafetyLevel.UNCERTAIN, message="我想先确认一下你现在是否安全。")
    session_id = new_session()
    body = client.post("/api/chat", json={
        "session_id": session_id, "text": "有时候觉得活着真没意思"
    }).json()
    assert body["safety"]["risk_level"] == "uncertain"
    assert body["safety"]["route"] == "safety_review"
    assert body["current_stage"] == "safety_review"
    assert body["next_strategy"] == "safety_review"
    assert body["visual_feedback"]["reason"] == "safety_review"
    # 澄清不等于停止：不下发号码，也不置停止锁
    assert body["safety"]["hotline_numbers"] == []
    session = client.get(f"/api/session/{session_id}").json()
    assert session["safety_halted"] is False
    assert session["safety_stage"] == "review"

    # 澄清后恢复正常表达，可以回到普通评估
    safety_stub.force(SafetyLevel.NORMAL)
    follow = client.post("/api/chat", json={
        "session_id": session_id, "text": "我最近就是睡不好"
    }).json()
    assert follow["current_stage"] == "exploration"
    assert follow["next_strategy"] == "情绪低落"
    session = client.get(f"/api/session/{session_id}").json()
    assert session["safety_halted"] is False
    assert session["safety_stage"] == "none"


@pytest.mark.parametrize("engine", ["legacy", "graph"])
@pytest.mark.parametrize("completed", [False, True])
def test_safety_review_does_not_reopen_finished_interview(
        safety_stub, dialogue_stub, monkeypatch, engine, completed):
    from backend.core.session_manager import session_manager
    from backend.models.enums import SessionStage

    monkeypatch.setenv("DIALOGUE_ENGINE", engine)
    sid = new_session()

    def close(state):
        state.current_stage = SessionStage.COMPLETED if completed else SessionStage.ASSESSMENT_READY
        state.screening_progress.end_reason = "model_finished"
        if completed:
            state.assessment_result_id = "saved-result"

    session_manager.modify_session(sid, close)
    safety_stub.force(SafetyLevel.UNCERTAIN)
    review = client.post("/api/chat", json={"session_id": sid, "text": "有点想不开"})
    assert review.status_code == 200
    assert review.json()["current_stage"] == "safety_review"
    safety_stub.force(SafetyLevel.NORMAL)
    resolved = client.post("/api/chat", json={"session_id": sid, "text": "我很安全，刚才只是随口说的"})
    assert resolved.status_code == 200
    assert resolved.json()["assessment_ready"] is True
    assert resolved.json()["current_stage"] == ("completed" if completed else "assessment_ready")
    assert dialogue_stub.requests == []
    assert session_manager.get_session(sid).safety_stage == "none"
    again = client.post("/api/chat", json={"session_id": sid, "text": "接着聊吗"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "SCREENING_FINISHED"


def test_normal_verdict_does_not_enter_safety_branch(safety_stub) -> None:
    """结论为 NORMAL 时不进入安全分支。

    「否定的自杀表述不得判为高风险」这条保护现在由 Safety Agent 的
    语义判定承担（提示词明确要求处理否定与转述），相应断言在
    ``tests/test_safety_agent.py`` 中锁定；这里只锁定路由契约。
    """
    session_id = new_session()
    body = client.post("/api/chat", json={
        "session_id": session_id, "text": "我不想自杀，我只是有点难过"
    }).json()
    assert body["safety"]["route"] == "continue"
    assert body["current_stage"] == "exploration"
    assert body["assessment_ready"] is False
    # Safety 收到的是本轮原文，未被截断或改写
    assert safety_stub.calls[-1][0] == "我不想自杀，我只是有点难过"


def test_short_chat_does_not_auto_assess_and_manual_assessment_is_explicit(
    evaluation_stub, monkeypatch,
) -> None:
    """短对话仍可继续；聊天收尾与生成报告是两个独立动作。"""
    from backend.core.memory_store import MemoryStore

    connection = sqlite3.connect(":memory:", check_same_thread=False)

    class InMemoryStore(MemoryStore):
        @contextmanager
        def _connection(self):
            with connection:
                yield connection

    store = InMemoryStore(":memory:")
    monkeypatch.setattr("backend.api.assessment.memory_store", store)
    monkeypatch.setattr("backend.api.history.memory_store", store)
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
    assert history["records"][0]["result"]["result_id"] == triggered.json()["result"]["result_id"]
    connection.close()
