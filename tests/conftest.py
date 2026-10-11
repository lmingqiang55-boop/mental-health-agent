"""共享测试夹具。

决策模型在测试里一律用 ``httpx.MockTransport`` 模拟响应：不访问网络，
也不要求本机启动模型服务。
"""

import json

import httpx
import pytest

from backend.models.dialogue import DialogueAgentResponse
from backend.policy.client import HttpPolicyClient

DEFAULT_ACTIONS = ("共情安慰", "情绪")


@pytest.fixture(autouse=True)
def dialogue_stub(monkeypatch):
    """API 测试离线运行，同时保留真实的对话 Agent 接线。"""
    from backend.api import chat

    class Stub:
        def __init__(self):
            self.requests = []

        async def generate_reply(self, request):
            self.requests.append(request)
            topic = request.decision.topic or "现在的感受"
            return DialogueAgentResponse(
                reply=f"听起来你说的是「{request.current_user_input.text}」。我们继续聊聊{topic}。"
            )

    stub = Stub()
    monkeypatch.setattr(chat.dialogue_manager, "_dialogue_agent", stub)
    return stub


def build_policy_client(actions=DEFAULT_ACTIONS, *, status_code: int = 200,
                        requests: list[httpx.Request] | None = None) -> HttpPolicyClient:
    """构造只走 MockTransport 的决策模型客户端，返回给定的动作序列。"""
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
    """把 ``/api/chat`` 使用的决策模型替换成模拟响应。"""
    from backend.api import chat

    def install(actions=DEFAULT_ACTIONS, **kwargs) -> HttpPolicyClient:
        client = build_policy_client(actions, **kwargs)
        monkeypatch.setattr(chat.dialogue_manager, "_policy", client)
        return client

    return install
