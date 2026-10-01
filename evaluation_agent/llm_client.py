# -*- coding: utf-8 -*-
"""DeepSeek API 客户端：把 :class:`EvaluationInput` 变成 :class:`RawLLMAssessment`。

职责**严格限制**为::

    EvaluationInput
          ↓
    构造 rubric Prompt          （复用 evaluation_agent.prompt）
          ↓
    调用 DeepSeek API
          ↓
    取出 structured response
          ↓
    解析 / 归一化               （复用 evaluation_agent.normalization）
          ↓
    RawLLMAssessment + AssessmentTrace

本模块**不计算**五维画像、``concern_index`` 或关注等级——那些由
:mod:`evaluation_agent.scoring` 与 :mod:`evaluation_agent.service` 负责。
模型只被允许判断 11 个小项。

接口选择
--------

优先使用 **Responses API** 的 ``text.format.type = "json_schema"``
（DeepSeek 官方文档明确支持 ``json_schema``：把结构正确性交给约束解码，
而不是指望模型自觉输出 JSON）。Chat Completions 只支持
``response_format.type = "json_object"``，因此作为回退路径：

- ``api_style = "responses"``（默认）+ ``structured_output = "json_schema"``（默认）
- ``api_style = "chat_completions"`` + ``structured_output = "json_object"``
- 若 ``json_schema`` 被服务端拒绝（400 且错误信息指向 format/schema），
  客户端会**自动降级一次**为 ``json_object`` 并记住该选择，
  本地解析与 Pydantic 校验在任何模式下都不省略。

安全约定
--------

- API Key 只从环境变量（或本地 ``.env``）读取，**不写死、不提交**；
- Key 用 ``SecretStr`` 保存，``repr`` / 序列化都不会输出明文；
- 日志与 ``AssessmentTrace`` 只记录模型名、Prompt 版本、耗时、状态码、
  脱敏后的失败原因，**不记录 API Key、不记录完整对话、不记录模型返回的原文**
  （模型返回的 evidence 里会包含用户原话）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator

from .base import StrictSchemaBase
from .inputs import EvaluationInput
from .normalization import ItemScoreNormalizationError, extract_item_scores
from .prompt import PROMPT_VERSION, build_messages
from .raw_assessment import (
    RESPONSE_SCHEMA_NAME,
    ModelReplyParseError,
    RawLLMAssessment,
    build_response_json_schema,
    extract_json_object,
)
from .schemas import AssessmentItemScores

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "STAGE_TRANSPORT",
    "STAGE_EMPTY_RESPONSE",
    "STAGE_PARSE",
    "STAGE_VALIDATE",
    "STAGE_NORMALIZE",
    "STAGE_DOWNGRADE",
    "LLMError",
    "LLMConfigurationError",
    "LLMAuthenticationError",
    "LLMRequestRejectedError",
    "LLMTransportError",
    "LLMResponseError",
    "LLMRetryableError",
    "LLMRetryExhaustedError",
    "LLMConfig",
    "load_env_file",
    "ApiStyle",
    "StructuredOutputMode",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "UrllibHttpTransport",
    "TokenUsage",
    "AttemptTrace",
    "AssessmentTrace",
    "LLMAssessmentResult",
    "EvaluationLLMClient",
]

logger = logging.getLogger("evaluation_agent.llm_client")

# -- 默认值（都可以用环境变量覆盖） -------------------------------------------

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_RETRIES = 2  # 初次请求 + 2 次重试 = 最多 3 次
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_OUTPUT_TOKENS = 8192
DEFAULT_API_STYLE = "responses"
DEFAULT_STRUCTURED_OUTPUT = "json_schema"
#: 思考强度默认跟随模型自己的默认档位。
#: ``GET /models`` 显示 ``deepseek-flash`` / ``deepseek-v4-pro`` 的
#: ``effort.supported_levels = ["low", "high", "max"]``、``default_level = "high"``。
#: ``"none"`` 不在声明列表里，但实测可用且确实关闭思考（reasoning_tokens=0、
#: 输出里不再有 reasoning 项）——它能省时省钱，代价是判断质量下降
#: （实测：关闭思考时 v4-pro 在一道小推理题上给出了错误答案），
#: 因此不作为默认值。
DEFAULT_REASONING_EFFORT = "high"

ENV_API_KEY = "DEEPSEEK_API_KEY"
ENV_BASE_URL = "DEEPSEEK_BASE_URL"
ENV_MODEL = "DEEPSEEK_MODEL"
ENV_API_STYLE = "DEEPSEEK_API_STYLE"
ENV_STRUCTURED_OUTPUT = "DEEPSEEK_STRUCTURED_OUTPUT"
ENV_REASONING_EFFORT = "DEEPSEEK_REASONING_EFFORT"
ENV_TEMPERATURE = "DEEPSEEK_TEMPERATURE"
ENV_MAX_OUTPUT_TOKENS = "DEEPSEEK_MAX_OUTPUT_TOKENS"
ENV_TIMEOUT_SECONDS = "DEEPSEEK_TIMEOUT_SECONDS"
ENV_MAX_RETRIES = "DEEPSEEK_MAX_RETRIES"

DEFAULT_ENV_FILE = ".env"

ApiStyle = Literal["responses", "chat_completions"]
StructuredOutputMode = Literal["json_schema", "json_object"]
ReasoningEffort = Literal["none", "low", "high", "max"]

# -- 失败阶段（必须能看出失败发生在哪一步） -----------------------------------

STAGE_TRANSPORT = "transport"
STAGE_EMPTY_RESPONSE = "empty_response"
STAGE_PARSE = "parse"
STAGE_VALIDATE = "validate"
STAGE_NORMALIZE = "normalize"
STAGE_DOWNGRADE = "structured_output_downgrade"


# ---------------------------------------------------------------------------
# 异常体系
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """本模块所有异常的基类。

    ``short_reason()`` 返回**可安全写入日志 / trace** 的简短原因：
    不含用户对话、不含模型返回原文、不含 API Key。
    """

    stage: str = "unknown"

    def short_reason(self) -> str:
        return f"{self.stage}: {type(self).__name__}"


class LLMConfigurationError(LLMError):
    """配置问题：缺少 API Key、参数非法、模型名格式不合法。

    **不可重试**：重试不会让配置变对。
    """

    stage = "configuration"


class LLMAuthenticationError(LLMError):
    """认证/授权失败（HTTP 401 / 403）。**不可重试**。"""

    stage = STAGE_TRANSPORT

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMRequestRejectedError(LLMError):
    """请求被服务端拒绝（其它 4xx，例如模型名不存在、参数不合法）。**不可重试**。"""

    stage = STAGE_TRANSPORT

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMRetryableError(LLMError):
    """**可重试**失败的共同基类。

    重试循环只捕获这个基类下的异常；不可重试的失败
    （配置错误、认证失败、请求被拒）不属于它，会直接冒泡。
    """


class LLMTransportError(LLMRetryableError):
    """传输层可重试失败：网络异常、5xx、429。"""

    stage = STAGE_TRANSPORT

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def short_reason(self) -> str:
        if self.status_code is not None:
            return f"{self.stage}: HTTP {self.status_code}"
        return f"{self.stage}: network"


class LLMResponseError(LLMRetryableError):
    """返回内容可重试失败：空回复、无法解析、结构不合法、归一化失败。

    :param stage: 失败阶段，见 ``STAGE_*`` 常量。
    :param safe_summary: **可安全写日志 / trace** 的简短说明：
        只描述问题本身，不含用户对话、不含模型返回原文。
    :param detail: 仅供排查用的补充信息（可能含敏感内容），**不要写日志**。
    """

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        safe_summary: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.safe_summary = safe_summary or message
        self.detail = detail

    def short_reason(self) -> str:
        return f"{self.stage}: {self.safe_summary}"


class _StructuredOutputDowngrade(LLMResponseError):
    """内部信号：服务端不接受 ``json_schema``，本次尝试已降级为 ``json_object``。

    与普通可重试失败区分开，便于在 trace 里如实记录"这次是降级"。
    """

    stage = STAGE_DOWNGRADE


class LLMRetryExhaustedError(LLMError):
    """重试次数用尽后的最终异常。

    必须能看出失败发生在哪个阶段，因此携带 ``stage`` 与全部失败原因。
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        stage: str,
        retry_reasons: list[str],
        last_error: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.stage = stage
        self.retry_reasons = list(retry_reasons)
        self.last_error = last_error

    def short_reason(self) -> str:
        return f"retry_exhausted: attempts={self.attempts} stage={self.stage}"


