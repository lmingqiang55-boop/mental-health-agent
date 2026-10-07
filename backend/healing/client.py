"""Reuse the existing DeepSeek connection, with bounded JSON generation."""

import asyncio
import json
from dataclasses import replace
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from backend.llm.config import load_deepseek_config
from backend.llm.deepseek_client import DeepSeekClient

T = TypeVar("T", bound=BaseModel)
MODEL_CALLS: ContextVar[list | None] = ContextVar("healing_model_calls", default=None)


def measure_model_calls(method):
    """Per-request accounting; shared clients cannot mix simultaneous sessions."""
    @wraps(method)
    async def measured(*args, **kwargs):
        calls = []
        previous = next((value for value in (*args, *kwargs.values())
                         if hasattr(value, "audit") and hasattr(value, "turn_count")), None)
        previous_audit_count = len(previous.audit) if previous is not None else 0
        token = MODEL_CALLS.set(calls)
        started = perf_counter()
        try:
            state = await method(*args, **kwargs)
            if len(state.audit) <= previous_audit_count:
                state.audit.append({"phase": "state_transition", "turn": state.turn_count})
            state.audit[-1]["model_calls"] = calls
            state.audit[-1]["total_ms"] = (perf_counter()-started)*1000
            return state
        finally:
            MODEL_CALLS.reset(token)
    return measured


class HealingUnavailable(RuntimeError):
    """Safe service error; never contains prompts, responses or API credentials."""


class HealingJSONClient:
    async def generate(self, system: str, payload: dict, schema: type[T], *, max_tokens=2000) -> T:
        try:
            config = replace(load_deepseek_config(), max_tokens=max_tokens, timeout=45., temperature=.2)
            client = DeepSeekClient(config)
            # SDK retries are also bounded by the outer deadline.
            client.client.max_retries = 0
            prompt = json.dumps(payload, ensure_ascii=False)
            try:
                async with asyncio.timeout(50):
                    for attempt in range(2):
                        started = perf_counter()
                        text = await client.generate(system, prompt)
                        calls = MODEL_CALLS.get()
                        if calls is not None:
                            calls.append({"schema": schema.__name__, "model": config.model,
                                "elapsed_ms": (perf_counter()-started)*1000, "usage": client.last_usage})
                        cleaned = text.strip()
                        if cleaned.startswith("```"):
                            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                        try:
                            return schema.model_validate_json(cleaned)
                        except (ValidationError, ValueError):
                            if attempt:
                                raise HealingUnavailable("支持服务返回格式不合格") from None
                            prompt = json.dumps({"input": payload, "repair": "上次 JSON 格式不合格，请严格按输出协议重写。"},
                                                ensure_ascii=False)
            finally:
                await client.client.close()
        except HealingUnavailable:
            raise
        except Exception as exc:
            raise HealingUnavailable(f"支持服务暂时不可用 ({type(exc).__name__})") from None
