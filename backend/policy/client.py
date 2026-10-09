"""兼容 OpenAI Chat Completions 的训练决策模型客户端。"""

import json
import os
from enum import Enum
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.llm.config import DEFAULT_ENV_FILE
from backend.models.states import Message
from backend.policy.prompt import POLICY_SYSTEM_PROMPT, build_policy_user_prompt


class DialogueAction(str, Enum):
    OTHER = "其它"
    EMPATHY = "共情安慰"
    MENTAL_STATE = "精神状态"
    SLEEP = "睡眠"
    MOOD = "情绪"
    SUICIDE = "自杀倾向"
    PHYSICAL = "躯体症状"
    APPETITE = "食欲"
    SOCIAL = "社会功能"
    INTEREST = "兴趣"
    SCREENING = "筛查"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[DialogueAction] = Field(min_length=1)


class PolicyClientError(RuntimeError):
    """决策模型请求或输出无效。"""


def parse_policy_content(content: str) -> PolicyDecision:
    if not isinstance(content, str):
        raise PolicyClientError("Policy model content must be a string")
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) < 3 or lines[0].strip() not in ("```", "```json") or lines[-1].strip() != "```":
            raise PolicyClientError("Policy model returned an invalid JSON code fence")
        content = "\n".join(lines[1:-1]).strip()
    try:
        return PolicyDecision.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PolicyClientError("Policy model returned invalid actions JSON") from exc


class HttpPolicyClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        load_dotenv(DEFAULT_ENV_FILE, override=False)
        self.base_url = (base_url or os.getenv("POLICY_API_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        endpoint = urlsplit(self.base_url)
        if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("POLICY_API_BASE_URL must be a local loopback HTTP endpoint")
        self.model = model or os.getenv("POLICY_API_MODEL", "policy-qwen3-8b:latest")
        try:
            self.timeout = float(timeout if timeout is not None else os.getenv("POLICY_API_TIMEOUT", "30"))
        except ValueError as exc:
            raise ValueError("POLICY_API_TIMEOUT must be a positive number") from exc
        if self.timeout <= 0:
            raise ValueError("POLICY_API_TIMEOUT must be a positive number")
        key = api_key or os.getenv("POLICY_API_KEY")
        # The policy endpoint is restricted to loopback; system HTTP proxies can
        # otherwise intercept 127.0.0.1 and return a misleading 502.
        self.client = client or httpx.Client(timeout=self.timeout, trust_env=False)
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}

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
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=self.headers, timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PolicyClientError(f"Policy API returned HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise PolicyClientError(f"Policy API request failed: {type(exc).__name__}") from exc
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise PolicyClientError("Policy API response has no message content") from exc
        return parse_policy_content(content)


def get_policy_client() -> HttpPolicyClient:
    """返回本机决策模型客户端。

    对话的下一步动作只有这一个来源：``POLICY_PROVIDER`` 开关和
    ``legacy``（六维固定提问状态机）回退路径已删除。模型不可用时调用方
    必须返回明确错误，不得改由规则提问。
    """
    return HttpPolicyClient()
