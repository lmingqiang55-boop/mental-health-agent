import json
import os
from abc import ABC, abstractmethod

import httpx
from pydantic import ValidationError

from backend.models.enums import DialogueAction
from backend.models.response import PolicyDecision
from backend.models.states import Message
from backend.policy.prompt import POLICY_SYSTEM_PROMPT, build_policy_user_prompt


class PolicyClientError(RuntimeError):
    pass


class PolicyClient(ABC):
    @abstractmethod
    def predict(self, conversation_history: list[Message]) -> PolicyDecision:
        ...


class MockPolicyClient(PolicyClient):
    def predict(self, conversation_history: list[Message]) -> PolicyDecision:
        return PolicyDecision(actions=[DialogueAction.MOOD])


def parse_policy_content(content: str) -> PolicyDecision:
    if not isinstance(content, str):
        raise PolicyClientError("Policy model content must be a string")
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) < 3 or lines[0] not in ("```", "```json") or lines[-1].strip() != "```":
            raise PolicyClientError("Policy model returned an invalid JSON code fence")
        content = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PolicyClientError("Policy model returned invalid JSON") from exc
    try:
        return PolicyDecision.model_validate(parsed)
    except ValidationError as exc:
        raise PolicyClientError(f"Policy model returned invalid actions: {exc}") from exc


class HttpPolicyClient(PolicyClient):
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("POLICY_API_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.model = model or os.getenv("POLICY_API_MODEL", "gpt-3.5-turbo")
        try:
            self.timeout = float(timeout if timeout is not None else os.getenv("POLICY_API_TIMEOUT", "30"))
        except ValueError as exc:
            raise ValueError("POLICY_API_TIMEOUT must be a positive number") from exc
        if self.timeout <= 0:
            raise ValueError("POLICY_API_TIMEOUT must be a positive number")
        self.client = client or httpx.Client(timeout=self.timeout)

    def predict(self, conversation_history: list[Message]) -> PolicyDecision:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": POLICY_SYSTEM_PROMPT},
                {"role": "user", "content": build_policy_user_prompt(conversation_history)},
            ],
            "temperature": 0,
            "max_tokens": 64,
        }
        try:
            response = self.client.post(
                f"{self.base_url}/v1/chat/completions", json=payload, timeout=self.timeout
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PolicyClientError(f"Policy API returned HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise PolicyClientError(f"Policy API request failed: {exc}") from exc
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise PolicyClientError("Policy API response is missing choices or message content") from exc
        return parse_policy_content(content)


_policy_client_override: PolicyClient | None = None


def set_policy_client(client: PolicyClient | None) -> None:
    global _policy_client_override
    _policy_client_override = client


def get_policy_client() -> PolicyClient:
    if _policy_client_override is not None:
        return _policy_client_override
    provider = os.getenv("POLICY_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return MockPolicyClient()
    if provider == "http":
        return HttpPolicyClient()
    raise ValueError(f"Unknown POLICY_PROVIDER: {provider!r}; expected 'mock' or 'http'")
