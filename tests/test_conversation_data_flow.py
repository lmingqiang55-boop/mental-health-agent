"""只替换两个外部模型响应，验证项目内部的完整对话数据流。"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from conftest import create_consented_session

from evaluation_agent.llm_client import EvaluationLLMClient, HttpResponse, LLMConfig
from evaluation_agent.schemas import ITEM_KEYS
from evaluation_agent.service import EvaluationService

from backend.api import chat
from backend.core.evaluation_engine import evaluation_engine
from backend.main import app
from backend.policy.client import HttpPolicyClient

pytestmark = pytest.mark.usefixtures("isolated_result_store")


class ModelResponseTransport:
    def __init__(self) -> None:
        self.requests = []

    def send(self, request) -> HttpResponse:
        self.requests.append(request)
        items = {
            item: {
                "score": 2 if item == "sleep_disturbance" else 0,
                "evidence": (["最近睡不好"] if item == "sleep_disturbance"
                             else ["对话中未提及相关表现"]),
                "reason": "模拟模型响应，用于接线测试。",
            }
            for item in ITEM_KEYS
        }
        body = {
            "id": "resp_data_flow_test",
            "status": "completed",
            "output": [{
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(items, ensure_ascii=False)}],
            }],
        }
        return HttpResponse(200, json.dumps(body, ensure_ascii=False))


def test_conversation_flows_through_policy_evaluation_storage_and_queries(monkeypatch) -> None:
    policy_requests = []

    def policy_reply(request: httpx.Request) -> httpx.Response:
        policy_requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"target_item":"sleep_disturbance","question_goal":"了解睡眠问题频率"}'}}],
        })

    policy = HttpPolicyClient(
        client=httpx.Client(transport=httpx.MockTransport(policy_reply)))
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)

    model_transport = ModelResponseTransport()
    model_client = EvaluationLLMClient(
        config=LLMConfig(api_key="test-key", max_retries=0),
        transport=model_transport,
    )
    monkeypatch.setattr(evaluation_engine, "_service",
                        EvaluationService(client=model_client))

    client = TestClient(app)
    session_id = create_consented_session(client)
    frame = client.post("/api/vision", json={
        "session_id": session_id,
        "state": {"face_detected": True, "valence": 0.2, "engagement": 0.8},
    })
    assert frame.status_code == 200

    first = client.post("/api/chat", json={
        "session_id": session_id,
        "text": "最近睡不好",
        "vision_snapshot": {"face_detected": True, "valence": -0.7, "engagement": 0.1},
    })
    second = client.post("/api/chat", json={
        "session_id": session_id, "text": "经常凌晨醒",
    })
    assert first.status_code == second.status_code == 200
    # 普通对话正常进行（安全结论为 continue 才会走决策/对话链路）
    assert first.json()["safety"]["route"] == "continue"
    assert second.json()["turn_count"] == 2
    assert len(policy_requests) == 2
    assert "用户：最近睡不好" in policy_requests[0]["messages"][1]["content"]
    assert first.json()["reply"] in policy_requests[1]["messages"][1]["content"]

    assessment = client.post("/api/assessment", json={"session_id": session_id})
    assert assessment.status_code == 200, assessment.json()
    result = assessment.json()["result"]
    # 报告风险字段由「已存储的逐条安全结论」单向投影而来；
    # 普通对话（NORMAL）应投影为低风险且无需干预。
    # 非低风险的投影（UNCERTAIN/HIGH/IMMINENT）由
    # tests/test_safety_agent.py 与 test_evaluation_integration.py 覆盖。
    assert result["risk"]["risk_level"] == "low"
    assert result["risk"]["requires_intervention"] is False
    assert result["concern_index"] > 0
    assert result["assessment_method"] == "evaluation_agent"
    report = result["report"]
    assert report["overall_status"]["concern_index"] == result["concern_index"]
    assert report["overall_status"]["level"] == result["overall_level"]
    assert report["psychological_profile"] == result["psychological_profile"]
    assert report["metadata"]["assessment_id"] == result["result_id"]
    assert report["overall_status"]["summary"]
    assert len(report["key_findings"]) >= 2
    assert report["key_findings"][0]["title"] == "睡眠异常"
    assert report["trend_and_suggestions"]["trend"] == "unclear"
    assert len(report["trend_and_suggestions"]["suggestions"]) >= 2
    assert report["multimodal_observation"]["consistency_level"] == "unknown"
    assert report["multimodal_observation"]["consistency_score"] is None
    assert len(model_transport.requests) == 1
    model_prompt = model_transport.requests[0].json_body["input"]
    assert "用户：最近睡不好\n    〔视觉：效价=-0.70，参与度=0.10，有人脸〕" in model_prompt
    assert "用户：经常凌晨醒" in model_prompt

    saved_session = client.get(f"/api/session/{session_id}").json()
    assert saved_session["current_stage"] == "completed"
    assert saved_session["turn_count"] == 2
    assert saved_session["conversation_history"][1]["vision_snapshot"]["valence"] == -0.7
    assert saved_session["conversation_history"][3]["vision_snapshot"] is None
    assert saved_session["assessment_result_id"] == result["result_id"]

    retrieved = client.get(
        f"/api/assessment/result/{result['result_id']}",
        params={"session_id": session_id},
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["result"] == result

    history = client.get(f"/api/history/{session_id}").json()
    assert history["total"] == 1
    assert history["records"][0]["result"]["result_id"] == result["result_id"]
    assert history["records"][0]["result"]["report"] == report


def test_upstream_two_level_vision_reaches_actual_evaluation_client(monkeypatch) -> None:
    model_transport = ModelResponseTransport()
    model_client = EvaluationLLMClient(
        config=LLMConfig(api_key="test-key", max_retries=0),
        transport=model_transport,
    )
    monkeypatch.setattr(evaluation_engine, "_service",
                        EvaluationService(client=model_client))

    client = TestClient(app)
    session_id = create_consented_session(client)
    response = client.post("/api/assessment", json={
        "session_id": session_id,
        "evaluation_input": {
            "dialogue_history": [
                {
                    "role": "user", "content": "最近睡不好",
                    "vision_snapshot": {
                        "face_detected": True, "emotion": "sad", "valence": -0.4,
                    },
                },
                {"role": "assistant", "content": "这种情况多久了？"},
            ],
            "vision_summary": {
                "dominant_emotion": "sad", "mean_valence": -0.35,
                "valence_trend": [-0.4, -0.3],
                "face_present_ratio": 1.0, "sample_count": 2,
            },
        },
    })
    assert response.status_code == 200, response.json()
    assert response.json()["result"]["concern_index"] > 0
    assert "视觉" in response.json()["result"]["report"]["multimodal_observation"]["summary"]

    prompt = model_transport.requests[0].json_body["input"]
    assert "用户：最近睡不好\n    〔视觉：情绪=sad，效价=-0.40，有人脸〕" in prompt
    assert "- 平均效价：-0.35" in prompt
    assert "- 逐句效价序列（按时间顺序）：-0.40，-0.30" in prompt
    saved = client.get(f"/api/session/{session_id}").json()
    assert saved["vision_summary"]["mean_valence"] == -0.35
    assert saved["conversation_history"][0]["vision_snapshot"]["valence"] == -0.4