# ---------------------------------------------------------------------------
# 环境变量 / .env 读取
# ---------------------------------------------------------------------------


def load_env_file(
    path: str | Path = DEFAULT_ENV_FILE, *, override: bool = False, apply: bool = True
) -> dict[str, str]:
    """把 ``.env`` 里的键值读进 ``os.environ``（极简实现，不引入依赖）。

    规则与常见 dotenv 一致：忽略空行与 ``#`` 注释，容忍 ``export`` 前缀，
    去掉值两侧的引号，**默认不覆盖已存在的环境变量**。

    :param path: ``.env`` 路径；不存在时静默跳过。
    :param override: 是否覆盖已存在的环境变量。
    :param apply: 是否真正写入 ``os.environ``。设 ``False`` 时只解析并返回，
        用于"想看看配置是什么，但不要改变当前进程环境"的场合
        （例如测试里判断该不该跳过联调用例）。
    :returns: 本次解析出的键值（``apply=False`` 时返回全部解析结果，
        否则只含真正写入的项）。
    """
    env_path = Path(path)
    if not env_path.is_file():
        return {}

    applied: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        if not apply:
            applied.setdefault(key, value)
            continue
        if key in os.environ and not override:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def _env_value(name: str, default: str | None = None) -> str | None:
    """读环境变量；空字符串按"未设置"处理。"""
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


