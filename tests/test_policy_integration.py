import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from fastapi.testclient import TestClient
from conftest import create_consented_session

from backend.api import chat
from backend.core.dialogue_manager import DialogueManager
from backend.main import app
from backend.models.enums import MessageRole
from backend.models.states import Message, SessionState
from backend.policy.client import (
    HttpPolicyClient,
    PolicyClientError,
    get_policy_client,
    parse_policy_content,
)
from backend.safety.schemas import SafetyLevel
from evaluation_agent.rubric import ITEM_RUBRICS
from evaluation_agent.schemas import ITEM_KEYS
from backend.policy.prompt import POLICY_SYSTEM_PROMPT


@pytest.mark.parametrize("item", ITEM_KEYS)
def test_all_evaluation_items_are_valid_policy_targets(item):
    result = parse_policy_content(json.dumps({
        "target_item": item, "question_goal": "补充过去两周的频率"}))
    assert result.model_dump() == {"target_item": item, "question_goal": "补充过去两周的频率"}


@pytest.mark.parametrize("value", [
    {}, {"target_item": "sleep_disturbance"}, {"question_goal": "补充频率"},
    {"target_item": "睡眠", "question_goal": "补充频率"},
    {"target_item": "sleep_disturbance", "question_goal": " "},
    {"target_item": "sleep_disturbance", "question_goal": 123},
    {"target_item": "sleep_disturbance", "question_goal": "补充频率", "score": 1},
    {"target_item": None, "question_goal": "补充频率"},
    {"target_item": "sleep_disturbance", "question_goal": "结束访谈"},
])
def test_invalid_policy_fields_are_rejected(value):
    with pytest.raises(PolicyClientError):
        parse_policy_content(json.dumps(value))


def test_policy_can_return_only_the_exact_ending_pair():
    decision = parse_policy_content('{"target_item":null,"question_goal":"结束访谈"}')
    assert decision.is_finished


@pytest.mark.skipif(os.getenv("RUN_LIVE_POLICY_TESTS") != "1", reason="需显式启用本机模型真实调用")
@pytest.mark.parametrize("answer", [
    "我13岁了，初一", "你好", "我挺好的，没什么烦恼", "我不知道说什么",
])
def test_live_policy_starts_assessment_after_intro_only(answer):
    from evaluation_agent.opening import OPENING_QUESTION

    policy = HttpPolicyClient(timeout=90)
    try:
        session = SessionState(session_id="live-intro", conversation_history=[
            Message(role=MessageRole.ASSISTANT, content=OPENING_QUESTION),
            Message(role=MessageRole.USER, content=answer),
        ])
        decision = DialogueManager(policy_client=policy).decide(session)
        assert not decision.is_finished, decision.model_dump()
    finally:
        policy.client.close()


@pytest.mark.skipif(os.getenv("RUN_LIVE_POLICY_TESTS") != "1", reason="需显式启用本机模型真实调用")
def test_live_policy_moves_on_from_known_mood_and_can_finish_when_informed():
    from evaluation_agent.opening import OPENING_QUESTION

    history = [
        Message(role=MessageRole.ASSISTANT, content=OPENING_QUESTION),
        Message(role=MessageRole.USER, content="我13岁了，初一"),
        Message(role=MessageRole.ASSISTANT, content="最近两周心情怎么样？"),
        Message(role=MessageRole.USER, content="这两周每天心情都挺好的，没有不开心。"),
    ]
    policy = HttpPolicyClient(timeout=90)
    try:
        session = SessionState(session_id="live-progress", conversation_history=history, turn_count=1)
        session.screening_progress.topic_turns = {"depressed_mood": 1}
        decision = DialogueManager(policy_client=policy).decide(session)
        assert not decision.is_finished
        assert decision.target_item != "depressed_mood"
        history.extend([
            Message(role=MessageRole.ASSISTANT, content="其他方面呢？"),
            Message(role=MessageRole.USER, content=(
                "最近两周不觉得自己差，也没觉得对不起谁。打球和画画都跟以前一样开心，想做的事情都主动做。"
                "每天晚上九点半睡到早上六点半，一会儿就能睡着，没早醒。白天精神很好，不累。吃饭和平时一样。"
                "上课专心，选择事情也不费劲，动作说话都和平时一样，没有坐不住。作业考试都能正常完成，"
                "和朋友相处好，洗漱收拾自己也都没问题。这些都是这两周每天的情况。"
            )),
        ])
        session.conversation_history = history
        session.screening_progress.topic_turns = {item: 1 for item in ITEM_KEYS}
        assert DialogueManager(policy_client=policy).decide(session).is_finished
    finally:
        policy.client.close()


