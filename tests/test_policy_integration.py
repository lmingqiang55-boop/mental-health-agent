import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import chat
from backend.agents.dialogue_agent import DialogueAgent
from backend.core.dialogue_manager import DialogueManager
from backend.llm.config import DeepSeekConfigError
from backend.main import app
from backend.models.dialogue import DialogueAgentRequest
from backend.models.states import SessionState
from backend.policy.client import (
    DialogueAction,
    HttpPolicyClient,
    PolicyClientError,
    get_policy_client,
    parse_policy_content,
)


def test_policy_output_contract_and_local_endpoint() -> None:
    assert parse_policy_content(
        '```json\n{"actions":["共情安慰","睡眠"]}\n```'
    ).actions == [DialogueAction.EMPATHY, DialogueAction.SLEEP]
    with pytest.raises(PolicyClientError):
        parse_policy_content('{"actions":["未知动作"]}')
    with pytest.raises(ValueError, match="local loopback"):
        HttpPolicyClient(base_url="https://policy.example")


def test_policy_actions_drive_chat_and_receive_current_turn(monkeypatch) -> None:
    prompts = []

    def handle(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"actions":["共情安慰","睡眠"]}'}}],
        })

    policy = HttpPolicyClient(
        base_url="http://127.0.0.1:8000",
        model="trained-model",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]
    first = client.post("/api/chat", json={"session_id": session_id, "text": "我最近睡不好"})
    second = client.post("/api/chat", json={"session_id": session_id, "text": "经常凌晨醒"})

    assert first.status_code == second.status_code == 200
    assert first.json()["next_strategy"] == "睡眠"
    assert "睡眠" in first.json()["reply"]
    assert first.json()["reply"].startswith("听起来")
    assert prompts[0].endswith("用户：我最近睡不好")
    assert prompts[1].endswith(
        f"用户：我最近睡不好\n助手：{first.json()['reply']}\n用户：经常凌晨醒"
    )


def test_same_policy_action_uses_new_user_input_and_prior_reply(policy_stub, dialogue_stub) -> None:
    policy_stub(("共情安慰", "睡眠"))
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]

    first = client.post("/api/chat", json={"session_id": session_id, "text": "最近睡不好"})
    second = client.post("/api/chat", json={"session_id": session_id, "text": "经常凌晨醒"})

    assert first.status_code == second.status_code == 200
    assert first.json()["reply"] != second.json()["reply"]
    assert dialogue_stub.requests[1].conversation_history[-1].content == first.json()["reply"]
    assert dialogue_stub.requests[1].current_user_input.text == "经常凌晨醒"
    assert "最近睡不好" in first.json()["reply"]
    assert "经常凌晨醒" in second.json()["reply"]


def test_dialogue_agent_rewrites_exact_prior_reply() -> None:
    class Client:
        def __init__(self):
            self.calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            return ("最近睡眠怎么样？" if self.calls == 1
                    else "你说睡不着，是从什么时候开始的？")

    request = DialogueAgentRequest.model_validate({
        "conversation_history": [{"role": "assistant", "content": "最近睡眠怎么样？"}],
        "decision": {"actions": ["睡眠"], "topic": "睡眠"},
        "current_user_input": {"text": "睡不着"},
    })
    llm = Client()
    reply = asyncio.run(DialogueAgent(llm).generate_reply(request)).reply

    assert llm.calls == 2
    assert reply == "你说睡不着，是从什么时候开始的？"


def test_missing_dialogue_config_returns_503_without_saving_turn(monkeypatch, policy_stub) -> None:
    policy_stub(("睡眠",))
    monkeypatch.setattr(chat.dialogue_manager, "_dialogue_agent", None)

    def missing_config():
        raise DeepSeekConfigError("missing key")

    monkeypatch.setattr("backend.core.dialogue_manager.load_deepseek_config", missing_config)
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]
    response = client.post("/api/chat", json={"session_id": session_id, "text": "睡不着"})
    session = client.get(f"/api/session/{session_id}").json()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DIALOGUE_UNAVAILABLE"
    assert session["turn_count"] == 0
    assert session["conversation_history"] == []


def test_crisis_preempts_policy(monkeypatch) -> None:
    def must_not_call(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Crisis turn must not call the policy model")

    policy = HttpPolicyClient(client=httpx.Client(
        transport=httpx.MockTransport(must_not_call)
    ))
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]
    response = client.post("/api/chat", json={"session_id": session_id, "text": "我想自杀"})
    assert response.status_code == 200
    assert response.json()["current_stage"] == "crisis"
    assert "急救" in response.json()["reply"]


def test_policy_failure_does_not_append_partial_turn(monkeypatch) -> None:
    policy = HttpPolicyClient(client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(503)
    )))
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]
    response = client.post("/api/chat", json={"session_id": session_id, "text": "你好"})
    session = client.get(f"/api/session/{session_id}").json()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "POLICY_UNAVAILABLE"
    assert session["turn_count"] == 0
    assert session["conversation_history"] == []


def test_legacy_provider_env_var_no_longer_selects_a_fallback(monkeypatch) -> None:
    """POLICY_PROVIDER=legacy 已删除：即使这样设置，也不回到六维规则提问。"""
    monkeypatch.setenv("POLICY_PROVIDER", "legacy")
    monkeypatch.setenv("POLICY_API_BASE_URL", "http://127.0.0.1:8001")
    assert isinstance(get_policy_client(), HttpPolicyClient)

    policy = HttpPolicyClient(client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(503)
    )))
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]

    response = client.post("/api/chat", json={"session_id": session_id, "text": "你好"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "POLICY_UNAVAILABLE"

    # 没有兜底提问：本轮不落库，也不产生 explore_* 之类的规则策略
    session = client.get(f"/api/session/{session_id}").json()
    assert session["turn_count"] == 0
    assert session["conversation_history"] == []


def test_invalid_policy_config_fails_on_first_use_not_on_import(monkeypatch) -> None:
    """配置无效时对话抛明确错误，而不是让整个应用在导入期崩溃。"""
    monkeypatch.setenv("POLICY_API_BASE_URL", "https://policy.example")
    manager = DialogueManager()

    with pytest.raises(PolicyClientError):
        manager.process_turn("你好", SessionState(session_id="s1"))
