# -*- coding: utf-8 -*-
"""Dialogue Agent Prompt 构造的第 2 步验证脚本。

只验证 Prompt 文本是否正确组装，**不调用任何 LLM**，也不涉及 API / 决策 / 记忆逻辑。

运行：python scripts/verify_dialogue_prompt.py
"""

import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.models.dialogue import DialogueAgentRequest  # noqa: E402
from backend.prompts.dialogue_prompt import (  # noqa: E402
    DIALOGUE_AGENT_SYSTEM_PROMPT,
    build_dialogue_user_prompt,
)

FAILURES: List[str] = []


def check(name: str, condition: bool) -> None:
    """打印一条检查结果，失败时记录下来。"""
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        FAILURES.append(name)


def assert_all_true(name: str, checks: Dict[str, bool]) -> None:
    """逐项打印子检查，并汇总成一条总检查。"""
    print(f"    · {name}")
    for label, ok in checks.items():
        mark = "OK  " if ok else "MISS"
        print(f"        [{mark}] {label}")
    check(name, all(checks.values()))


SLEEP_HISTORY: List[Dict[str, Any]] = [
    {"role": "user", "content": "我最近总是睡不好，躺下要很久才能睡着"},
    {
        "role": "assistant",
        "content": "听起来这段时间挺难熬的。是入睡困难，还是睡着之后容易醒呢？",
    },
    {"role": "user", "content": "主要是睡不着，脑子里一直在想事情"},
    {
        "role": "assistant",
        "content": "睡前脑子停不下来确实很消耗人。这种情况大概持续多久了？",
    },
]


