# -*- coding: utf-8 -*-
"""Phase 2.5：用**真实模型**验收 Dialogue 自主追问（不注入任何模型桩）。

与 ``scripts/compare_decision_budget.py`` 的区别：那个脚本把两个模型都换成桩，
只证明调度逻辑；本脚本**真的调用** DeepSeek（Safety / Router / Dialogue）
与本地 Qwen3-8B（Decision），回答的是"真实模型下这套调度表现如何"。

逐轮记录：用户输入、路由结论与理由、是否真的调用了决策模型、当前话题、
话题计数、最终回复、以及 Safety / Router / Decision / Dialogue 四类调用的
次数与耗时。**四类都要统计**——"Decision 调用减少"不等于"总模型调用减少"。

用法::

    python scripts/phase25_real_dialogue.py                    # 跑全部场景
    python scripts/phase25_real_dialogue.py --scenario A B     # 只跑指定场景
    python scripts/phase25_real_dialogue.py --out docs/x.md

所有用户输入均为**模拟学生输入**，不含任何真实学生数据。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from fastapi.testclient import TestClient  # noqa: E402

from _probe import (  # noqa: E402
    CountingDialogueAgent, CountingPolicy, CountingSafety, install_route_recorder,
    level_of,
)
from backend.api import chat  # noqa: E402
from backend.graph.engine import DIALOGUE_ENGINE_ENV, ENGINE_GRAPH  # noqa: E402
from backend.main import app  # noqa: E402
from backend.policy.client import get_policy_client  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------------
# 场景脚本（全部为模拟输入）
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, dict] = {
    "A": {
        "title": "睡眠话题逐步展开，验证 Dialogue 是否合理追问",
        "expect": "前几轮应由 Dialogue 自主追问，不每轮调用决策模型",
        "texts": [
            "最近总是睡不好，躺下要很久才睡得着",
            "大概一两点才能睡着吧，明明十一点就上床了",
            "半夜还会醒，醒了就翻来覆去",
            "白天上课一直打瞌睡，老师讲什么基本听不进去",
            "这种情况有一个多月了，最近越来越严重",
            "我也不知道为什么会这样",
        ],
    },
    "B": {
        "title": "用户主动要求换话题，验证是否请求决策切换",
        "expect": "用户表示不想聊之后，应出现新的决策调用并换到别的话题",
        "texts": [
            "晚上睡不好，白天没精神",
            "室友打呼噜，我戴耳塞也没什么用",
            "这个不太想聊了，能聊点别的吗",
            "其实我最近跟同学关系有点紧张",
            "感觉他们在背后说我，但我不确定",
            "所以我不太想去上课",
        ],
    },
    "C": {
        "title": "较长筛查过程，验证话题计数、覆盖率与收尾",
        "expect": "在 MAX_TURNS 以内靠覆盖率收尾，话题次数不超上限",
        "texts": [
            "最近心情一直不太好",
            "说不上来为什么，就是提不起劲",
            "以前喜欢打篮球，现在叫我去我也不想去",
            "吃饭也没什么胃口，随便吃点就饱了",
            "体重好像掉了三四斤",
            "上课注意力集中不了，看两行书就走神",
            "作业拖到最后一刻才写",
            "跟室友基本不怎么说话",
            "周末就在宿舍躺着刷手机",
            "身体上倒是没什么毛病，就是容易累",
            "早上起来还是觉得很困",
            "家里人不知道这些，我也不想说，怕他们担心",
            "有时候莫名其妙就想哭，但又哭不出来",
            "我也不知道该怎么办",
            "你觉得我这样正常吗",
            "我该做点什么吗",
        ],
    },
    "D": {
        "title": "风险表达，验证 Safety 仍然优先且不进普通图",
        "expect": "风险表达应落入安全分支，不产生任何决策/路由调用",
        "texts": [
            "最近压力很大，什么都做不好",
            "有时候真的觉得活着没什么意思",
        ],
    },
    "B2": {
        "title": "用户要求换话题（话题预算尚未用尽，路由不会被后端强制掩盖）",
        "expect": "第 2 轮应进入路由判断，Dialogue 报 user_wants_change 并触发决策",
        "texts": [
            "最近睡不好，白天没精神",
            "这个不太想聊了，能聊点别的吗",
            "那说说别的吧，我最近跟同学关系有点紧张",
        ],
    },
    "C2": {
        "title": "安全澄清后恢复普通评估，并靠覆盖率收尾",
        "expect": "澄清后用户明确否认风险 → 恢复普通图 → 覆盖 8/8 → topic_coverage 收尾",
        "texts": [
            "最近心情一直不太好",
            "说不上来为什么，就是提不起劲",
            "以前喜欢打篮球，现在叫我去我也不想去",
            "吃饭也没什么胃口，随便吃点就饱了",
            "体重好像掉了三四斤",
            "上课注意力集中不了，看两行书就走神",
            "作业拖到最后一刻才写",
            "跟室友基本不怎么说话",
            "周末就在宿舍躺着刷手机",
            "身体上倒是没什么毛病，就是容易累",
            "早上起来还是觉得很困",
            "家里人不知道这些，我也不想说，怕他们担心",
            "有时候莫名其妙就想哭，但又哭不出来",
            "没有，我没有那种想法，就是最近太累了",
        ],
    },
}


# ---------------------------------------------------------------------------
# 跑场景
# ---------------------------------------------------------------------------

def new_session() -> str:
    return client.post("/api/session").json()["session_id"]


def run_scenario(key: str, dialogue: CountingDialogueAgent, policy: CountingPolicy,
                 safety: CountingSafety, route_records: list[dict],
                 engine: str = ENGINE_GRAPH) -> dict:
    scenario = SCENARIOS[key]
    os.environ[DIALOGUE_ENGINE_ENV] = engine
    session_id = new_session()
    turns: list[dict] = []
    # 每个场景开始前清空路由记录，便于按轮切片。
    route_records.clear()

    for index, text in enumerate(scenario["texts"], start=1):
        s_safety = len(safety.log.elapsed)
        s_route = len(dialogue.route_log.elapsed)
        s_reply = len(dialogue.reply_log.elapsed)
        s_policy = len(policy.log.elapsed)
        s_nodes = len(route_records)

        started = time.perf_counter()
        try:
            response = client.post("/api/chat",
                                   json={"session_id": session_id, "text": text})
        except Exception as exc:  # noqa: BLE001
            turns.append({"turn": index, "user": text, "status": "EXC",
                          "error": f"{type(exc).__name__}: {exc}",
                          "elapsed_total": round(time.perf_counter() - started, 2)})
            break
        elapsed_total = time.perf_counter() - started

        safety_calls, safety_sec = safety.log.since(s_safety)
        route_calls, route_sec = dialogue.route_log.since(s_route)
        reply_calls, reply_sec = dialogue.reply_log.since(s_reply)
        decision_calls, decision_sec = policy.log.since(s_policy)
        node_records = route_records[s_nodes:]

        record: dict = {
            "turn": index,
            "user": text,
            "status": response.status_code,
            "elapsed_total": round(elapsed_total, 2),
            "safety_calls": safety_calls,
            "safety_sec": safety_sec,
            "safety_level": level_of(safety.verdicts[-1]) if safety.verdicts else None,
            "route_calls": route_calls,
            "route_sec": route_sec,
            "decision_calls": decision_calls,
            "decision_sec": decision_sec,
            "reply_calls": reply_calls,
            "reply_sec": reply_sec,
        }

        if node_records:
            node = node_records[-1]
            record["node_forced_reason"] = node.get("forced_reason")
            record["node_need_decision"] = node.get("need_decision")
            record["node_route_reason"] = node.get("route_reason")
        else:
            record["node_forced_reason"] = None
            record["node_need_decision"] = None
            record["node_route_reason"] = "（未进入路由：收尾轮或安全分支）"

        if dialogue.routes and route_calls:
            record["router"] = dialogue.routes[-1]

        if response.status_code != 200:
            record["error"] = response.json().get("error")
            turns.append(record)
            break

        body = response.json()
        state = client.get(f"/api/session/{session_id}").json()
        record.update({
            "reply": body["reply"],
            "next_strategy": body["next_strategy"],
            "current_stage": body["current_stage"],
            "assessment_ready": body["assessment_ready"],
            "completion_reason": body["completion_reason"],
            "active_topic": state["screening_progress"].get("pending_topic"),
            "internal_active_topic": state["screening_progress"].get("active_topic"),
            "topic_turns": body["screening_progress"]["topic_turns"],
            "visual_feedback": body["visual_feedback"]["reason"],
        })
        turns.append(record)

        if body["assessment_ready"]:
            break

    final_state = client.get(f"/api/session/{session_id}").json()
    return {
        "key": key,
        "engine": engine,
        "title": scenario["title"],
        "expect": scenario["expect"],
        "turns": turns,
        "final_progress": final_state["screening_progress"],
        "final_stage": final_state["current_stage"],
        "turn_count": final_state["turn_count"],
        "safety_halted": final_state.get("safety_halted"),
    }


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def fmt_seconds(value: float) -> str:
    return f"{value:.2f}s"


def render(result: dict) -> str:
    lines: list[str] = []
    lines.append(f"### 场景 {result['key']}（{result.get('engine', 'graph')}）：{result['title']}\n")
    lines.append(f"**预期**：{result['expect']}\n")
    lines.append("| 轮 | 用户输入 | Router need_decision | reason_code | 后端强制 | "
                 "是否调Decision | pending_topic | topic_turns | 耗时 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for turn in result["turns"]:
        if turn.get("status") != 200:
            lines.append(f"| {turn['turn']} | {turn['user']} | — | — | — | — | — | — | "
                         f"HTTP {turn.get('status')} {turn.get('error')} |")
            continue
        router = turn.get("router") or {}
        need = router.get("need_decision")
        need_text = "（未调用路由）" if need is None else ("**是**" if need else "否")
        code = router.get("reason_code") or "—"
        forced = turn.get("node_forced_reason") or "—"
        decision = "**是**" if turn["decision_calls"] else "否"
        lines.append(
            f"| {turn['turn']} | {turn['user']} | {need_text} | {code} | {forced} | "
            f"{decision} | {turn['active_topic']} | "
            f"{json.dumps(turn['topic_turns'], ensure_ascii=False)} | "
            f"{fmt_seconds(turn['elapsed_total'])} |")
    lines.append("")
    lines.append("逐轮回复与理由：\n")
    for turn in result["turns"]:
        if turn.get("status") != 200:
            continue
        router = turn.get("router") or {}
        lines.append(f"- **第 {turn['turn']} 轮** 用户：{turn['user']}")
        lines.append(f"  - 路由理由：{router.get('reason') or '（未调用路由）'}")
        lines.append(f"  - 助手回复：{turn['reply']}")
        lines.append(f"  - next_strategy={turn['next_strategy']}，"
                     f"分项耗时：Safety {turn['safety_sec']}s（{turn['safety_calls']} 次）/"
                     f"Router {turn['route_sec']}s（{turn['route_calls']} 次）/"
                     f"Decision {turn['decision_sec']}s（{turn['decision_calls']} 次）/"
                     f"Dialogue {turn['reply_sec']}s（{turn['reply_calls']} 次）")
    lines.append("")
    progress = result["final_progress"]
    lines.append(f"**收尾**：{result['turn_count']} 轮，stage={result['final_stage']}，"
                 f"话题计数={json.dumps(progress['topic_turns'], ensure_ascii=False)}，"
                 f"覆盖话题数={len(progress['topic_turns'])}/8，"
                 f"end_reason={progress['end_reason']}")
    lines.append("")
    return "\n".join(lines)


def summarize(results: list[dict]) -> str:
    lines = ["## 汇总统计（真实模型）\n"]
    lines.append("| 场景 | 引擎 | 轮数 | Safety 调用 | Router 调用 | Decision 调用 | "
                 "Dialogue 调用 | 模型总调用 | 总耗时 | 平均/轮 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    grand = {"safety": 0, "route": 0, "decision": 0, "reply": 0, "sec": 0.0}
    for result in results:
        turns = [t for t in result["turns"] if t.get("status") == 200]
        safety = sum(t["safety_calls"] for t in turns)
        route = sum(t["route_calls"] for t in turns)
        decision = sum(t["decision_calls"] for t in turns)
        reply = sum(t["reply_calls"] for t in turns)
        total_sec = sum(t["elapsed_total"] for t in turns)
        grand["safety"] += safety
        grand["route"] += route
        grand["decision"] += decision
        grand["reply"] += reply
        grand["sec"] += total_sec
        lines.append(
            f"| {result['key']} | {result.get('engine', 'graph')} | {len(turns)} | "
            f"{safety} | {route} | {decision} | "
            f"{reply} | **{safety + route + decision + reply}** | "
            f"{total_sec:.1f}s | {total_sec / max(len(turns), 1):.1f}s |")
    total_calls = grand["safety"] + grand["route"] + grand["decision"] + grand["reply"]
    total_turns = sum(len([t for t in r["turns"] if t.get("status") == 200])
                      for r in results)
    lines.append(
        f"| **合计** | — | {total_turns} | {grand['safety']} | {grand['route']} | "
        f"{grand['decision']} | {grand['reply']} | **{total_calls}** | "
        f"{grand['sec']:.1f}s | — |")
    lines.append("")
    lines.append("读法提醒：**Decision 调用次数少不等于模型总调用次数少。**"
                 "按需模式下每轮仍有 Safety + Dialogue，"
                 "只是把「决策」省下来了；Decision 是本地 Qwen3-8B，"
                 "其余三类是 DeepSeek。")
    lines.append("")
    return "\n".join(lines)


def analyze_router(results: list[dict]) -> str:
    lines = ["## 路由协议一致性检查\n"]
    conflicts: list[str] = []
    stats = {"route_called": 0, "need_true": 0, "need_false": 0, "forced": 0}
    codes: dict[str, int] = {}
    for result in results:
        for turn in result["turns"]:
            if turn.get("status") != 200:
                continue
            if turn["route_calls"]:
                stats["route_called"] += 1
                router = turn.get("router") or {}
                if router.get("need_decision"):
                    stats["need_true"] += 1
                else:
                    stats["need_false"] += 1
                code = router.get("reason_code") or "（空）"
                codes[code] = codes.get(code, 0) + 1
                # 语义冲突：要决策却说"继续当前话题"
                if router.get("need_decision") and code in ("continue_topic", "clarify"):
                    conflicts.append(
                        f"场景 {result['key']} 第 {turn['turn']} 轮："
                        f"need_decision=True 但 reason_code={code}"
                        f"（理由：{router.get('reason')}）")
                if not router.get("need_decision") and code in (
                        "topic_exhausted", "user_wants_change", "off_topic"):
                    conflicts.append(
                        f"场景 {result['key']} 第 {turn['turn']} 轮："
                        f"need_decision=False 但 reason_code={code}"
                        f"（理由：{router.get('reason')}）")
            if turn.get("node_forced_reason"):
                stats["forced"] += 1
    lines.append(f"- 进入路由判断的轮次：{stats['route_called']}")
    lines.append(f"- 其中 Dialogue 说“需要新决策”：{stats['need_true']}，"
                 f"说“不需要”：{stats['need_false']}")
    lines.append(f"- 被后端强制（未调用路由）：{stats['forced']}")
    lines.append(f"- reason_code 分布：{json.dumps(codes, ensure_ascii=False)}")
    lines.append("")
    if conflicts:
        lines.append("**发现语义不一致：**\n")
        for item in conflicts:
            lines.append(f"- {item}")
    else:
        lines.append("**未发现 need_decision 与 reason_code 的语义冲突。**")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", nargs="*", default=list(SCENARIOS),
                        help="要跑的场景 key，默认全部")
    parser.add_argument("--out", default="docs/phase25_real_dialogue_log.md")
    parser.add_argument("--engine", default=ENGINE_GRAPH, choices=["graph", "legacy"],
                        help="dialogue 引擎；legacy 用于真实对照")
    args = parser.parse_args()

    route_records = install_route_recorder()
    dialogue = CountingDialogueAgent()
    policy = CountingPolicy(get_policy_client())
    safety = CountingSafety(chat.safety_runner.evaluate)

    chat.dialogue_manager._dialogue_agent = dialogue
    chat.dialogue_manager._policy = policy
    chat.safety_runner.evaluate = safety.evaluate

    print(f"真实模型验收：引擎={args.engine}，场景 {args.scenario}")
    print("（DeepSeek 负责 Safety/Router/Dialogue，本地 Qwen3-8B 负责 Decision）\n")

    results = []
    for key in args.scenario:
        print(f"--- 场景 {key}：{SCENARIOS[key]['title']}")
        result = run_scenario(key, dialogue, policy, safety, route_records,
                              engine=args.engine)
        results.append(result)
        closed = result["final_progress"]["end_reason"]
        print(f"    完成 {result['turn_count']} 轮，end_reason={closed}，"
              f"覆盖 {len(result['final_progress']['topic_turns'])}/8 话题，"
              f"stage={result['final_stage']}")
        for turn in result["turns"]:
            if turn.get("status") != 200:
                print(f"    第 {turn['turn']} 轮非 200：{turn.get('error')}")
        print()

    body = "\n".join([
        f"# Phase 2.5 真实模型对话验收记录（{args.engine} 引擎）\n",
        "> 本文件由 `scripts/phase25_real_dialogue.py` 自动生成。"
        "所有用户输入均为**模拟学生输入**，不含任何真实学生数据。\n",
        f"> 对话/路由/安全模型：`deepseek-flash`；决策模型：本地 Ollama "
        f"`policy-qwen3-8b:latest`；`DIALOGUE_ENGINE={args.engine}`。\n",
        summarize(results),
        analyze_router(results),
        "## 逐轮记录\n",
        *[render(result) for result in results],
    ])
    out = ROOT / args.out
    out.write_text(body, encoding="utf-8")
    print(f"报告已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
