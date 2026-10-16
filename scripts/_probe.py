# -*- coding: utf-8 -*-
"""真实模型探针：**真的调用**模型，只额外记录次数、耗时与节点返回。

Phase 2.5 的验收脚本与演示脚本共用这里的插桩，避免两处各写一份而分家。

关键纪律（与生产代码一致）：``DialogueAgent`` 的客户端**每次调用新建并关闭**，
因为 ``asyncio.run`` 每轮新建事件循环，跨轮复用会踩
``RuntimeError: Event loop is closed``。插桩不能改变被测行为。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.dialogue_agent import DialogueAgent  # noqa: E402
from backend.llm.config import load_deepseek_config  # noqa: E402
from backend.llm.deepseek_client import DeepSeekClient  # noqa: E402

__all__ = [
    "CallLog", "CountingSafety", "CountingPolicy", "CountingDialogueAgent",
    "install_route_recorder", "level_of",
]


def level_of(verdict) -> str | None:
    """SafetyVerdict -> 风险等级字符串（枚举或字符串都兼容）。"""
    level = getattr(verdict, "risk_level", None)
    if level is None:
        return None
    return getattr(level, "value", str(level))


@dataclass
class CallLog:
    """一串调用的耗时记录。"""

    elapsed: list[float] = field(default_factory=list)

    def since(self, start: int) -> tuple[int, float]:
        window = self.elapsed[start:]
        return len(window), round(sum(window), 2)


class CountingSafety:
    """包住真实的 ``safety_runner.evaluate``。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.log = CallLog()
        self.verdicts: list = []

    def evaluate(self, text, history):
        started = time.perf_counter()
        try:
            verdict = self._inner(text, history)
        finally:
            self.log.elapsed.append(time.perf_counter() - started)
        self.verdicts.append(verdict)
        return verdict


class CountingPolicy:
    """包住真实的决策模型客户端（同步 httpx，本地 Qwen3-8B）。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.log = CallLog()

    def predict(self, history):
        started = time.perf_counter()
        try:
            return self._inner.predict(history)
        finally:
            self.log.elapsed.append(time.perf_counter() - started)


class CountingDialogueAgent:
    """真实 DialogueAgent + 每轮新建客户端 + 计时。"""

    def __init__(self) -> None:
        self.route_log = CallLog()
        self.reply_log = CallLog()
        self.routes: list[dict] = []

    async def route(self, request):
        client_ = DeepSeekClient(load_deepseek_config())
        started = time.perf_counter()
        try:
            decision = await DialogueAgent(client_).route(request)
        finally:
            self.route_log.elapsed.append(time.perf_counter() - started)
            await client_.client.close()
        self.routes.append({
            "need_decision": decision.need_decision,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "active_topic": request.active_topic,
            "active_topic_turns": request.active_topic_turns,
            "turn_count": request.turn_count,
        })
        return decision

    async def generate_reply(self, request):
        client_ = DeepSeekClient(load_deepseek_config())
        started = time.perf_counter()
        try:
            return await DialogueAgent(client_).generate_reply(request)
        finally:
            self.reply_log.elapsed.append(time.perf_counter() - started)
            await client_.client.close()


def install_route_recorder() -> list[dict]:
    """记录 ``dialogue_route`` 节点实际返回的状态（含后端强制原因）。

    必须在图第一次编译**之前**安装：``backend/graph/build.py`` 在编译时
    就把节点方法绑定进图了。
    """
    from backend.graph.nodes import TurnNodes

    original = TurnNodes.dialogue_route
    records: list[dict] = []

    def recording(self, state):
        result = original(self, state)
        records.append(dict(result))
        return result

    TurnNodes.dialogue_route = recording
    return records
