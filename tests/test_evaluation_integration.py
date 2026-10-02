from importlib import import_module
from types import SimpleNamespace

from fastapi.testclient import TestClient

from evaluation_agent.llm_client import LLMConfigurationError

from backend.main import app

client = TestClient(app)


def new_session() -> str:
    return client.post("/api/session").json()["session_id"]


def test_upstream_two_level_vision_reaches_evaluation_agent(evaluation_stub) -> None:
    session_id = new_session()
    payload = {
        "session_id": session_id,
        "evaluation_input": {
            "dialogue_history": [
                {
                    "role": "user",
                    "content": "最近睡不好",
                    "vision_snapshot": {
                        "face_detected": True,
                        "emotion": "sad",
                        "valence": -0.4,
                    },
                },
                {"role": "assistant", "content": "你愿意说说吗？"},
            ],
            "vision_summary": {
                "dominant_emotion": "sad",
                "mean_valence": -0.35,
                "valence_trend": [-0.4, -0.3],
                "face_present_ratio": 1.0,
                "sample_count": 2,
            },
        },
    }
    response = client.post("/api/assessment", json=payload)

    assert response.status_code == 200, response.json()
    assert response.json()["result"]["overall_level"] == "low_concern"
    received = evaluation_stub.inputs[0]
    assert received.dialogue_history[0].vision_snapshot.valence == -0.4
    assert received.vision_summary.mean_valence == -0.35
    assert received.vision_summary.valence_trend == [-0.4, -0.3]
    session = client.get(f"/api/session/{session_id}").json()
    assert session["conversation_history"][0]["vision_snapshot"]["valence"] == -0.4
    assert session["vision_summary"]["mean_valence"] == -0.35
    assert session["turn_count"] == 1


def test_frames_are_not_mislabelled_as_sentence_snapshots(policy_stub, evaluation_stub) -> None:
    policy_stub()
    session_id = new_session()
    client.post("/api/vision", json={
        "session_id": session_id,
        "state": {"face_detected": True, "valence": -0.6},
    })
    chat = client.post("/api/chat", json={
        "session_id": session_id, "text": "最近睡不好",
    })
    assert chat.status_code == 200
    response = client.post("/api/assessment", json={"session_id": session_id})
    assert response.status_code == 200
    assert evaluation_stub.inputs[0].dialogue_history[0].vision_snapshot is None
    assert evaluation_stub.inputs[0].vision_summary is None


def test_evaluation_without_key_does_not_complete_session(monkeypatch) -> None:
    evaluation_module = import_module("backend.core.evaluation_engine")

    def missing_key(**kwargs):
        raise LLMConfigurationError("missing test key")

    monkeypatch.setattr(evaluation_module.LLMConfig, "from_env", staticmethod(missing_key))
    session_id = new_session()
    response = client.post("/api/assessment", json={
        "session_id": session_id,
        "evaluation_input": {
            "dialogue_history": [{"role": "user", "content": "你好"}],
        },
    })
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EVALUATION_UNAVAILABLE"
    session = client.get(f"/api/session/{session_id}").json()
    assert session["assessment_result_id"] is None
    assert session["current_stage"] == "exploration"


def test_default_service_connects_configured_evaluation_agent_without_network(
    monkeypatch, evaluation_stub
) -> None:
    evaluation_module = import_module("backend.core.evaluation_engine")
    evaluation_module.evaluation_engine.set_service(None)
    config = object()

    def from_env(*, env_file):
        assert env_file == evaluation_module.DEFAULT_ENV_FILE
        return config

    class FakeClient:
        def __init__(self, *, config):
            assert config is expected_config

    expected_config = config
    monkeypatch.setattr(evaluation_module, "LLMConfig", SimpleNamespace(from_env=from_env))
    monkeypatch.setattr(evaluation_module, "EvaluationLLMClient", FakeClient)
    monkeypatch.setattr(
        evaluation_module, "EvaluationService", lambda client: evaluation_stub
    )

    session_id = new_session()
    response = client.post("/api/assessment", json={
        "session_id": session_id,
        "evaluation_input": {
            "dialogue_history": [{"role": "user", "content": "最近睡不好"}],
        },
    })
    assert response.status_code == 200, response.json()
    assert evaluation_stub.inputs[0].dialogue_history[0].content == "最近睡不好"


def test_direct_input_preserves_independent_crisis_signal(evaluation_stub) -> None:
    session_id = new_session()
    response = client.post("/api/assessment", json={
        "session_id": session_id,
        "evaluation_input": {
            "dialogue_history": [{"role": "user", "content": "我想自杀"}],
        },
    })
    assert response.status_code == 200
    assert response.json()["result"]["risk"]["risk_level"] == "high"
    assert response.json()["result"]["report"]["key_findings"][0]["title"] == "安全提示"
    assert "安全风险" in response.json()["result"]["report"]["overall_status"]["summary"]
    assert "可信任的成年人" in response.json()["result"]["report"]["trend_and_suggestions"]["suggestions"][0]


def test_assessment_result_can_be_read_by_its_public_id(evaluation_stub) -> None:
    session_id = new_session()
    response = client.post("/api/assessment", json={
        "session_id": session_id,
        "evaluation_input": {
            "dialogue_history": [{"role": "user", "content": "最近睡不好"}],
        },
    })
    assert response.status_code == 200, response.json()
    result_id = response.json()["result"]["result_id"]

    retrieved = client.get(
        f"/api/assessment/result/{result_id}", params={"session_id": session_id}
    )
    assert retrieved.status_code == 200, retrieved.json()
    assert retrieved.json()["result"]["result_id"] == result_id

    other_session = new_session()
    mismatched = client.get(
        f"/api/assessment/result/{result_id}", params={"session_id": other_session}
    )
    assert mismatched.status_code == 404
