# -*- coding: utf-8 -*-
"""Phase 6 真实模型验证：三个演示场景的真实 trace。

被验证的是**真模型**：Safety / Router / Dialogue 为 ``deepseek-flash``，
Decision 为本地 Ollama ``policy-qwen3-8b``；``DIALOGUE_ENGINE=graph``、
``AGENT_TRACE=on``。

**关于视觉输入的诚实声明**：场景 C 的视觉帧是**脚本预设的测试输入**，用与线上
一致的 ``VisionState`` / ``aggregate_frames`` / ``vision_segments`` 结构注入，
**不是实时摄像头采集的，也不是真实人脸检测器的输出**。

用法::

    python scripts/phase6_trace_real.py
    python scripts/phase6_trace_real.py --out docs/archive/dialogue/phase6_trace_log.md
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

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from backend.api import chat  # noqa: E402
from backend.core.agent_trace import TRACE_ENV  # noqa: E402
from backend.core.session_manager import session_manager  # noqa: E402
from backend.graph.engine import DIALOGUE_ENGINE_ENV, ENGINE_GRAPH  # noqa: E402
from backend.models.requests import ChatRequest  # noqa: E402
from backend.models.states import (  # noqa: E402
    VisionFrameObservation, VisionSegment, VisionState,
)
from backend.vision.aggregation import aggregate_frames  # noqa: E402

CAPTURE_ID = "phase6-preset-camera"

#: 场景 A：Dialogue 自主追问（Decision 复用当前策略）。
SCENARIO_A = {
    "key": "A",
    "title": "Dialogue 自主追问 -> Decision 跳过",
    "expect": "第 2 轮起 Dialogue 自己决定继续追问，面板显示「复用当前策略」",
    "texts": [
        "最近老是睡不好，躺下要很久才能睡着",
        "半夜还会醒一两次，早上起来特别累",
        "白天上课就犯困，注意力也集中不了",
        "有时候会想是不是自己太焦虑了",
    ],
}

#: 场景 B：需要切换话题（Decision 真实调用）。
SCENARIO_B = {
    "key": "B",
    "title": "需要换话题 -> Decision 真实调用",
    "expect": "学生明确要求换方向时，Dialogue 请求新策略，面板显示「本轮已调用决策模型」",
    "texts": [
        "最近吃饭没什么胃口，也不太想吃东西",
        "体重好像掉了几斤",
        "这些先不聊了吧，我们换个话题好吗",
        "我想说说和室友相处的事",
    ],
}

#: 场景 C：视觉关怀（预设视觉线索被真实说出口）。
SCENARIO_C = {
    "key": "C",
    "title": "视觉关怀 -> 线索被采用",
    "expect": "预设视觉标签有效时，Dialogue 真的说出「你看起来……」",
    "vision": {"emotion": "sad", "confidence": 0.92, "valence": -0.62},
    "texts": [
        "最近做什么都提不起劲",
        "以前喜欢打篮球，现在也不想去了",
        "就是觉得很累，什么都不想做",
    ],
}


def install_vision(session_id: str, utterance_id: str, spec: dict):
    """把预设视觉帧装成与线上一致的冻结结果，并返回这份快照。"""
    frames = [VisionState(face_detected=True, emotion=spec["emotion"],
                          emotion_confidence=spec["confidence"],
                          valence=spec["valence"]) for _ in range(4)]
    snapshot = aggregate_frames(frames)
    observations = [VisionFrameObservation(
        frame_id=f"{utterance_id}-{index}", capture_id=CAPTURE_ID,
        captured_at_ms=index * 100, image_digest="phase6-preset",
        state=frame, source="real",
    ) for index, frame in enumerate(frames)]

    def apply(session):
        session.vision_frames = observations
        session.active_vision_capture_id = CAPTURE_ID
        session.vision_segments[utterance_id] = VisionSegment(
            capture_id=CAPTURE_ID, start_ms=0, end_ms=400,
            vision_snapshot=snapshot, frame_count=len(frames),
            valid_frame_count=len(frames), dialogue_frames=observations,
        )

    session_manager.modify_session(session_id, apply)
    return snapshot


def run_scenario(scenario: dict) -> list[dict]:
    session_id = session_manager.create_session().session_id
    turns: list[dict] = []
    for index, text in enumerate(scenario["texts"], start=1):
        extra: dict = {}
        if "vision" in scenario:
            utterance_id = f"{scenario['key'].lower()}-u{index}"
            snapshot = install_vision(session_id, utterance_id, scenario["vision"])
            extra = {"utterance_id": utterance_id,
                     "vision_snapshot": snapshot.model_dump(mode="json")}
        started = time.perf_counter()
        response = chat.chat(ChatRequest(session_id=session_id, text=text, **extra))
        elapsed = time.perf_counter() - started
        trace = response.trace
        assert trace is not None, "AGENT_TRACE 未生效"
        turns.append({
            "turn": index, "user": text, "elapsed": round(elapsed, 2),
            "reply": response.reply, "messages": response.messages,
            "next_strategy": response.next_strategy,
            "safety_route": response.safety.route.value,
            "trace": trace.model_dump(mode="json"),
        })
        print(f"  第{index}轮 routed={trace.dialogue.routed} "
              f"need_decision={trace.dialogue.need_decision} "
              f"forced={trace.dialogue.forced_reason} "
              f"decision={trace.decision.state} "
              f"vision={trace.vision.channel}/{trace.vision.spoken} "
              f"bubbles={trace.output.bubbles} {elapsed:.2f}s")
    return turns


def render(scenario: dict, turns: list[dict]) -> str:
    lines = [f"## 场景 {scenario['key']}：{scenario['title']}\n",
             f"预期：{scenario['expect']}\n"]
    if "vision" in scenario:
        lines.append("预设视觉标签（**测试输入，非实时摄像头**）："
                     f"`{json.dumps(scenario['vision'], ensure_ascii=False)}`\n")
    for turn in turns:
        trace = turn["trace"]
        lines.append(f"### 第 {turn['turn']} 轮　学生：{turn['user']}\n")
        lines.append(f"- 回复：{turn['reply']}")
        lines.append(f"- 气泡（{trace['output']['bubbles']} 条）："
                     + " ｜ ".join(turn["messages"]))
        lines.append(f"- 策略：`{turn['next_strategy']}`　"
                     f"Safety：`{turn['safety_route']}`　耗时 {turn['elapsed']}s\n")
        lines.append("本轮 `trace`（面板就是照这个渲染的）：\n")
        lines.append("```json")
        lines.append(json.dumps(trace, ensure_ascii=False, indent=2))
        lines.append("```\n")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/archive/dialogue/phase6_trace_log.md")
    args = parser.parse_args()

    os.environ[DIALOGUE_ENGINE_ENV] = ENGINE_GRAPH
    os.environ[TRACE_ENV] = "on"

    print("Phase 6 真实模型验证：graph 引擎 + AGENT_TRACE=on\n")
    sections = []
    for scenario in (SCENARIO_A, SCENARIO_B, SCENARIO_C):
        print(f"--- 场景 {scenario['key']}：{scenario['title']}")
        sections.append(render(scenario, run_scenario(scenario)))

    body = "\n".join([
        "# Phase 6 多智能体运行轨迹验证（真实模型）\n",
        "> 由 `scripts/phase6_trace_real.py` 生成。\n",
        "> 真模型：Safety / Router / Dialogue 为 `deepseek-flash`，"
        "Decision 为本地 Ollama `policy-qwen3-8b:latest`；"
        "`DIALOGUE_ENGINE=graph`、`AGENT_TRACE=on`。\n",
        "> 场景 C 的视觉帧是**脚本预设的测试输入**，用与线上一致的 `VisionState` / "
        "`aggregate_frames` / `vision_segments` 结构注入，"
        "**不是实时摄像头采集，也不是真实人脸检测器的输出**。\n",
        "> `trace` 只含节点级结论：没有提示词、模型推理文本、密钥或视觉原始数据。\n",
        *sections,
    ])
    out = ROOT / args.out
    out.write_text(body, encoding="utf-8")
    print(f"\n记录已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
