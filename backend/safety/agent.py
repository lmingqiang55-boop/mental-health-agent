# -*- coding: utf-8 -*-
"""新 Safety Agent：系统唯一的心理安全检测入口。

与旧 ``backend/core/risk_engine.py`` 无任何关系，不 import 它、不复用它任何函数。

【判定方式】
调用 LLM 结合「用户最新发言 + 对话历史」做语义判断。危险表达关键词只作为
辅助线索（``SafetySignal``）随提示词一并给出，**不参与**风险等级的决定。

【失败处理】
超时 / 解析失败 / 服务不可用一律产出 UNCERTAIN + SAFETY_REVIEW，绝不放行。
这是刻意选择的 fail-to-review：宁可多一次安全澄清，不可漏判。

【为什么每次判定新建客户端】
本项目是「同步 FastAPI 端点 + 每请求 ``asyncio.run()``」的模式，
``AsyncOpenAI`` 内部 httpx 连接池绑定在创建它的事件循环上；循环关闭后
复用同一实例会立即失败。因此 :class:`SafetyAgent` 持有的是**客户端工厂**，
每次判定新建、用完关闭，与 ``dialogue_manager._generate_reply`` 的做法一致。

【号码来源】
提示词里不出现任何号码；``hotline_numbers`` 由后端从已核实配置注入，
并强制经过白名单校验。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from typing import Any, Callable, Protocol, Sequence

from pydantic import ValidationError

from backend.core.text_signals import predicate_is_negated
from backend.llm.config import load_deepseek_config
from backend.llm.deepseek_client import DeepSeekClient, DeepSeekClientError
from backend.safety.hotlines import allowed_hotline_numbers, load_hotlines
from backend.safety.prompt import SAFETY_SYSTEM_PROMPT, build_safety_user_prompt
from backend.safety.schemas import (
    ModelStatus,
    SafetyAgentError,
    SafetyModelOutput,
    SafetySignal,
    SafetyVerdict,
    assemble_verdict,
)

__all__ = [
    "SafetyClient",
    "SafetyAgent",
    "SAFETY_KEYWORDS",
    "SAFETY_FALLBACK_MESSAGE",
    "scan_keywords",
    "parse_safety_content",
    "evaluate_safety",
    "get_safety_agent",
    "set_safety_agent",
    "build_default_agent",
]

#: Safety 专属超时。比 Dialogue 的 60s 短得多：安全判定必须快速返回，
#: 卡住时应当尽快进入 REVIEW，而不是让学生干等。
DEFAULT_SAFETY_TIMEOUT_SECONDS = 12.0

#: Safety 的输出上限。这个值是**按 schema 的字段上限算出来的**，不是拍的：
#: rationale ≤ 600 字 + support_message ≤ 600 字 + 5 条 evidence_quotes，
#: 合计约 1200 汉字 ≈ 800~1000 token，再加 JSON 结构。
#: 之所以必须留足余量：输出一旦在上限处被截断，JSON 就是残缺的，
#: 整轮判定会从 ok 掉成 parse_error -> 人工复核。上限是天花板而不是开销，
#: 模型写得简洁时并不会真的生成这么多。
DEFAULT_SAFETY_MAX_TOKENS = 1600

#: 模型失败时给学生的安全侧模板。不含号码（判定未完成，不给号码）。
SAFETY_FALLBACK_MESSAGE = (
    "我想先确认一下你现在是否安全。这一轮我们先不继续原来的话题，"
    "如果你此刻感到很难受，请让身边可信任的人陪着你。"
)

#: 危险表达关键词。**仅作辅助线索**，不产生结论。
#: 刻意不 import 旧 risk_engine 的信号表，独立维护。
SAFETY_KEYWORDS: tuple[str, ...] = (
    # 自杀意念
    "自杀", "轻生", "想死", "去死", "死了算了", "不想活", "活不下去",
    "结束生命", "结束自己", "了结自己", "一了百了",
    # 计划与方式
    "跳楼", "跳下去", "跳河", "卧轨", "割腕", "割脉", "上吊", "自缢",
    "烧炭", "吞药", "安眠药", "吃安眠药",
    # 准备行为
    "遗书", "遗言", "交代后事", "最后一面", "告别",
    # 自伤
    "自伤", "自残", "伤害自己", "划自己",
    # 伤害他人
    "杀了他", "杀了她", "伤害他人", "报复社会",
)


class SafetyClient(Protocol):
    """Safety 只需一个异步文本生成接口，便于离线替换。"""

    async def generate(self, system_prompt: str, user_prompt: str) -> str: ...


def scan_keywords(text: str, source: str = "latest_message") -> list[SafetySignal]:
    """扫描危险表达关键词。命中项带否定标记，**不产生风险结论**。

    返回按词去重后的信号列表，保留首次出现的位置。
    """
    signals: list[SafetySignal] = []
    seen: set[str] = set()
    for term in SAFETY_KEYWORDS:
        if term in seen:
            continue
        index = text.find(term)
        if index < 0:
            continue
        seen.add(term)
        signals.append(SafetySignal(
            term=term,
            negated=predicate_is_negated(text, index),
            source="history" if source == "history" else "latest_message",
        ))
    return signals


def parse_safety_content(content: str) -> SafetyModelOutput:
    """解析 Safety 模型输出，容忍 Markdown 代码块围栏。

    ``strict=False`` 是刻意的：支持文本现在要求写成 2~3 段（段间换行），
    模型偶尔不转义 ``\\n`` 而是直接在 JSON 字符串里换行。那在 RFC 8259 里
    不合法，但语义毫无歧义——为此把整轮判定降级成人工复核（fail-to-REVIEW）
    并不划算，所以这里放宽控制字符。字段校验仍然照旧严格执行。

    Raises:
        SafetyAgentError: 找不到 JSON 对象，或字段不符合约定。
    """
    text = (content or "").strip()
    if not text:
        raise SafetyAgentError("Safety 模型返回空内容")

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise SafetyAgentError("Safety 模型输出中没有 JSON 对象")
    payload = text[start:end + 1]

    try:
        raw: Any = json.loads(payload, strict=False)
    except json.JSONDecodeError as exc:
        raise SafetyAgentError("Safety 模型输出不是合法 JSON") from exc
    if not isinstance(raw, dict):
        raise SafetyAgentError("Safety 模型输出不是 JSON 对象")

    try:
        return SafetyModelOutput.model_validate(raw)
    except ValidationError as exc:
        raise SafetyAgentError("Safety 模型输出字段不符合约定") from exc


async def _aclose(client: SafetyClient) -> None:
    """尽力关闭底层客户端；关闭失败不影响安全结论。

    兼容两种形态：``DeepSeekClient`` 把 ``AsyncOpenAI`` 放在 ``.client`` 上，
    而测试替身可能自己就有 ``close``。
    """
    inner = getattr(client, "client", None)
    close = getattr(inner, "close", None)
    if close is None:
        close = getattr(client, "close", None)
    if close is None:
        return
    try:
        await close()
    except Exception:  # noqa: BLE001 - 关闭失败不应改变判定结果
        pass


class SafetyAgent:
    """把一次用户发言判定为 :class:`SafetyVerdict`。

    ``client_factory`` 每次判定都会被调用一次，返回一个待关闭的客户端。
    """

    def __init__(
        self,
        client_factory: Callable[[], SafetyClient],
        *,
        timeout: float = DEFAULT_SAFETY_TIMEOUT_SECONDS,
        deployment_region: str | None = None,
        fallback_message: str = SAFETY_FALLBACK_MESSAGE,
    ) -> None:
        self._client_factory = client_factory
        self._timeout = timeout
        self._fallback = fallback_message
        self._hotlines = load_hotlines(deployment_region)
        # 白名单是全部已核实号码，与部署地区无关：只用于拦截模型编造的号码。
        self._allowed = allowed_hotline_numbers()

    @property
    def hotlines(self) -> list[str]:
        return [item.number for item in self._hotlines]

    async def judge(
        self,
        current_user_message: str,
        conversation_history: Sequence[tuple[str, str]] = (),
    ) -> SafetyVerdict:
        """判定一条用户发言的安全风险。**永不抛异常**，失败即 REVIEW。"""
        signals = scan_keywords(current_user_message)
        user_prompt = build_safety_user_prompt(
            current_user_message, conversation_history, signals)

        try:
            client = self._client_factory()
        except Exception:  # noqa: BLE001 - 配置/构造失败也必须走 REVIEW
            return assemble_verdict(
                output=None, status=ModelStatus.unavailable,
                extra_signals=signals, fallback_message=self._fallback)

        try:
            raw = await asyncio.wait_for(
                client.generate(SAFETY_SYSTEM_PROMPT, user_prompt),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return assemble_verdict(
                output=None, status=ModelStatus.timeout,
                extra_signals=signals, fallback_message=self._fallback)
        except DeepSeekClientError:
            return assemble_verdict(
                output=None, status=ModelStatus.unavailable,
                extra_signals=signals, fallback_message=self._fallback)
        except Exception:  # noqa: BLE001 - 安全判定不允许因未知异常而中断放行
            # 任何未预期的故障都必须走 REVIEW，绝不能让它冒泡成 500 而绕过安全判定。
            return assemble_verdict(
                output=None, status=ModelStatus.unavailable,
                extra_signals=signals, fallback_message=self._fallback)
        finally:
            await _aclose(client)

        try:
            output = parse_safety_content(raw)
        except SafetyAgentError:
            return assemble_verdict(
                output=None, status=ModelStatus.parse_error,
                extra_signals=signals, fallback_message=self._fallback)

        return assemble_verdict(
            output=output,
            status=ModelStatus.ok,
            hotlines=self.hotlines,
            allowed_hotlines=self._allowed,
            extra_signals=signals,
        )


def _client_factory() -> Callable[[], SafetyClient]:
    """构造一个「每次调用新建客户端」的工厂。

    温度固定 0（判定需要确定性），并覆写为更短的超时与更小的输出上限。
    """
    timeout = float(os.environ.get("SAFETY_LLM_TIMEOUT", DEFAULT_SAFETY_TIMEOUT_SECONDS))

    def create() -> SafetyClient:
        return DeepSeekClient(replace(
            load_deepseek_config(),
            temperature=0.0,
            max_tokens=DEFAULT_SAFETY_MAX_TOKENS,
            timeout=timeout,
        ))

    return create


def build_default_agent(deployment_region: str | None = None) -> SafetyAgent:
    """按环境变量构造默认 Safety Agent（不校验配置是否可用）。"""
    return SafetyAgent(_client_factory(), deployment_region=deployment_region)


_agent: SafetyAgent | None = None


def get_safety_agent() -> SafetyAgent:
    """进程内单例。"""
    global _agent
    if _agent is None:
        _agent = build_default_agent()
    return _agent


def set_safety_agent(agent: SafetyAgent | None) -> None:
    """测试注入入口。"""
    global _agent
    _agent = agent


def evaluate_safety(
    current_user_message: str,
    conversation_history: Sequence[tuple[str, str]] = (),
) -> SafetyVerdict:
    """同步封装，供当前同步的 FastAPI 端点使用。

    任何构造/配置问题同样返回 REVIEW 结论，而不是抛错放行。
    """
    try:
        agent = get_safety_agent()
    except Exception:  # noqa: BLE001 - 配置问题也必须走 REVIEW
        return assemble_verdict(
            output=None, status=ModelStatus.unavailable,
            extra_signals=scan_keywords(current_user_message),
            fallback_message=SAFETY_FALLBACK_MESSAGE)
    return asyncio.run(agent.judge(current_user_message, conversation_history))
