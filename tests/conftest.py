"""共享离线测试夹具。"""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from evaluation_agent.schemas import OverallLevel, PsychologicalProfile

from backend.core.evaluation_engine import evaluation_engine
from backend.policy.client import HttpPolicyClient

DEFAULT_ACTIONS = ("共情安慰", "情绪")


def build_policy_client(actions=DEFAULT_ACTIONS, *, status_code: int = 200,
                        requests: list[httpx.Request] | None = None) -> HttpPolicyClient:
    def handle(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return httpx.Response(status_code, json={
            "choices": [{"message": {"content": json.dumps(
                {"actions": list(actions)}, ensure_ascii=False)}}],
        })

    return HttpPolicyClient(
        client=httpx.Client(transport=httpx.MockTransport(handle)))


@pytest.fixture
def policy_stub(monkeypatch):
    """把 /api/chat 使用的决策模型替换成离线模拟响应。"""
    from backend.api import chat

    def install(actions=DEFAULT_ACTIONS, **kwargs) -> HttpPolicyClient:
        client = build_policy_client(actions, **kwargs)
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
