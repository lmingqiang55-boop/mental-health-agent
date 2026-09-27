"""LLM 客户端。

LLM 只负责「怎么表达」，不接管「问什么」（提问策略由 DialogueManager 决定）。
接入真实 Provider 时实现 ``LLMClient`` 接口，并保留 Mock 降级路径。
"""

import os
from abc import ABC, abstractmethod

from backend.llm.prompts import QUESTIONS
from backend.models.states import Message


class LLMClient(ABC):
    @abstractmethod
    def generate_reply(
        self,
        user_text: str,
        strategy: str,
        retrieved_context: list[str],
        conversation_history: list[Message],
    ) -> str:
        """根据策略和上下文生成自然语言回复。"""


class MockLLMClient(LLMClient):
    """框架阶段的确定性 Mock，无需 API Key，保证主链路可运行。"""

    def generate_reply(
        self,
        user_text: str,
        strategy: str,
        retrieved_context: list[str],
        conversation_history: list[Message],
    ) -> str:
        return QUESTIONS.get(strategy, QUESTIONS["follow_up"])


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """根据 LLM_PROVIDER 返回客户端；未知值时降级为 Mock 并给出提示。"""
    global _client
    if _client is not None:
        return _client
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider == "mock":
        _client = MockLLMClient()
    else:
        # 不在启动时硬失败：降级到 Mock，真实 Provider 后续版本接入
        print(f"[llm] LLM_PROVIDER={provider} 尚未接入，降级使用 mock。")
        _client = MockLLMClient()
    return _client


def set_llm_client(client: LLMClient) -> None:
    global _client
    _client = client
