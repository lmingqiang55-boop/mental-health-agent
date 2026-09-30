# -*- coding: utf-8 -*-
"""Dialogue Agent 数据结构的第 1 步最小验证脚本。

只验证 schema 能否正常实例化与解析，不涉及任何 LLM / API / 决策 / 记忆逻辑。

必填约定：
- conversation_history 必填（首次对话显式传 []）
- decision 必填
- current_user_input 必填
- user_memory 可选（可省略，也可传 {}）

运行：python scripts/verify_dialogue_schema.py
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# 允许以脚本方式直接运行（把项目根目录加入 sys.path）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError  # noqa: E402

from backend.models.dialogue import (  # noqa: E402
    DialogueAgentRequest,
    DialogueAgentResponse,
    DialogueCurrentUserInput,
    DialogueDecision,
    DialogueHistoryMessage,
    DialogueUserMemory,
    DialogueVisual,
)

FAILURES: List[str] = []


def check(name: str, condition: bool) -> None:
    """打印一条检查结果，失败时记录到全局失败列表。"""
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILURES.append(name)


def expects_validation_error(payload: Dict[str, Any], missing_field: str) -> bool:
    """断言该 payload 会抛 ValidationError，且错误定位到指定字段。"""
    try:
        DialogueAgentRequest.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors()
        located = any(err.get("loc") == (missing_field,) for err in errors)
        print(f"        -> 已抛 ValidationError，字段定位正确: {located}")
        print(f"        -> {errors[0].get('msg')} (loc={errors[0].get('loc')})")
        return located
    return False


def main() -> int:
    print("=" * 60)
    print("Dialogue Agent schema 验证")
    print("=" * 60)

    # ============ A / B: 必填三件套齐全，省略 user_memory ============
    print("\n-- A / B: 完整必填输入，且省略 user_memory --")
    payload_a: Dict[str, Any] = {
        "conversation_history": [],
        "decision": {"actions": ["情绪"], "topic": "情绪"},
        "current_user_input": {"text": "最近感觉挺累的"},
    }
    req_a = DialogueAgentRequest.model_validate(payload_a)
    check("A: conversation_history=[] 解析成功", req_a.conversation_history == [])
    check("A: current_user_input.text 正确", req_a.current_user_input.text == "最近感觉挺累的")
    check("A: decision.actions 正确", req_a.decision.actions == ["情绪"])
    check("A: decision.topic 正确", req_a.decision.topic == "情绪")
    check("A: decision.reason 缺省为 None", req_a.decision.reason is None)
    check("B: user_memory 不传时自动生成", isinstance(req_a.user_memory, DialogueUserMemory))
    check("B: 自动生成的 user_memory.facts == []", req_a.user_memory.facts == [])
    check("B: 自动生成的 user_memory.preferences == []", req_a.user_memory.preferences == [])
    check(
        "B: 自动生成的 user_memory.important_events == []",
        req_a.user_memory.important_events == [],
    )
    check(
        "B: 自动生成的 previous_assessment_summary is None",
        req_a.user_memory.previous_assessment_summary is None,
    )
    check("B: 自动生成的 user_memory.extra == {}", req_a.user_memory.extra == {})

    # ============ C: user_memory 显式传 {} ============
    print("\n-- C: user_memory 传 {} --")
    req_c = DialogueAgentRequest.model_validate({**payload_a, "user_memory": {}})
    check("C: user_memory={} 解析成功", isinstance(req_c.user_memory, DialogueUserMemory))
    check("C: user_memory={} 后 facts == []", req_c.user_memory.facts == [])
    check("C: user_memory={} 后 extra == {}", req_c.user_memory.extra == {})
    check(
        "C: user_memory={} 与省略 user_memory 等价",
        req_c.model_dump() == req_a.model_dump(),
    )

    # ============ D: 缺少 decision ============
    print("\n-- D: 缺少 decision --")
    check(
        "D: 缺少 decision 抛 ValidationError",
        expects_validation_error(
            {
                "conversation_history": [],
                "current_user_input": {"text": "最近感觉挺累的"},
            },
            "decision",
        ),
    )

    # ============ E: 缺少 conversation_history ============
    print("\n-- E: 缺少 conversation_history --")
    check(
        "E: 缺少 conversation_history 抛 ValidationError",
        expects_validation_error(
            {
                "decision": {"actions": ["情绪"], "topic": "情绪"},
                "current_user_input": {"text": "最近感觉挺累的"},
            },
            "conversation_history",
        ),
    )

    # ============ F: 缺少 current_user_input ============
    print("\n-- F: 缺少 current_user_input --")
    check(
        "F: 缺少 current_user_input 抛 ValidationError",
        expects_validation_error(
            {
                "conversation_history": [],
                "decision": {"actions": ["情绪"], "topic": "情绪"},
            },
            "current_user_input",
        ),
    )

    # ============ 附加: actions 至少 1 项 ============
    print("\n-- 附加: decision.actions 至少 1 项 --")
    empty_actions_rejected = False
    try:
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": [],
                "decision": {"actions": [], "topic": "情绪"},
                "current_user_input": {"text": "最近感觉挺累的"},
            }
        )
    except ValidationError:
        empty_actions_rejected = True
    check("actions=[] 会被拒绝", empty_actions_rejected)

    missing_actions_rejected = False
    try:
        DialogueDecision.model_validate({"topic": "情绪"})
    except ValidationError:
        missing_actions_rejected = True
    check("decision 缺少 actions 会被拒绝", missing_actions_rejected)

    # ============ 完整输入: visual 可选字段与 extra 扩展 ============
    print("\n-- 完整输入: visual 可选字段与 extra 扩展 --")
    full_payload: Dict[str, Any] = {
        "conversation_history": [
            {"role": "user", "content": "我最近总是睡不着"},
            {
                "role": "assistant",
                "content": "听起来这段时间挺难熬的，愿意多说说吗？",
            },
            {
                "role": "user",
                "content": "闭上眼睛就开始想工作的事",
                "visual": {
                    "valence": -0.42,
                    "arousal": 0.71,
                    "engagement": 0.55,
                    "extra": {"head_pose": "down", "gaze_aversion": 0.3},
                },
            },
        ],
        "user_memory": {
            "facts": ["是一名大二学生"],
            "preferences": ["喜欢被直接提问"],
            "important_events": ["上周和室友发生过争执"],
            "previous_assessment_summary": "轻度焦虑倾向，睡眠质量偏低",
            "extra": {"source": "placeholder"},
        },
        "decision": {
            "actions": ["共情安慰", "当前话题从睡眠转到食欲"],
            "topic": "食欲",
            "reason": "睡眠话题已达到次数限制",
        },
        "current_user_input": {
            "text": "这几天也没什么胃口",
            "visual": {"valence": -0.3, "arousal": None, "engagement": 0.4},
        },
    }
    req_full = DialogueAgentRequest.model_validate(full_payload)

    check("历史对话条数为 3", len(req_full.conversation_history) == 3)
    check(
        "assistant 消息 visual 为 None",
        req_full.conversation_history[1].visual is None,
    )
    user_visual = req_full.conversation_history[2].visual
    check("user 消息 visual 绑定成功", isinstance(user_visual, DialogueVisual))
    check("visual.valence 解析正确", user_visual is not None and user_visual.valence == -0.42)
    check(
        "visual.extra 保留扩展字段",
        user_visual is not None and user_visual.extra.get("head_pose") == "down",
    )
    check(
        "visual 已提供字段解析正确",
        user_visual is not None and user_visual.arousal == 0.71,
    )
    check("user_memory.facts 解析正确", req_full.user_memory.facts == ["是一名大二学生"])
    check(
        "user_memory.previous_assessment_summary 解析正确",
        req_full.user_memory.previous_assessment_summary == "轻度焦虑倾向，睡眠质量偏低",
    )
    check(
        "user_memory.extra 保留扩展字段",
        req_full.user_memory.extra.get("source") == "placeholder",
    )
    check("decision.topic 解析正确", req_full.decision.topic == "食欲")
    check("decision.actions 条数为 2", len(req_full.decision.actions) == 2)
    check("decision.reason 解析正确", req_full.decision.reason == "睡眠话题已达到次数限制")
    check("current_user_input.text 解析正确", req_full.current_user_input.text == "这几天也没什么胃口")
    check(
        "current_user_input.visual 部分字段为 None 可接受",
        req_full.current_user_input.visual is not None
        and req_full.current_user_input.visual.arousal is None,
    )

    # ============ 可变默认值隔离性 ============
    print("\n-- 可变默认值隔离性 --")
    i1 = DialogueAgentRequest.model_validate(payload_a)
    i2 = DialogueAgentRequest.model_validate(payload_a)
    i1.user_memory.facts.append("不应影响 i2")
    i1.decision.actions.append("不应影响 i2")
    i1.conversation_history.append(
        DialogueHistoryMessage(role="user", content="不应影响 i2")
    )
    check("两个实例的 user_memory 互不共享", i2.user_memory.facts == [])
    check("两个实例的 decision.actions 互不共享", i2.decision.actions == ["情绪"])
    check("两个实例的 conversation_history 互不共享", i2.conversation_history == [])

    # ============ 输出结构 ============
    print("\n-- 输出结构 --")
    resp = DialogueAgentResponse(reply="没胃口这件事，是最近才有，还是已经持续一阵子了？")
    check("DialogueAgentResponse.reply 正常", resp.reply.endswith("？"))
    check("响应 JSON 只含 reply 字段", set(resp.model_dump().keys()) == {"reply"})

    # ============ 其它结构约束 ============
    print("\n-- 其它结构约束 --")
    schema = DialogueAgentRequest.model_json_schema()
    check("可导出 JSON Schema", "$defs" in schema and "DialogueVisual" in schema["$defs"])
    check(
        "schema.required 恰为三件套",
        set(schema.get("required", []))
        == {"conversation_history", "decision", "current_user_input"},
    )

    rejected = False
    try:
        DialogueHistoryMessage(role="system", content="x")
    except Exception:
        rejected = True
    check("非法 role 会被校验拒绝", rejected)

    dumped = req_full.model_dump()
    reloaded = DialogueAgentRequest.model_validate(dumped)
    check("model_dump -> model_validate 往返一致", reloaded.model_dump() == dumped)

    print("-" * 60)
    print("A 用例解析结果（model_dump, ensure_ascii=False）:")
    print(json.dumps(req_a.model_dump(), ensure_ascii=False, indent=2))

    print("=" * 60)
    if FAILURES:
        print(f"结果：失败 {len(FAILURES)} 项 -> {FAILURES}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
