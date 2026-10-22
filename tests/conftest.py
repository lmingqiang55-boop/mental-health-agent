"""共享离线测试夹具。"""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from evaluation_agent.schemas import OverallLevel, PsychologicalProfile

from backend.core.evaluation_engine import evaluation_engine
from backend.models.dialogue import DialogueAgentResponse
from backend.policy.client import HttpPolicyClient

DEFAULT_TARGET = "depressed_mood"
DEFAULT_GOAL = "了解过去两周情绪变化的频率"


@pytest.fixture
def isolated_result_store(monkeypatch):
    import sqlite3
    from contextlib import contextmanager
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
    yield store
    connection.close()


def create_consented_session(client) -> str:
    """通过真实同意接口准备对话测试，保留服务端授权门禁。"""
    from backend.api.consent_guard import ALLOWED_SCOPES

    response = client.post("/api/session")
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    response = client.put(f"/api/session/{sid}/consent", json={
        "session_id": sid, "granted": True, "scope": sorted(ALLOWED_SCOPES),
    })
    assert response.status_code == 200, response.text
    return sid


@pytest.fixture(autouse=True)
def dialogue_stub(monkeypatch):
    """Keep API tests offline while exercising the dialogue Agent boundary."""
    from backend.api import chat
    from backend.models.dialogue import DialogueRouteDecision

    class Stub:
        """对话 Agent 的离线替身：生成回复 + 路由判断。

        路由默认返回 ``need_decision=True``，即"每轮都要新策略"，
        与迁移前的行为一致——不显式开启自主追问的测试不受 Phase 2 影响。
        """

        def __init__(self):
            self.requests = []
            self.route_requests = []
            self.need_decision = True
            self.route_reason_code = "topic_exhausted"

        def set_route(self, need_decision: bool,
                      reason_code: str = "continue_topic") -> None:
            """让后续路由判断固定返回指定结论。"""
            self.need_decision = need_decision
            self.route_reason_code = reason_code

        async def route(self, request):
            self.route_requests.append(request)
            return DialogueRouteDecision(
                need_decision=self.need_decision,
                reason_code=self.route_reason_code,
                reason="离线桩",
            )

        async def generate_reply(self, request):
            self.requests.append(request)
            topic = request.decision.target_label
            return DialogueAgentResponse(
                reply=f"听起来你说的是「{request.current_user_input.text}」。我们继续聊聊{topic}。"
            )

    stub = Stub()
    monkeypatch.setattr(chat.dialogue_manager, "_dialogue_agent", stub)
    return stub


@pytest.fixture(autouse=True)
def safety_stub(monkeypatch):
    """把 /api/chat 的安全判定替换成离线结论。

    autouse：新版 Safety 是每个用户消息的第一道闸门，若不替换，
    所有走 /api/chat 的测试都会真的去调用 DeepSeek。

    默认判定 NORMAL；需要安全分支的测试调用 ``safety_stub.force(...)``。
    """
    from backend.api import chat
    from backend.safety.schemas import (
        ModelStatus, SafetyLevel, SafetyVerdict, derive_risk_detected, derive_route,
    )

    NORMAL_MESSAGE = "我听到了，我们继续聊聊。"

    class Stub:
        def __init__(self):
            self.calls: list[tuple[str, list]] = []
            self.level = SafetyLevel.NORMAL
            self.model_status = ModelStatus.ok
            self.forced_message: str | None = None

        def force(self, level, *, message=None, model_status=ModelStatus.ok):
            """让后续判定固定返回指定等级。"""
            self.level = level
            self.model_status = model_status
            self.forced_message = message

        def evaluate(self, text, history):
            self.calls.append((text, list(history)))
            level = self.level
            messages: list[str] = []
            if level is not SafetyLevel.NORMAL:
                messages = [self.forced_message or f"安全分支回应：{level.value}"]
            numbers = ["12356"] if level in (SafetyLevel.HIGH, SafetyLevel.IMMINENT) else []
            return SafetyVerdict(
                risk_detected=derive_risk_detected(level),
                risk_level=level,
                route=derive_route(level),
                messages=messages,
                hotline_numbers=numbers,
                model_status=self.model_status,
            )

    stub = Stub()
    # 两个入口都要替换：
    # 1) /api/chat 的第一道闸门；
    # 2) 评估时对「没有安全结论的用户消息」的补判（直接导入转写文本的路径）。
    # 少替换任何一个，测试都会真的去调用 DeepSeek。
    monkeypatch.setattr(chat.safety_runner, "evaluate", stub.evaluate)
    from backend.core import evaluation_engine as evaluation_engine_module
    monkeypatch.setattr(evaluation_engine_module, "evaluate_safety", stub.evaluate)
    return stub


def build_policy_client(target_item=DEFAULT_TARGET, *, question_goal=DEFAULT_GOAL,
                        status_code: int = 200,
                        requests: list[httpx.Request] | None = None) -> HttpPolicyClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return httpx.Response(status_code, json={
            "choices": [{"message": {"content": json.dumps(
                {"target_item": target_item, "question_goal": question_goal}, ensure_ascii=False)}}],
        })

    return HttpPolicyClient(
        client=httpx.Client(transport=httpx.MockTransport(handle)))


@pytest.fixture
def policy_stub(monkeypatch):
    """把 /api/chat 使用的决策模型替换成离线模拟响应。"""
    from backend.api import chat

    def install(target_item=DEFAULT_TARGET, **kwargs) -> HttpPolicyClient:
        client = build_policy_client(target_item, **kwargs)
        monkeypatch.setattr(chat.dialogue_manager, "_policy", client)
        return client

    return install


@pytest.fixture
def evaluation_stub():
    """模拟评估服务，只检查接线，不调用外部模型。"""

    class Stub:
        def __init__(self):
            self.inputs = []

        def evaluate(self, input_data):
            self.inputs.append(input_data)
            return SimpleNamespace(
                assessment_id=str(uuid4()),
                psychological_profile=PsychologicalProfile(
                    emotion=0,
                    interest_motivation=0,
                    sleep_energy=0,
                    attention_thinking=0,
                    social_daily=0,
                ),
                concern_index=0,
                overall_level=OverallLevel.LOW_CONCERN,
            )

    previous = evaluation_engine._service
    stub = Stub()
    evaluation_engine.set_service(stub)
    try:
        yield stub
    finally:
        evaluation_engine.set_service(previous)