def main() -> int:
    print("=" * 64)
    print("Dialogue Agent Prompt 构造验证（不调用任何 LLM）")
    print("=" * 64)

    # ================= 场景 A =================
    print("\n-- 场景 A: actions=['睡眠'], topic='睡眠', 首轮对话 --")
    prompt_a = build_dialogue_user_prompt(
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": [],
                "decision": {"actions": ["睡眠"], "topic": "睡眠"},
                "current_user_input": {"text": "最近总是睡不好"},
                "user_memory": {},
            }
        )
    )
    assert_all_true(
        "A: Prompt 内容完整",
        {
            "包含用户文本“最近总是睡不好”": "最近总是睡不好" in prompt_a,
            "包含 decision 的 topic“睡眠”": "睡眠" in prompt_a,
            "包含 actions“睡眠”": "actions：睡眠" in prompt_a,
            "包含【历史对话】分区": "【历史对话】" in prompt_a,
            "包含【用户记忆】分区": "【用户记忆】" in prompt_a,
            "包含【当前用户输入】分区": "【当前用户输入】" in prompt_a,
            "包含【上游最终决策】分区": "【上游最终决策】" in prompt_a,
            "包含【任务】分区": "【任务】" in prompt_a,
            "首轮历史提示正确": "（历史对话为空，这是本次对话的第一轮）" in prompt_a,
            "空记忆提示正确": "暂无可用用户记忆" in prompt_a,
            "reason 缺省渲染为（无）": "reason：（无）" in prompt_a,
        },
    )

    # ================= 场景 B =================
    print("\n-- 场景 B: 共情安慰 + 睡眠转食欲（含 reason）, history 两轮睡眠 --")
    prompt_b = build_dialogue_user_prompt(
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": SLEEP_HISTORY,
                "user_memory": {},
                "decision": {
                    "actions": ["共情安慰", "当前话题从睡眠转到食欲"],
                    "topic": "食欲",
                    "reason": "睡眠话题达到次数限制",
                },
                "current_user_input": {"text": "反正就是睡不好"},
            }
        )
    )
    assert_all_true(
        "B: history 与 decision 完整保留",
        {
            "第 1 条历史 user 文本存在": "我最近总是睡不好，躺下要很久才能睡着" in prompt_b,
            "第 2 条历史 assistant 文本存在": "是入睡困难，还是睡着之后容易醒呢？" in prompt_b,
            "第 3 条历史 user 文本存在": "主要是睡不着，脑子里一直在想事情" in prompt_b,
            "第 4 条历史 assistant 文本存在": "这种情况大概持续多久了？" in prompt_b,
            "历史条目编号 1. 存在": "\n1. 用户：" in prompt_b,
            "历史条目编号 4. 存在": "\n4. 助手：" in prompt_b,
            "role=assistant 渲染为“助手”": "助手：" in prompt_b,
            "decision.actions 完整": "actions：共情安慰、当前话题从睡眠转到食欲" in prompt_b,
            "decision.topic 完整": "topic：食欲" in prompt_b,
            "decision.reason 完整": "reason：睡眠话题达到次数限制" in prompt_b,
            "当前用户输入保留": "反正就是睡不好" in prompt_b,
            "未把当前输入混入历史（无第 5 条）": "\n5. " not in prompt_b,
        },
    )
    assert_all_true(
        "B: System Prompt 明确要求自然切换话题",
        {
            "写明“必须严格执行”": "必须严格执行上游给出的最终 decision" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明“不允许自行修改 decision”": "不允许自行修改 decision" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明禁止自己决定话题": "不允许自己决定：下一步聊什么话题" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明切换话题需自然承接": "再平滑进入新话题，不允许生硬换题" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "给出切换话题正例": "听起来最近睡眠确实让你有些困扰" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "给出切换话题反例": "你的食欲怎么样？" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明共情安慰优先": "如果 decision 包含“共情安慰”这类动作" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明继续话题不重复提问": "不要重复同一个问题" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明不暴露内部信息": "不得暴露任何内部系统信息" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明不做诊断": "不做医学诊断" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明视觉标签不得说给用户": "不得把视觉标签直接说给用户听" in DIALOGUE_AGENT_SYSTEM_PROMPT,
            "写明默认只问一个问题": "只提出一个主要问题" in DIALOGUE_AGENT_SYSTEM_PROMPT,
        },
    )

    # ================= 场景 C =================
    print("\n-- 场景 C: user_memory = {} --")
    prompt_c = build_dialogue_user_prompt(
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": [],
                "user_memory": {},
                "decision": {"actions": ["情绪"], "topic": "情绪"},
                "current_user_input": {"text": "今天还行吧"},
            }
        )
    )
    assert_all_true(
        "C: 空记忆处理正确且不报错",
        {
            "Prompt 构造成功（非空字符串）": bool(prompt_c.strip()),
            "明确表示暂无用户记忆": "暂无可用用户记忆" in prompt_c,
            "未出现伪造的记忆条目": "已知事实：" not in prompt_c,
            "未出现用户偏好条目": "用户偏好：" not in prompt_c,
            "未出现重要事件条目": "重要事件：" not in prompt_c,
        },
    )
    # 空 {} 与“记忆字段全空”应渲染一致
    prompt_c2 = build_dialogue_user_prompt(
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": [],
                "user_memory": {
                    "facts": [],
                    "preferences": [],
                    "important_events": [],
                    "previous_assessment_summary": None,
                    "extra": {},
                },
                "decision": {"actions": ["情绪"], "topic": "情绪"},
                "current_user_input": {"text": "今天还行吧"},
            }
        )
    )
    check("C: {} 与字段全空渲染一致", prompt_c == prompt_c2)

    # ================= 场景 D =================
    print("\n-- 场景 D: user_memory.facts = ['用户最近正在准备考试'] --")
    prompt_d = build_dialogue_user_prompt(
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": [],
                "user_memory": {"facts": ["用户最近正在准备考试"]},
                "decision": {"actions": ["压力"], "topic": "压力"},
                "current_user_input": {"text": "有点累"},
            }
        )
    )
    assert_all_true(
        "D: 记忆出现在 Prompt 中",
        {
            "事实内容出现在 Prompt": "用户最近正在准备考试" in prompt_d,
            "带“已知事实：”标签": "已知事实：" in prompt_d,
            "不再显示暂无记忆": "暂无可用用户记忆" not in prompt_d,
        },
    )

    # ================= 场景 E =================
    print("\n-- 场景 E: current_user_input 带 visual --")
    prompt_e = build_dialogue_user_prompt(
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": [],
                "user_memory": {},
                "decision": {"actions": ["情绪"], "topic": "情绪"},
                "current_user_input": {
                    "text": "我没事",
                    "visual": {"valence": -0.5, "arousal": 0.3, "engagement": 0.6},
                },
            }
        )
    )
    assert_all_true(
        "E: 当前输入的视觉数据存在且格式正确",
        {
            "visual 段落标题存在": "这句话的视觉标签：" in prompt_e,
            "valence 存在": "valence=-0.5" in prompt_e,
            "arousal 存在": "arousal=0.3" in prompt_e,
            "engagement 存在": "engagement=0.6" in prompt_e,
            "视觉标签为同一行渲染": "valence=-0.5，arousal=0.3，engagement=0.6" in prompt_e,
        },
    )

    # ========== 附加: 历史中 user 的 visual 一并序列化 ==========
    print("\n-- 附加: 历史 user 消息的 visual 一并序列化 --")
    prompt_f = build_dialogue_user_prompt(
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": [
                    {"role": "user", "content": "第一条历史"},
                    {"role": "assistant", "content": "第一条回复"},
                    {
                        "role": "user",
                        "content": "第二条历史",
                        "visual": {"valence": -0.2, "engagement": 0.4, "extra": {"gaze": "down"}},
                    },
                ],
                "user_memory": {"extra": {"note": "占位扩展"}},
                "decision": {"actions": ["情绪"], "topic": "情绪"},
                "current_user_input": {"text": "最新一句"},
            }
        )
    )
    assert_all_true(
        "附加: 历史 visual / extra 不丢失",
        {
            "历史 user 视觉标签已序列化": "（当时的视觉标签：valence=-0.2，engagement=0.4" in prompt_f,
            "历史 visual.extra 已序列化": '"gaze": "down"' in prompt_f,
            "user_memory.extra 已序列化": "其他记忆：" in prompt_f and '"note": "占位扩展"' in prompt_f,
            "assistant 消息未伪造视觉标签": "第一条回复（当时的视觉标签" not in prompt_f,
        },
    )

    # ========== 附加: 确定性（同一输入同一输出） ==========
    print("\n-- 附加: 纯函数确定性 --")
    payload = {
        "conversation_history": SLEEP_HISTORY,
        "decision": {"actions": ["睡眠"], "topic": "睡眠"},
        "current_user_input": {"text": "还是睡不好"},
        "user_memory": {},
    }
    p1 = build_dialogue_user_prompt(DialogueAgentRequest.model_validate(payload))
    p2 = build_dialogue_user_prompt(DialogueAgentRequest.model_validate(payload))
    check("附加: 同一输入两次调用结果一致", p1 == p2)

    # ========== 导出完整示例，供人工查看 ==========
    sample = build_dialogue_user_prompt(
        DialogueAgentRequest.model_validate(
            {
                "conversation_history": SLEEP_HISTORY,
                "user_memory": {
                    "facts": ["是一名大二学生", "最近正在准备期末考试"],
                    "preferences": ["喜欢被直接提问"],
                },
                "decision": {
                    "actions": ["共情安慰", "当前话题从睡眠转到食欲"],
                    "topic": "食欲",
                    "reason": "睡眠话题达到次数限制",
                },
                "current_user_input": {
                    "text": "反正就是睡不好，白天也没什么精神",
                    "visual": {"valence": -0.5, "arousal": 0.3, "engagement": 0.6},
                },
            }
        )
    )
    out_dir = PROJECT_ROOT / "scripts" / "_prompt_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "user_prompt_sample.txt"
    out_file.write_text(sample, encoding="utf-8")
    print(f"\n已导出完整示例（UTF-8）: {out_file.relative_to(PROJECT_ROOT)}")

    print("=" * 64)
    if FAILURES:
        print(f"结果：失败 {len(FAILURES)} 项 -> {FAILURES}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
