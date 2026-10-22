# -*- coding: utf-8 -*-
"""Phase 4 真实模型验证：Dialogue 到底会输出几条消息。

**不伪造任何输出**：本脚本把模型返回的**原始文本**和解析后的 ``messages``
一起打印，因此"模型自己分了段"与"后端清理了什么"一眼可辨。

用法::

    python scripts/phase4_messages_real.py
    python scripts/phase4_messages_real.py --out docs/archive/dialogue/phase4_message_split_log.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from fastapi.testclient import TestClient  # noqa: E402

from backend.agents.dialogue_agent import parse_reply_messages  # noqa: E402
from backend.api import chat  # noqa: E402
from backend.core import dialogue_manager as dialogue_manager_module  # noqa: E402
from backend.graph.engine import DIALOGUE_ENGINE_ENV, ENGINE_GRAPH  # noqa: E402
from backend.llm.config import load_deepseek_config  # noqa: E402
from backend.llm.deepseek_client import DeepSeekClient  # noqa: E402
from backend.main import app  # noqa: E402
from backend.policy.client import get_policy_client  # noqa: E402
from _probe import CountingPolicy, CountingSafety, install_route_recorder, create_demo_session  # noqa: E402

client = TestClient(app)

#: 三组预设学生输入。**刻意不做任何"为了让模型多分几条"的引导**——
#: 条数完全由模型按内容决定，本脚本只如实记录。
SCENARIOS: list[dict] = [
    {
        "key": "S1",
        "title": "简短开场：只有一句情绪陈述",
        "expect": "内容很少，1 条最自然",
        "texts": [
            "最近心情一直不太好",
            "说不上来为什么，就是提不起劲",
        ],
    },
    {
        "key": "S2",
        "title": "具体症状：需要先接住再追问",
        "expect": "共情 + 追问，2 条比较自然",
        "texts": [
            "最近总是睡不好，躺下要很久才睡得着",
            "大概一两点才能睡着吧，明明十一点就上床了",
        ],
    },
    {
        "key": "S3",
        "title": "信息密集：一次说了好几件事",
        "expect": "内容较多，可能到 3 条",
        "texts": [
            "我最近什么都不想做，以前喜欢打篮球现在也不去了，吃饭也没胃口，上课也听不进去",
            "跟室友也基本不说话，周末就在宿舍躺着",
        ],
    },
    {
        "key": "S4",
        "title": "一口气列出多重困扰（最可能自然分到 3 条）",
        "expect": "分别回应不同困扰时，3 条才说得完",
        "texts": [
            "上课完全听不进去，作业拖到最后一天才写，晚上睡不着白天又困，"
            "跟室友也基本不说话，周末就在宿舍躺着，我也不知道自己怎么了",
            "就是这样，一天天混过去",
        ],
    },
]


class RecordingClient:
    """包住真实 DeepSeek 客户端，把**原始返回文本**留一份用于取证。"""

    def __init__(self, inner: DeepSeekClient, sink: list[str]) -> None:
        self._inner = inner
        self._sink = sink
        # _generate_reply 会调用 client.client.close()，必须指向真实 SDK 客户端。
        self.client = inner.client

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        raw = await self._inner.generate(
            system_prompt=system_prompt, user_prompt=user_prompt)
        self._sink.append(raw)
        return raw


def install_recorder() -> list[str]:
    """让 dialogue_manager 造出来的客户端把原始文本记下来。

    注意要打在**模块**全局上：``_generate_reply`` 里的 ``DeepSeekClient`` 是按模块
    全局名解析的，打到 ``chat.dialogue_manager`` 这个实例上是无效的。
    """
    raw_outputs: list[str] = []
    original = dialogue_manager_module.DeepSeekClient

    def factory(config):
        return RecordingClient(original(config), raw_outputs)

    dialogue_manager_module.DeepSeekClient = factory
    return raw_outputs


def new_session() -> str:
    return create_demo_session(client)


def looks_cleaned(raw: str, messages: list[str]) -> str:
    """解析是否对原文做了清理（去围栏/空行/列表符号）。"""
    if raw.strip() == "\n".join(messages):
        return "—"
    notes = []
    if "-" in raw[:3] or re.match(r"^\s*\d+\s*[.、)]", raw):
        notes.append("去列表符号")
    if "\n\n" in raw:
        notes.append("去空行")
    if raw.strip().startswith("```"):
        notes.append("去代码围栏")
    return "、".join(notes) or "仅去首尾空白"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/archive/dialogue/phase4_message_split_log.md")
    parser.add_argument("--engine", default=ENGINE_GRAPH)
    args = parser.parse_args()

    os.environ[DIALOGUE_ENGINE_ENV] = args.engine
    route_records = install_route_recorder()
    policy = CountingPolicy(get_policy_client())
    safety = CountingSafety(chat.safety_runner.evaluate)
    chat.dialogue_manager._policy = policy
    chat.safety_runner.evaluate = safety.evaluate
    raw_outputs = install_recorder()

    print(f"Phase 4 真实模型验证：引擎={args.engine}")
    print("（DeepSeek 负责 Safety/Router/Dialogue，本地 Qwen3-8B 负责 Decision）\n")

    sections: list[str] = []
    distribution: dict[int, int] = {}

    for scenario in SCENARIOS:
        print(f"--- {scenario['key']}：{scenario['title']}（预期：{scenario['expect']}）")
        session_id = new_session()
        route_records.clear()
        turns: list[dict] = []

        for index, text in enumerate(scenario["texts"], start=1):
            before = len(raw_outputs)
            s_policy = len(policy.log.elapsed)
            started = time.perf_counter()
            response = client.post("/api/chat",
                                   json={"session_id": session_id, "text": text})
            elapsed = time.perf_counter() - started
            body = response.json()
            if response.status_code != 200:
                print(f"    HTTP {response.status_code}: {body}")
                break

            new_raw = raw_outputs[before:]
            reply_raw = new_raw[-1] if new_raw else ""
            messages = body["messages"]
            decision_calls, decision_sec = policy.log.since(s_policy)
            distribution[len(messages)] = distribution.get(len(messages), 0) + 1
            print(f"  第{index}轮 -> {len(messages)} 条"
                  f"（Safety {1} / Decision {decision_calls} / "
                  f"{elapsed:.2f}s）")
            for order, message in enumerate(messages, start=1):
                print(f"      [{order}] {message}")

            turns.append({
                "turn": index, "user": text, "raw": reply_raw,
                "messages": messages, "reply": body["reply"],
                "cleaned": looks_cleaned(reply_raw, messages),
                "next_strategy": body["next_strategy"],
                "decision_calls": decision_calls, "decision_sec": decision_sec,
                "safety": body.get("safety") or {},
                "elapsed": round(elapsed, 2),
                "assessment_ready": body["assessment_ready"],
                "completion_reason": body["completion_reason"],
            })

        lines = [f"### {scenario['key']}：{scenario['title']}\n",
                 f"预期：{scenario['expect']}\n",
                 "| 轮 | 条数 | 解析清理 | 本轮 next_strategy | Decision 调用 | 耗时 |",
                 "| --- | --- | --- | --- | --- | --- |"]
        for turn in turns:
            lines.append(
                f"| {turn['turn']} | **{len(turn['messages'])}** | {turn['cleaned']} | "
                f"{turn['next_strategy']} | {turn['decision_calls']} | "
                f"{turn['elapsed']}s |")
        lines.append("")
        for turn in turns:
            lines.append(f"**第 {turn['turn']} 轮**　模拟学生：{turn['user']}\n")
            lines.append("模型原始返回（`\\n` 为真实换行）：\n")
            lines.append("```text")
            lines.append(turn["raw"])
            lines.append("```")
            lines.append(f"\n解析为 {len(turn['messages'])} 条消息：\n")
            for order, message in enumerate(turn["messages"], start=1):
                lines.append(f"{order}. {message}")
            lines.append(f"\n- `reply`（换行拼接，向后兼容）：{json.dumps(turn['reply'], ensure_ascii=False)}")
            lines.append(f"- 解析清理：{turn['cleaned']}")
            lines.append("")
        sections.append("\n".join(lines))

    headline = "、".join(f"{count} 条 × {times} 轮"
                        for count, times in sorted(distribution.items()))
    total = sum(distribution.values())
    body = "\n".join([
        "# Phase 4 真实模型分段验证（Dialogue 输出 1~3 条消息）\n",
        "> 由 `scripts/phase4_messages_real.py` 生成。三组预设学生输入均为**模拟台词**，"
        "不含任何真实学生数据。\n",
        "> 对话/路由/安全模型：`deepseek-flash`；决策模型：本地 Ollama "
        "`policy-qwen3-8b:latest`；`DIALOGUE_ENGINE=graph`。\n",
        "> 条数**完全由模型按内容决定**，脚本没有为了凑条数做任何引导；"
        "模型原始返回与解析结果都逐字保留，未做改写。\n",
        f"\n**本轮实际分布**：共 {total} 轮，{headline}。\n",
        *sections,
        "## 读法提醒\n",
        "- `reply` 恒等于 `messages` 用换行拼接，因此旧的单字段调用方不受影响；",
        "- 前端只按 `messages` 渲染气泡，`reply` 不再单独渲染，所以不会重复显示；",
        "- 解析只在**格式层**清理（空行、列表符号、代码围栏），不按标点切分句子；",
        "- 条数上限为 3：超出时合并而不是截断，正文一个字都不会少。\n",
    ])

    out = ROOT / args.out
    out.write_text(body, encoding="utf-8")
    print(f"\n实际分布：共 {total} 轮，{headline}")
    print(f"记录已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