def test_policy_receives_actual_rubrics_and_adequate_output_budget():
    assert "每轮只补充一个真正缺失的信息点" in POLICY_SYSTEM_PROMPT
    for rubric in ITEM_RUBRICS:
        assert rubric.item in POLICY_SYSTEM_PROMPT
        assert rubric.definition in POLICY_SYSTEM_PROMPT
        assert all(signal in POLICY_SYSTEM_PROMPT for signal in rubric.signals)
        assert all(exclusion in POLICY_SYSTEM_PROMPT for exclusion in rubric.exclusions)

    def handle(request):
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 512
        assert payload["messages"][0]["content"] == POLICY_SYSTEM_PROMPT
        assert "当前为第 24 轮" in payload["messages"][1]["content"]
        assert "最多 35 轮" in payload["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"target_item":"sleep_disturbance","question_goal":"补充入睡困难的频率"}'}}]})

    client = HttpPolicyClient(client=httpx.Client(transport=httpx.MockTransport(handle)))
    client.predict([Message(role=MessageRole.USER, content="每周三四晚")], turn_count=24)


def test_policy_output_contract_and_local_endpoint() -> None:
    assert parse_policy_content(
        '```json\n{"target_item":"sleep_disturbance","question_goal":"了解入睡困难的频率"}\n```'
    ).target_item == "sleep_disturbance"
    with pytest.raises(PolicyClientError):
        parse_policy_content('{"actions":["未知动作"]}')
    with pytest.raises(ValueError, match="local loopback"):
        HttpPolicyClient(base_url="https://policy.example")


def test_local_policy_ignores_system_http_proxy(monkeypatch) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.dumps({"choices": [{"message": {
                "content": '{"target_item":"sleep_disturbance","question_goal":"了解入睡困难的频率"}'
            }}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            policy = HttpPolicyClient(base_url=f"http://127.0.0.1:{server.server_port}")
            decision = policy.predict([Message(role=MessageRole.USER, content="睡不着")])
            assert decision.target_item == "sleep_disturbance"
        finally:
            policy.client.close()
            server.shutdown()
            thread.join()


def test_policy_actions_drive_chat_and_receive_current_turn(monkeypatch) -> None:
    prompts = []

    def handle(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"target_item":"sleep_disturbance","question_goal":"了解入睡困难的频率"}'}}],
        })

    policy = HttpPolicyClient(
        base_url="http://127.0.0.1:8000",
        model="trained-model",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)
    client = TestClient(app)
    session_id = create_consented_session(client)
    first = client.post("/api/chat", json={"session_id": session_id, "text": "我最近睡不好"})
    second = client.post("/api/chat", json={"session_id": session_id, "text": "经常凌晨醒"})

    assert first.status_code == second.status_code == 200
    assert first.json()["next_strategy"] == "睡眠异常"
    assert "睡眠" in first.json()["reply"]
    assert first.json()["reply"].startswith("听起来")
    assert "用户：我最近睡不好\n\n【当前任务】" in prompts[0]
    assert (
        f"用户：我最近睡不好\n助手：{first.json()['reply']}\n用户：经常凌晨醒\n\n【当前任务】"
    ) in prompts[1]
    assert "sleep_disturbance（睡眠异常）：尚未覆盖" in prompts[0]
    assert "sleep_disturbance（睡眠异常）：已收到 1 次回复" in prompts[1]


def test_high_risk_turn_preempts_policy(monkeypatch, safety_stub) -> None:
    """高风险轮次必须被安全分支拦下，不得调用决策模型。"""
    def must_not_call(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Safety branch must not call the policy model")

    policy = HttpPolicyClient(client=httpx.Client(
        transport=httpx.MockTransport(must_not_call)
    ))
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)
    safety_stub.force(SafetyLevel.HIGH, message="我很担心你，请先联系身边可信任的人。")
    client = TestClient(app)
    session_id = create_consented_session(client)
    response = client.post("/api/chat", json={"session_id": session_id, "text": "我想自杀"})
    assert response.status_code == 200
    body = response.json()
    assert body["current_stage"] == "safety_stop"
    assert body["safety"]["route"] == "safety_stop"
    assert body["reply"] == "我很担心你，请先联系身边可信任的人。"
    # 判定确实发生且只发生一次
    assert len(safety_stub.calls) == 1
    assert safety_stub.calls[0][0] == "我想自杀"


def test_policy_failure_does_not_append_partial_turn(monkeypatch) -> None:
    policy = HttpPolicyClient(client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(503)
    )))
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)
    client = TestClient(app)
    session_id = create_consented_session(client)
    response = client.post("/api/chat", json={"session_id": session_id, "text": "你好"})
    session = client.get(f"/api/session/{session_id}").json()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "POLICY_UNAVAILABLE"
    assert session["turn_count"] == 0
    assert len(session["conversation_history"]) == 1
    assert session["conversation_history"][0]["role"] == "assistant"


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
    session_id = create_consented_session(client)

    response = client.post("/api/chat", json={"session_id": session_id, "text": "你好"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "POLICY_UNAVAILABLE"

    # 没有兜底提问：本轮不落库，也不产生 explore_* 之类的规则策略
    session = client.get(f"/api/session/{session_id}").json()
    assert session["turn_count"] == 0
    assert len(session["conversation_history"]) == 1
    assert session["conversation_history"][0]["role"] == "assistant"


def test_invalid_policy_config_fails_on_first_use_not_on_import(monkeypatch) -> None:
    """配置无效时对话抛明确错误，而不是让整个应用在导入期崩溃。"""
    monkeypatch.setenv("POLICY_API_BASE_URL", "https://policy.example")
    manager = DialogueManager()

    with pytest.raises(PolicyClientError):
        manager.process_turn("你好", SessionState(session_id="s1"))