class LLMConfig(StrictSchemaBase):
    """一次模型调用所需的全部配置。

    API Key 用 :class:`pydantic.SecretStr` 保存：``repr``、``model_dump()``
    与 JSON 序列化都只会输出 ``**********``，不会泄露明文。
    """

    api_key: SecretStr = Field(..., description="DeepSeek API Key（从环境变量读取）。")
    base_url: str = Field(default=DEFAULT_BASE_URL, description="API base URL。")
    model: str = Field(default=DEFAULT_MODEL, description="模型名，例如 deepseek-flash。")
    api_style: ApiStyle = Field(default=DEFAULT_API_STYLE, description="responses 或 chat_completions。")
    structured_output: StructuredOutputMode = Field(
        default=DEFAULT_STRUCTURED_OUTPUT,
        description="json_schema（优先）或 json_object（回退）。",
    )
    reasoning_effort: ReasoningEffort = Field(
        default=DEFAULT_REASONING_EFFORT,
        description=(
            "思考强度：low / high / max 为模型声明的档位，high 是模型默认；"
            "none 不在声明列表里但实测可关闭思考（更省更快、判断质量下降）。"
        ),
    )
    temperature: float = Field(default=DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=DEFAULT_MAX_OUTPUT_TOKENS, ge=1, le=393216)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    max_retries: int = Field(
        default=DEFAULT_MAX_RETRIES,
        ge=0,
        le=5,
        description="重试次数；总尝试次数 = max_retries + 1。",
    )
    retry_backoff_seconds: float = Field(default=DEFAULT_RETRY_BACKOFF_SECONDS, ge=0)

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        cleaned = value.strip().rstrip("/")
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("base_url 必须以 http:// 或 https:// 开头")
        return cleaned

    @field_validator("model")
    @classmethod
    def _check_model_name(cls, value: str) -> str:
        """在本地就挡掉明显非法的模型名，避免拿着错配置去请求。"""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("model 不能为空")
        if not all(char.isalnum() or char in "._:-" for char in cleaned):
            raise ValueError(f"model 名称格式不合法：{cleaned!r}")
        return cleaned

    @model_validator(mode="after")
    def _check_style_and_format(self) -> "LLMConfig":
        if self.api_style == "chat_completions" and self.structured_output == "json_schema":
            # Chat Completions 只支持 response_format.type = json_object，
            # 直接降级而不是发一个必然被拒的请求。
            self.structured_output = "json_object"
            logger.warning(
                "api_style=chat_completions 不支持 json_schema，已自动使用 json_object"
            )
        return self

    # -- 只读辅助 ---------------------------------------------------------

    @property
    def endpoint_url(self) -> str:
        """按接口风格拼出完整 endpoint。"""
        if self.api_style == "responses":
            return f"{self.base_url}/responses"
        return f"{self.base_url}/chat/completions"

    @property
    def api_key_present(self) -> bool:
        """Key 是否已配置（不暴露内容）。"""
        return bool(self.api_key.get_secret_value().strip())

    @property
    def masked_api_key(self) -> str:
        """**不含任何 Key 字符**的展示形式，仅供日志/排查使用。"""
        if not self.api_key_present:
            return "<未设置>"
        return f"****(len={len(self.api_key.get_secret_value().strip())})"

    @property
    def max_attempts(self) -> int:
        """总尝试次数（初次 + 重试）。"""
        return self.max_retries + 1

    def scrub(self, text: str) -> str:
        """把文本里可能出现的 API Key 抹掉（防御性，不改动其余内容）。"""
        secret = self.api_key.get_secret_value().strip()
        if secret and secret in text:
            return text.replace(secret, "***")
        return text

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = DEFAULT_ENV_FILE,
        **overrides: Any,
    ) -> "LLMConfig":
        """从环境变量构造配置（可选先读 ``.env``）。

        :param env_file: 传给 :func:`load_env_file` 的路径；``None`` 表示不读文件。
        :param overrides: 直接覆盖的字段（例如测试里传 ``max_retries=0``）。
        :raises LLMConfigurationError: 缺少 API Key 或取值非法。
        """
        if env_file is not None:
            load_env_file(env_file)

        raw: dict[str, Any] = {
            "api_key": _env_value(ENV_API_KEY),
            "base_url": _env_value(ENV_BASE_URL, DEFAULT_BASE_URL),
            "model": _env_value(ENV_MODEL, DEFAULT_MODEL),
            "api_style": _env_value(ENV_API_STYLE, DEFAULT_API_STYLE),
            "structured_output": _env_value(ENV_STRUCTURED_OUTPUT, DEFAULT_STRUCTURED_OUTPUT),
            "reasoning_effort": _env_value(ENV_REASONING_EFFORT, DEFAULT_REASONING_EFFORT),
            "temperature": _env_value(ENV_TEMPERATURE, str(DEFAULT_TEMPERATURE)),
            "max_output_tokens": _env_value(ENV_MAX_OUTPUT_TOKENS, str(DEFAULT_MAX_OUTPUT_TOKENS)),
            "timeout_seconds": _env_value(ENV_TIMEOUT_SECONDS, str(DEFAULT_TIMEOUT_SECONDS)),
            "max_retries": _env_value(ENV_MAX_RETRIES, str(DEFAULT_MAX_RETRIES)),
        }

        if not raw["api_key"]:
            raise LLMConfigurationError(
                f"未配置 {ENV_API_KEY}。请设置环境变量，"
                f"或在 {DEFAULT_ENV_FILE} 中填写（参考 .env.example）。"
                "注意：不要把真实 Key 提交到仓库。"
            )

        raw.update(overrides)
        try:
            config = cls(**raw)
        except ValidationError as exc:
            raise LLMConfigurationError(_summarize_validation_error(exc)) from exc

        if not config.api_key_present:
            raise LLMConfigurationError(f"{ENV_API_KEY} 为空字符串，视为未配置。")
        return config


