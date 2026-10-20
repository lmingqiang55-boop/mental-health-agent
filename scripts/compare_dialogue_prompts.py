"""Compare dialogue prompts on synthetic inputs; network calls require --live.

Example:
    python scripts/compare_dialogue_prompts.py --baseline-ref a0dea57
    python scripts/compare_dialogue_prompts.py --baseline-ref a0dea57 --live
    python scripts/compare_dialogue_prompts.py --baseline-ref a0dea57 --live --candidate-only --case 简短求助

This isolates one generation per prompt/input. It does not run Safety, policy,
router, or the dialogue rewrite gate, and is not an end-to-end assessment test.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agents.dialogue_agent import parse_reply_messages  # noqa: E402
from backend.llm.config import load_deepseek_config  # noqa: E402
from backend.llm.deepseek_client import DeepSeekClient  # noqa: E402
from backend.models.dialogue import DialogueAgentRequest  # noqa: E402
from backend.prompts import dialogue_prompt  # noqa: E402


def case(name, topic, text, *, history=(), goal, **extra):
    return {
        "name": name, "review_goal": goal,
        "request": DialogueAgentRequest.model_validate({
            "conversation_history": [
                {"role": role, "content": content} for role, content in history],
            "decision": {"actions": [topic], "topic": topic},
            "current_user_input": {"text": text}, **extra,
        }),
    }


CASES = [
    case("情绪开场", "情绪", "最近心里总是堵得慌。",
         goal="回应具体感受，避免只有频率问句或泛泛安慰。"),
    case("短句反问", "睡眠", "这算严重吗？", history=[
        ("user", "最近夜里老醒，已经十来天了。"),
        ("assistant", "白天上课会受影响吗？")],
         goal="先回应轻重的担心，不诊断、不直接跳过反问。"),
    case("跨轮承接", "精神状态", "老师讲课我经常跟不上。", history=[
        ("user", "这阵子总到凌晨两点才睡，早上六点多就起了。"),
        ("assistant", "白天在学校感觉怎么样？")],
         goal="自然使用睡眠和上课的真实上下文，不断言因果或重复问睡眠时长。"),
    case("纠正重复提问", "睡眠", "刚才已经告诉你啦。", history=[
        ("assistant", "这样睡不好大概有多久了？"),
        ("user", "快一个月了。"),
        ("assistant", "大概持续多久了？")],
         goal="承认问重复，采用一个月的答案，补问另一项信息。"),
    case("简短求助", "精神状态", "现在怎么办？", history=[
        ("user", "作业堆了好多，打开本子就不知道先写什么。"),
        ("assistant", "最难的是开始动笔，还是写着写着就停了？")],
         goal="先回应具体求助，至多给一个可选择的小建议，避免只有新问题。"),
    case("尊重拒答", "社会功能", "这部分我不想聊了。",
         goal="接纳拒绝，不变着问法继续追问被拒绝的内容。"),
    case("不确定回答", "睡眠", "说不准。", history=[
        ("assistant", "最近入睡一般要花多久？")],
         goal="帮助把原问题问具体，允许不知道，不当成否认或强行换话题。"),
    case("明确的信息短答", "睡眠", "一周四五次。", history=[
        ("user", "睡着后总会醒。"),
        ("assistant", "最近一周，大概有几晚会这样？")],
         goal="采用已回答的频率，简洁追问尚缺的信息，不机械追加安慰。"),
    case("允许的视觉关切", "情绪", "最近有些提不起劲。", visual_observation="sad",
         goal="只用被允许的外观线索，试探表达，不把表情当内心事实。"),
    case("有承接的收尾", "结束本次筛查", "差不多就是这些了。", history=[
        ("user", "这一个月经常半夜醒，白天上课也容易走神。"),
        ("assistant", "和朋友相处呢？"),
        ("user", "还好，朋友会约我一起吃饭。")], finish_screening=True,
         goal="简短承接真实信息，提示生成结果，没有新问题或已确诊表述。"),
]


def baseline_module(ref: str) -> ModuleType:
    source = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "show",
         f"{ref}:backend/prompts/dialogue_prompt.py"], cwd=ROOT, check=True,
        capture_output=True, encoding="utf-8",
    ).stdout
    module = ModuleType("baseline_dialogue_prompt")
    exec(compile(source, f"{ref}:dialogue_prompt.py", "exec"), module.__dict__)
    return module


async def compare(args, baseline, cases):
    config = replace(load_deepseek_config(), timeout=25.0)
    client = DeepSeekClient(config)
    client.client.max_retries = 0
    semaphore = asyncio.Semaphore(2)
    variants = (("candidate", dialogue_prompt),) if args.candidate_only else (
        ("baseline", baseline), ("candidate", dialogue_prompt))
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_inputs_only": True, "baseline_ref": args.baseline_ref,
        "model": config.model, "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "scope": "single generation; no Safety/policy/router/rewrite",
        "requested_cases": [item["name"] for item in cases],
        "requested_variants": [name for name, _ in variants],
        "prompts": {name: {
            "sha256": hashlib.sha256(module.DIALOGUE_AGENT_SYSTEM_PROMPT.encode()).hexdigest(),
            "system_chars": len(module.DIALOGUE_AGENT_SYSTEM_PROMPT),
        } for name, module in (("baseline", baseline), ("candidate", dialogue_prompt))},
        "results": [],
    }
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    async def generate(item, variant, module):
        async with semaphore:
            start = time.monotonic()
            result = {
                "case": item["name"], "variant": variant,
                "review_goal": item["review_goal"],
                "request": item["request"].model_dump(mode="json"),
            }
            try:
                async with asyncio.timeout(30):
                    reply = await client.generate(
                        module.DIALOGUE_AGENT_SYSTEM_PROMPT,
                        module.build_dialogue_user_prompt(item["request"]),
                    )
                messages = parse_reply_messages(reply)
                result.update(reply=reply, message_count=len(messages),
                              question_marks=len(re.findall(r"[？?]", reply)))
            except Exception as exc:
                # Never record exception bodies, which can contain request secrets.
                result["error_type"] = type(exc).__name__
            result["elapsed_seconds"] = round(time.monotonic() - start, 2)
            return result

    try:
        tasks = [generate(item, variant, module) for item in cases
                 for variant, module in variants]
        for task in asyncio.as_completed(tasks):
            result = await task
            report["results"].append(result)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            status = result.get("error_type", "ok")
            print(f"{len(report['results'])}/{len(tasks)} {result['case']} {result['variant']} {status}", flush=True)
    finally:
        await client.client.close()
    print(f"Saved {output}")
    return int(any("error_type" in row for row in report["results"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--live", action="store_true", help="Make real API calls using synthetic inputs (default: 20)")
    parser.add_argument("--case", action="append", choices=[item["name"] for item in CASES],
                        help="Only run the named case; repeat to select several")
    parser.add_argument("--candidate-only", action="store_true", help="Only generate the current prompt for a focused retest")
    parser.add_argument("--out", type=Path, default=ROOT / ".codex-runtime/dialogue_prompt_comparison.json")
    args = parser.parse_args()
    baseline = baseline_module(args.baseline_ref)
    cases = [item for item in CASES if not args.case or item["name"] in args.case]
    for item in cases:
        for module in (baseline, dialogue_prompt):
            assert module.build_dialogue_user_prompt(item["request"])
    if not args.live:
        print(f"Validated {len(cases)} synthetic cases and both prompt builders; no API calls.")
        return 0
    return asyncio.run(compare(args, baseline, cases))


if __name__ == "__main__":
    raise SystemExit(main())