def _summarize_validation_error(exc: ValidationError) -> str:
    """把 ValidationError 压成 ``字段: 错误类型`` 列表。

    **只保留 loc 与错误类型**，不携带输入值，避免把 Key 等内容带进异常信息。
    """
    parts = []
    for error in exc.errors():
        loc = ".".join(str(item) for item in error.get("loc", ())) or "<model>"
        parts.append(f"{loc}: {error.get('type')}")
    return "配置取值非法：" + "; ".join(parts)


# ---------------------------------------------------------------------------
# HTTP 传输层（可替换，便于测试时完全不联网）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpRequest:
    """一次 HTTP 请求（已组装好 header 与 JSON body）。"""

    method: str
    url: str
    headers: Mapping[str, str]
    json_body: Mapping[str, Any]
    timeout_seconds: float

    def body_bytes(self) -> bytes:
        return json.dumps(self.json_body, ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class HttpResponse:
    """一次 HTTP 响应（保持最简：状态码 + 文本）。"""

    status_code: int
    body_text: str

    def json(self) -> Any:
        """解析响应体；失败抛 ``ValueError``。"""
        return json.loads(self.body_text)


class HttpTransport(Protocol):
    """传输层协议：只要能发请求即可，便于注入假实现。"""

    def send(self, request: HttpRequest) -> HttpResponse:  # pragma: no cover - 协议
        ...


class UrllibHttpTransport:
    """基于标准库 ``urllib`` 的最小实现（不引入额外依赖）。

    只做"发请求 + 把 HTTP 错误转成响应对象"两件事：

    - 4xx/5xx **不抛异常**，而是作为 :class:`HttpResponse` 返回，
      由客户端按状态码分类（便于精确控制哪些可重试）；
    - 网络层失败（连不上、超时、DNS）抛 :class:`LLMTransportError`。
    """

    def __init__(self, *, urlopen_func: Callable[..., Any] | None = None) -> None:
        self._urlopen = urlopen_func or urlopen

    def send(self, request: HttpRequest) -> HttpResponse:
        prepared = Request(
            url=request.url,
            data=request.body_bytes(),
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with self._urlopen(prepared, timeout=request.timeout_seconds) as response:
                status = getattr(response, "status", None) or response.getcode()
                raw = response.read()
        except HTTPError as exc:  # 4xx / 5xx：把错误响应体取回来
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:  # pragma: no cover - 极端情况
                body = ""
            return HttpResponse(status_code=int(exc.code), body_text=body)
        except (URLError, TimeoutError, OSError) as exc:
            raise LLMTransportError(
                f"网络请求失败（{type(exc).__name__}），未取得 HTTP 响应：{exc}"
            ) from exc

        return HttpResponse(
            status_code=int(status),
            body_text=raw.decode("utf-8", errors="replace"),
        )


# ---------------------------------------------------------------------------
# 后台审计信息
# ---------------------------------------------------------------------------


class TokenUsage(StrictSchemaBase):
    """token 用量（用于成本与性能审计，不含任何用户内容）。"""

    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None


class AttemptTrace(StrictSchemaBase):
    """单次尝试的记录。"""

    attempt: int = Field(..., ge=1, description="第几次尝试（从 1 开始）。")
    outcome: Literal["success", "retryable_failure", "downgraded"] = Field(
        ..., description="该次尝试的结果。"
    )
    stage: str = Field(..., description="失败发生的阶段；成功时为 ok。")
    reason: str | None = Field(
        default=None, description="脱敏后的失败原因（不含用户内容与模型原文）。"
    )
    latency_ms: int = Field(..., ge=0, description="该次尝试的耗时（毫秒）。")
    status_code: int | None = Field(default=None, description="HTTP 状态码（若有）。")
    request_id: str | None = Field(default=None, description="服务端返回的响应 id（若有）。")


class AssessmentTrace(StrictSchemaBase):
    """一次评估调用的**后台审计信息**。

    属于内部数据，**不进入**用户最终看到的 ``EvaluationOutput``。
    刻意不包含任何用户内容：不含对话、不含 ``user_memory``、
    不含模型返回的 evidence 原文、不含 API Key。
    """

    prompt_version: str = Field(..., description="使用的 Prompt 版本。")
    model_name: str = Field(..., description="实际请求的模型名。")
    created_at: datetime = Field(..., description="调用开始时间（UTC，带时区）。")
    api_style: ApiStyle = Field(..., description="实际使用的接口风格。")
    structured_output_mode: StructuredOutputMode = Field(
        ..., description="实际生效的结构化输出方式（可能因降级而与配置不同）。"
    )
    attempts: int = Field(..., ge=1, description="总尝试次数。")
    latency_ms: int = Field(..., ge=0, description="整次评估的总耗时（毫秒）。")
    request_id: str | None = Field(default=None, description="成功那次的响应 id。")
    base_url: str = Field(..., description="请求的 base URL（不含 Key）。")
    retry_reasons: list[str] = Field(
        default_factory=list, description="此前每次失败的原因（脱敏后）。"
    )
    attempt_details: list[AttemptTrace] = Field(
        default_factory=list, description="每次尝试的明细。"
    )
    usage: TokenUsage | None = Field(default=None, description="成功那次的 token 用量。")

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        """审计时间必须带时区，避免与报告时间比较时出现 naive/aware 混用。"""
        if value.tzinfo is None:
            raise ValueError("created_at 必须带时区（tz-aware）")
        return value


class LLMAssessmentResult(StrictSchemaBase):
    """一次模型调用的完整内部结果：原始产出 + 归一化分数 + 审计信息。"""

    raw_assessment: RawLLMAssessment = Field(..., description="模型原始产出（未归一化）。")
    item_scores: AssessmentItemScores = Field(
        ..., description="归一化后的 11 个小项分数（已通过合法性校验）。"
    )
    trace: AssessmentTrace = Field(..., description="本次调用的审计信息。")


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


@dataclass
class _AttemptOutcome:
    """单次尝试成功后的产物。"""

    raw_assessment: RawLLMAssessment
    item_scores: AssessmentItemScores
    status_code: int
    request_id: str | None
    usage: TokenUsage | None
    structured_output_mode: StructuredOutputMode
    latency_ms: int


class EvaluationLLMClient:
    """调用强模型完成 11 小项评估的客户端。

    用法::

        client = EvaluationLLMClient()                 # 从环境变量读配置
        raw = client.assess(evaluation_input)          # -> RawLLMAssessment
        result = client.assess_with_trace(evaluation_input)   # 带审计信息

    重试策略：**整份请求重试**，不做局部小项重试。
    可重试：网络异常、5xx、429、空回复、JSON 无法解析、结构不合法、
    归一化失败、11 项不完整。
    不可重试：缺少 Key、401/403、其它 4xx（模型名不存在、参数非法）。
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        transport: HttpTransport | None = None,
        sleep_func: Callable[[float], None] | None = None,
        now_func: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config if config is not None else LLMConfig.from_env()
        self._transport = transport if transport is not None else UrllibHttpTransport()
        self._sleep = sleep_func or time.sleep
        self._now = now_func or (lambda: datetime.now(timezone.utc))
        #: 实际生效的结构化输出方式（可能因降级而改变）。
        self._structured_output: StructuredOutputMode = self.config.structured_output

    # -- 对外接口 ---------------------------------------------------------

    def assess(self, input_data: EvaluationInput) -> RawLLMAssessment:
        """完成一次评估并返回模型原始产出（最简单的调用形式）。

        :param input_data: 评估输入。
        :returns: 校验并可归一化的模型原始产出。
        :raises LLMRetryExhaustedError: 重试后仍然失败。
        :raises LLMAuthenticationError: 认证失败（不重试）。
        :raises LLMConfigurationError: 配置错误（不重试）。
        :raises LLMRequestRejectedError: 请求被拒绝（不重试）。
        """
        return self.assess_with_trace(input_data).raw_assessment

    def assess_with_trace(self, input_data: EvaluationInput) -> LLMAssessmentResult:
        """完成一次评估，并返回含审计信息的完整结果。

        每次尝试都会**完整走一遍**：取内容 → 解析 JSON → 结构校验 → 归一化。
        任意一步失败都整份重试。
        """
        messages = build_messages(input_data)
        created_at = self._now()
        started = time.monotonic()
        attempt_details: list[AttemptTrace] = []
        retry_reasons: list[str] = []

        logger.info(
            "assessment started: model=%s prompt_version=%s api_style=%s structured_output=%s max_attempts=%d",
            self.config.model,
            PROMPT_VERSION,
            self.config.api_style,
            self._structured_output,
            self.config.max_attempts,
        )

        for attempt in range(1, self.config.max_attempts + 1):
            attempt_started = time.monotonic()
            try:
                outcome = self._attempt(messages)
            except LLMRetryableError as exc:
                latency_ms = _elapsed_ms(attempt_started)
                reason = exc.short_reason()
                retry_reasons.append(reason)
                attempt_details.append(
                    AttemptTrace(
                        attempt=attempt,
                        outcome=(
                            "downgraded"
                            if isinstance(exc, _StructuredOutputDowngrade)
                            else "retryable_failure"
                        ),
                        stage=exc.stage,
                        reason=reason,
                        latency_ms=latency_ms,
                        status_code=getattr(exc, "status_code", None),
                    )
                )
                logger.warning(
                    "attempt %d/%d failed: stage=%s reason=%s latency_ms=%d",
                    attempt,
                    self.config.max_attempts,
                    exc.stage,
                    reason,
                    latency_ms,
                )
                if attempt >= self.config.max_attempts:
                    raise self._exhausted(attempt, exc.stage, retry_reasons, exc) from exc
                self._backoff(attempt)
                continue

            # -- 成功 -----------------------------------------------------
            total_ms = _elapsed_ms(started)
            attempt_details.append(
                AttemptTrace(
                    attempt=attempt,
                    outcome="success",
                    stage="ok",
                    latency_ms=outcome.latency_ms,
                    status_code=outcome.status_code,
                    request_id=outcome.request_id,
                )
            )
            trace = AssessmentTrace(
                prompt_version=PROMPT_VERSION,
                model_name=self.config.model,
                created_at=created_at,
                api_style=self.config.api_style,
                structured_output_mode=outcome.structured_output_mode,
                attempts=attempt,
                latency_ms=total_ms,
                request_id=outcome.request_id,
                base_url=self.config.base_url,
                retry_reasons=retry_reasons,
                attempt_details=attempt_details,
                usage=outcome.usage,
            )
            logger.info(
                "assessment call succeeded: attempt=%d/%d latency_ms=%d request_id=%s",
                attempt,
                self.config.max_attempts,
                total_ms,
                outcome.request_id,
            )
            return LLMAssessmentResult(
                raw_assessment=outcome.raw_assessment,
                item_scores=outcome.item_scores,
                trace=trace,
            )

        # 理论上不可达：循环内要么 return 要么 raise。
        raise self._exhausted(  # pragma: no cover
            self.config.max_attempts, STAGE_TRANSPORT, retry_reasons, None
        )

    # -- 内部实现 ---------------------------------------------------------

    def _attempt(self, messages: list[dict[str, str]]) -> _AttemptOutcome:
        """单次尝试：发请求 → 取内容 → 解析 → 结构校验 → 归一化。

        可重试的失败抛 :class:`LLMResponseError`；
        不可重试的失败抛 :class:`LLMAuthenticationError` /
        :class:`LLMRequestRejectedError`，**直接向上冒泡，不进入重试**。
        """
        attempt_started = time.monotonic()
        mode = self._structured_output
        request = self._build_request(messages, mode)

        response = self._transport.send(request)
        self._raise_for_status(response, mode)

        text = self._extract_text(response)
        if not text.strip():
            # DeepSeek 官方文档明确说明 JSON Output 偶发返回空内容。
            raise LLMResponseError(
                "模型返回了空内容（JSON Output 已知会偶发返回空内容，需要重试）。",
                stage=STAGE_EMPTY_RESPONSE,
                safe_summary="模型返回空内容",
            )

        # 解析：容错包裹形式，但不容忍结构错误。
        try:
            payload = extract_json_object(text)
        except ModelReplyParseError as exc:
            raise LLMResponseError(
                "模型回复不是可解析的 JSON 对象。",
                stage=STAGE_PARSE,
                safe_summary="返回文本中找不到可解析的 JSON 对象",
                # detail 里含回复片段（可能引用用户原话），只用于本地排查。
                detail=str(exc),
            ) from exc

        # 结构校验：11 项齐全、evidence/reason 非空、score 形态可接受。
        try:
            raw = RawLLMAssessment.model_validate(payload)
        except ValidationError as exc:
            summary = _summarize_validation_error(exc)
            raise LLMResponseError(
                "模型返回的 JSON 不符合 11 小项结构要求。",
                stage=STAGE_VALIDATE,
                # 只含字段路径与错误类型，不含字段取值。
                safe_summary=summary,
                detail=summary,
            ) from exc

        # 归一化：分数必须能安全转成 0-3 整数（4 / 2.5 / "moderate" 都算失败）。
        try:
            item_scores = extract_item_scores(raw)
        except ItemScoreNormalizationError as exc:
            summary = str(exc)
            raise LLMResponseError(
                "模型返回的分数无法归一化到 0-3 整数。",
                stage=STAGE_NORMALIZE,
                # 只含小项名与失败原因，不含 evidence。
                safe_summary=summary,
                detail=summary,
            ) from exc

        return _AttemptOutcome(
            raw_assessment=raw,
            item_scores=item_scores,
            status_code=response.status_code,
            request_id=self._extract_request_id(response),
            usage=self._extract_usage(response),
            structured_output_mode=mode,
            latency_ms=_elapsed_ms(attempt_started),
        )

    def _backoff(self, attempt: int) -> None:
        """指数退避（测试里注入 no-op sleep）。"""
        delay = self.config.retry_backoff_seconds * (2 ** (attempt - 1))
        if delay > 0:
            self._sleep(delay)

    def _exhausted(
        self,
        attempts: int,
        stage: str,
        retry_reasons: list[str],
        last_error: Exception | None,
    ) -> LLMRetryExhaustedError:
        return LLMRetryExhaustedError(
            f"模型调用在 {attempts} 次尝试后仍然失败（最后失败阶段：{stage}）。"
            f"失败原因：{'; '.join(retry_reasons) or '未知'}",
            attempts=attempts,
            stage=stage,
            retry_reasons=retry_reasons,
            last_error=last_error,
        )

    # -- 请求构造 ---------------------------------------------------------

    def _build_request(
        self, messages: list[dict[str, str]], mode: StructuredOutputMode
    ) -> HttpRequest:
        """按接口风格组装请求体。"""
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]

        if self.config.api_style == "responses":
            format_spec: dict[str, Any]
            if mode == "json_schema":
                format_spec = {
                    "type": "json_schema",
                    "name": RESPONSE_SCHEMA_NAME,
                    "schema": build_response_json_schema(),
                }
            else:
                format_spec = {"type": "json_object"}

            body: dict[str, Any] = {
                "model": self.config.model,
                "instructions": system_prompt,
                "input": user_prompt,
                "text": {"format": format_spec},
                "max_output_tokens": self.config.max_output_tokens,
                "temperature": self.config.temperature,
                "stream": False,
                # 始终显式发送，行为不依赖服务端默认（注意：思考模式下 temperature 不生效）
                "reasoning": {"effort": self.config.reasoning_effort},
            }
        else:
            body = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": self.config.max_output_tokens,
                "temperature": self.config.temperature,
                "stream": False,
            }
            if self.config.reasoning_effort == "none":
                body["thinking"] = {"type": "disabled"}
            else:
                body["thinking"] = {
                    "type": "enabled",
                    "reasoning_effort": self.config.reasoning_effort,
                }

        return HttpRequest(
            method="POST",
            url=self.config.endpoint_url,
            headers={
                "Authorization": f"Bearer {self.config.api_key.get_secret_value().strip()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "evaluation-agent/1.0",
            },
            json_body=body,
            timeout_seconds=self.config.timeout_seconds,
        )

    # -- 状态码分类 -------------------------------------------------------

    def _raise_for_status(self, response: HttpResponse, mode: StructuredOutputMode) -> None:
        """按状态码决定：成功 / 可重试 / 不可重试 / 降级。"""
        status = response.status_code
        if 200 <= status < 300:
            return

        message = self._error_message(response)

        if status in (401, 403):
            raise LLMAuthenticationError(
                f"认证失败（HTTP {status}）：{message}。请检查 {ENV_API_KEY} 是否有效。",
                status_code=status,
            )

        if status == 400 and mode == "json_schema" and _looks_like_format_rejection(message):
            # 服务端不接受 json_schema：降级为 json_object 再试（只降级一次）。
            self._structured_output = "json_object"
            logger.warning(
                "服务端拒绝了 json_schema（HTTP 400），已降级为 json_object 重试"
            )
            raise _StructuredOutputDowngrade(
                "json_schema 结构化输出被服务端拒绝，已降级为 json_object。",
                stage=STAGE_DOWNGRADE,
                safe_summary="服务端拒绝了 json_schema",
                detail=message,
            )

        if status == 429 or status >= 500:
            raise LLMTransportError(
                f"服务端暂时不可用（HTTP {status}）：{message}", status_code=status
            )

        if 400 <= status < 500:
            raise LLMRequestRejectedError(
                f"请求被拒绝（HTTP {status}）：{message}。这类错误重试没有意义，"
                "请检查模型名与请求参数。",
                status_code=status,
            )

        raise LLMTransportError(
            f"未预期的 HTTP 状态 {status}：{message}", status_code=status
        )

    def _error_message(self, response: HttpResponse) -> str:
        """从错误响应体里取出可读信息，并抹掉可能出现的 Key。"""
        text = response.body_text or ""
        try:
            payload = response.json()
        except ValueError:
            return self.config.scrub(text[:300])

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                pieces = [
                    str(error.get(key))
                    for key in ("message", "type", "code")
                    if error.get(key)
                ]
                if pieces:
                    return self.config.scrub(" / ".join(pieces))
            if payload.get("message"):
                return self.config.scrub(str(payload["message"]))
        return self.config.scrub(text[:300])

    # -- 响应解析 ---------------------------------------------------------

    def _extract_text(self, response: HttpResponse) -> str:
        """从响应体中取出模型输出的可见文本。"""
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMResponseError(
                "响应体不是合法 JSON。",
                stage=STAGE_PARSE,
                safe_summary="HTTP 响应体不是合法 JSON",
                detail=self.config.scrub(response.body_text[:200]),
            ) from exc

        if not isinstance(payload, dict):
            raise LLMResponseError(
                "响应体不是 JSON 对象。",
                stage=STAGE_PARSE,
                safe_summary="HTTP 响应体不是 JSON 对象",
            )

        if self.config.api_style == "responses":
            return self._extract_responses_text(payload)
        return self._extract_chat_text(payload)

    def _extract_responses_text(self, payload: dict[str, Any]) -> str:
        """Responses API：只取 ``message`` 项里的 ``output_text``。

        **必须跳过 ``reasoning`` 项**：思考模式下思维链会作为单独一项排在前面，
        如果把它一起拼进来，就会把模型的推理过程当成 JSON 去解析。
        """
        status = payload.get("status")
        if status == "failed":
            error = payload.get("error") or {}
            detail = error.get("message") or error.get("code") or "未知原因"
            raise LLMResponseError(
                f"模型返回 status=failed：{self.config.scrub(str(detail))}",
                stage=STAGE_TRANSPORT,
                safe_summary="模型返回 status=failed",
                detail=self.config.scrub(str(detail)),
            )
        if status == "incomplete":
            details = payload.get("incomplete_details") or {}
            reason = details.get("reason", "未知原因")
            raise LLMResponseError(
                f"模型返回 status=incomplete（{reason}），输出可能被截断。",
                stage=STAGE_EMPTY_RESPONSE,
                safe_summary=f"模型返回 status=incomplete（{reason}）",
            )

        parts: list[str] = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    parts.append(part.get("text") or "")
        return "".join(parts)

    def _extract_chat_text(self, payload: dict[str, Any]) -> str:
        """Chat Completions：取 ``choices[0].message.content``。"""
        choices = payload.get("choices") or []
        if not choices:
            raise LLMResponseError(
                "响应中没有 choices 字段。", stage=STAGE_PARSE
            )
        first = choices[0] or {}
        finish_reason = first.get("finish_reason")
        if finish_reason == "length":
            raise LLMResponseError(
                "输出被 max_tokens 截断（finish_reason=length）。",
                stage=STAGE_EMPTY_RESPONSE,
            )
        message = first.get("message") or {}
        return message.get("content") or ""

    def _extract_request_id(self, response: HttpResponse) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("id"), str):
            return payload["id"]
        return None

    def _extract_usage(self, response: HttpResponse) -> TokenUsage | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return None

        if self.config.api_style == "responses":
            input_details = usage.get("input_tokens_details") or {}
            output_details = usage.get("output_tokens_details") or {}
            return TokenUsage(
                input_tokens=_as_int(usage.get("input_tokens")),
                output_tokens=_as_int(usage.get("output_tokens")),
                reasoning_tokens=_as_int(output_details.get("reasoning_tokens")),
                cached_tokens=_as_int(input_details.get("cached_tokens")),
                total_tokens=_as_int(usage.get("total_tokens")),
            )

        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        return TokenUsage(
            input_tokens=_as_int(usage.get("prompt_tokens")),
            output_tokens=_as_int(usage.get("completion_tokens")),
            reasoning_tokens=_as_int(completion_details.get("reasoning_tokens")),
            cached_tokens=_as_int(
                prompt_details.get("cached_tokens")
                or usage.get("prompt_cache_hit_tokens")
            ),
            total_tokens=_as_int(usage.get("total_tokens")),
        )


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _elapsed_ms(started: float) -> int:
    return int(round((time.monotonic() - started) * 1000))


def _looks_like_format_rejection(message: str) -> bool:
    """判断 400 错误是否指向"不接受 json_schema / format"。

    只在明确指向格式时才降级；其它 400（例如模型名不存在）必须原样失败，
    不能被误判成"降级后就能好"。
    """
    lowered = message.lower()
    markers = (
        "json_schema",
        "json schema",
        "text.format",
        "response_format",
        "unsupported format",
        "invalid format",
        "format type",
    )
    return any(marker in lowered for marker in markers)
