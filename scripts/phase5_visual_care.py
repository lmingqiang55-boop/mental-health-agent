# -*- coding: utf-8 -*-
"""Phase 5 真实模型验证：预设视觉线索能否让 Dialogue 真说出一句外观关怀。

**关于视觉输入的诚实声明**：本脚本的视觉帧是**脚本预设的测试输入**，用与线上
一致的 ``VisionState`` / ``aggregate_frames`` / ``vision_segments`` 结构注入，
**不是实时摄像头采集的**，也**不是真实人脸检测器的输出**。这样做的目的是让
"哪一轮给了什么线索"完全可控，从而看清 Dialogue 在收到线索后到底怎么说话。

被验证的是**真模型**：Safety / Router / Dialogue 都是 ``deepseek-flash``，
Decision 是本地 Ollama ``policy-qwen3-8b``。

用法::

    python scripts/phase5_visual_care.py
    python scripts/phase5_visual_care.py --out docs/phase5_visual_care_log.md
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

from backend.api import chat  # noqa: E402
from backend.core import dialogue_manager as dialogue_manager_module  # noqa: E402
from backend.core.session_manager import session_manager  # noqa: E402
from backend.core.dialogue_manager import select_visual_channels  # noqa: E402
from backend.core.visual_acknowledgment import mentions_appearance  # noqa: E402
from backend.graph.engine import DIALOGUE_ENGINE_ENV, ENGINE_GRAPH  # noqa: E402
from backend.llm.config import load_deepseek_config  # noqa: E402
from backend.llm.deepseek_client import DeepSeekClient  # noqa: E402
from backend.main import app  # noqa: E402
from backend.policy.client import get_policy_client  # noqa: E402
from backend.vision.aggregation import aggregate_frames  # noqa: E402
from _probe import CountingPolicy, CountingSafety, install_route_recorder  # noqa: E402

client = TestClient(app)

CAPTURE_ID = "phase5-preset-camera"

#: 每一组预设视觉线索。``emotion`` / ``confidence`` / ``valence`` 就是注入的
#: 视觉标签；``neutral`` 配低置信度是刻意选的——那正是真实模型最常见的输出，
#: 用来验证"说不出情绪名字时，靠连续效价也能说出关怀"。
SCENARIOS: list[dict] = [
    {
        "key": "V1",
        "title": "悲伤（说得出口的情绪名字）",
        "expect": "走表情名字通道，说出“难过”这一类",
        "vision": {"emotion": "sad", "confidence": 0.92, "valence": -0.62},
        "texts": [
            "最近学习有点跟不上",
            "上课听不太进去，作业也拖着",
            "就是提不起劲，什么都不想做",
            "晚上躺床上会想很多",
            "白天又特别困",
        ],
    },
    {
        "key": "V2",
        "title": "紧张（说得出口的情绪名字）",
        "expect": "走表情名字通道，说出“紧张”这一类",
        "vision": {"emotion": "fearful", "confidence": 0.88, "valence": -0.5},
        "texts": [
            "下周要上台答辩",
            "一想到就手心出汗",
            "晚上也睡不踏实",
            "怕自己讲砸了",
            "同学都比我准备得好",
        ],
    },
    {
        "key": "V3",
        "title": "疲惫/低落（说不出情绪名字，只有连续效价）",
        "expect": "走整体语气通道，说出“累/没精神”这一类",
        "vision": {"emotion": "neutral", "confidence": 0.42, "valence": -0.38},
        "texts": [
            "最近就是有点累",
            "睡得也一般",
            "白天老打瞌睡",
            "没什么想做的事",
            "周末基本都在宿舍躺着",
        ],
    },
    {
        "key": "V4",
        "title": "嘴上说还好、画面明显偏负（矛盾核对）",
        "expect": "走温和核对通道，试探地确认一次",
        "vision": {"emotion": "neutral", "confidence": 0.4, "valence": -0.65},
        "texts": [
            "我还好，没什么事",
            "真的挺好的，就是有点忙",
            "都挺正常的",
            "不用担心我",
            "最近就是事情多了点",
        ],
    },
]


class RecordingClient:
    """包住真实 DeepSeek 客户端，留下原始返回文本（用于区分首答与重写）。"""

    def __init__(self, inner: DeepSeekClient, sink: list[str]) -> None:
        self._inner = inner
        self._sink = sink
        self.client = inner.client

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        raw = await self._inner.generate(
            system_prompt=system_prompt, user_prompt=user_prompt)
        self._sink.append(raw)
        return raw


def install_recorder() -> list[str]:
    raw_outputs: list[str] = []
    original = dialogue_manager_module.DeepSeekClient

    def factory(config):
        return RecordingClient(original(config), raw_outputs)

    dialogue_manager_module.DeepSeekClient = factory
    return raw_outputs


def preset_frames(emotion: str, confidence: float, valence: float) -> list:
    from backend.models.states import VisionState
    return [VisionState(face_detected=True, emotion=emotion,
                        emotion_confidence=confidence, valence=valence)
            for _ in range(4)]


def install_vision(session_id: str, utterance_id: str, spec: dict) -> object:
    """把预设视觉帧装成与线上一致的冻结结果，并返回对应的这份快照。

    ``source="real"`` 是 ``_gate_frames`` 必过的一关（它区分的是"真实检测器
    产出"与"mock 检测器产出"）。这里的帧是脚本造的测试输入，见模块开头声明。
    """
    from backend.models.states import VisionFrameObservation, VisionSegment

    frames = preset_frames(spec["emotion"], spec["confidence"], spec["valence"])
    snapshot = aggregate_frames(frames)
    observations = [VisionFrameObservation(
        frame_id=f"{utterance_id}-{index}", capture_id=CAPTURE_ID,
        captured_at_ms=index * 100, image_digest="phase5-preset",
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


def _is_router_json(raw: str) -> bool:
    """Router 与 Dialogue 共用同一个客户端；路由返回的是 JSON，回复不是。"""
    text = (raw or "").strip()
    if not text.startswith("{"):
        return False
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/phase5_visual_care_log.md")
    parser.add_argument("--engine", default=ENGINE_GRAPH)
    args = parser.parse_args()

    os.environ[DIALOGUE_ENGINE_ENV] = args.engine
    route_records = install_route_recorder()
    policy = CountingPolicy(get_policy_client())
    safety = CountingSafety(chat.safety_runner.evaluate)
    chat.dialogue_manager._policy = policy
    chat.safety_runner.evaluate = safety.evaluate
    raw_outputs = install_recorder()

    print(f"Phase 5 真实模型验证：引擎={args.engine}")
    print("视觉帧为脚本预设的测试输入，不是实时摄像头采集。\n")

    sections: list[str] = []
    care_turns = 0
    total_turns = 0

    for scenario in SCENARIOS:
        print(f"--- {scenario['key']}：{scenario['title']}")
        print(f"    预设视觉标签：{scenario['vision']}")
        session_id = client.post("/api/session").json()["session_id"]
        turns: list[dict] = []

        for index, text in enumerate(scenario["texts"], start=1):
            utterance_id = f"{scenario['key'].lower()}-u{index}"
            snapshot = install_vision(session_id, utterance_id, scenario["vision"])

            # 生成前先算一遍本轮拿到了哪条通道，便于对照
            session = session_manager.get_session(session_id)
            channels = select_visual_channels(session, utterance_id, snapshot, text)

            before = len(raw_outputs)
            policy_before = len(policy.log.elapsed)
            started = time.perf_counter()
            response = client.post("/api/chat", json={
                "session_id": session_id, "text": text,
                "utterance_id": utterance_id,
                "vision_snapshot": snapshot.model_dump(mode="json"),
            })
            elapsed = time.perf_counter() - started
            body = response.json()
            if response.status_code != 200:
                print(f"    HTTP {response.status_code}: {body}")
                break

            new_raw = [raw for raw in raw_outputs[before:] if not _is_router_json(raw)]
            channel = ("emotion" if channels.acknowledgment else
                       "discordance" if channels.discordance else
                       "tone" if channels.tone else "none")
            mentioned = mentions_appearance(body["reply"])
            decision_calls, _ = policy.log.since(policy_before)
            total_turns += 1
            if mentioned:
                care_turns += 1
            print(f"  第{index}轮 通道={channel:11s} "
                  f"feedback={body['visual_feedback']['reason']:18s} "
                  f"提到外观={mentioned} 模型调用={len(new_raw)} {elapsed:.2f}s")
            if mentioned:
                print(f"      -> {body['reply']}")

            turns.append({
                "turn": index, "user": text, "channel": channel,
                "feedback_reason": body["visual_feedback"]["reason"],
                "mentioned": mentioned, "reply": body["reply"],
                "messages": body["messages"], "model_calls": len(new_raw),
                "raw_outputs": new_raw, "decision_calls": decision_calls,
                "elapsed": round(elapsed, 2),
                "cooldown_marker": session_manager.get_session(
                    session_id).last_visual_observation_turn,
            })

        rows = ["| 轮 | 学生（模拟） | 本轮通道 | feedback.reason | 是否提到外观 | 模型调用 | 冷却标记 |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for turn in turns:
            rows.append(
                f"| {turn['turn']} | {turn['user']} | {turn['channel']} | "
                f"`{turn['feedback_reason']}` | "
                f"{'**是**' if turn['mentioned'] else '否'} | "
                f"{turn['model_calls']} | {turn['cooldown_marker']} |")
        detail = []
        for turn in turns:
            detail.append(f"**第 {turn['turn']} 轮**　学生：{turn['user']}\n")
            detail.append(f"预设视觉标签：`{json.dumps(scenario['vision'], ensure_ascii=False)}`"
                          f"　本轮通道：`{turn['channel']}`"
                          f"　feedback：`{turn['feedback_reason']}`\n")
            for order, message in enumerate(turn["messages"], start=1):
                detail.append(f"{order}. {message}")
            detail.append("")
            detail.append("模型原始返回：\n")
            for call, raw in enumerate(turn["raw_outputs"], start=1):
                label = "首答" if call == 1 else f"重写#{call - 1}"
                detail.append(f"```text\n[{label}]\n{raw}\n```")
            detail.append("")

        sections.append("\n".join([
            f"### {scenario['key']}：{scenario['title']}\n",
            f"预期：{scenario['expect']}\n",
            f"预设视觉标签：`{json.dumps(scenario['vision'], ensure_ascii=False)}`\n",
            *rows, "", *detail]))

    body = "\n".join([
        "# Phase 5 视觉关怀话术验证（真实模型 + 预设视觉标签）\n",
        "> 由 `scripts/phase5_visual_care.py` 生成。\n",
        "> **视觉帧是脚本预设的测试输入**，用与线上一致的 `VisionState` / "
        "`aggregate_frames` / `vision_segments` 结构注入，"
        "**不是实时摄像头采集，也不是真实人脸检测器的输出**。"
        "这样做的目的是让「哪一轮给了什么线索」完全可控。\n",
        "> 被验证的是**真模型**：Safety / Router / Dialogue 为 `deepseek-flash`，"
        "Decision 为本地 Ollama `policy-qwen3-8b:latest`；`DIALOGUE_ENGINE=graph`。\n",
        f"\n**本轮结果**：{len(SCENARIOS)} 组预设场景共 {total_turns} 轮，"
        f"其中 **{care_turns} 轮真的说出了外观关怀**。\n",
        *sections,
        "## 读法提醒\n",
        "- `feedback.reason` 是后端给出的通道判定；`是否提到外观` 是按回复正文实测的，"
        "两者不一致就说明模型拿了线索却没说出来；",
        "- `冷却标记`（`last_visual_observation_turn`）只在**真的说出口**之后才推进，"
        "所以「模型沉默」不会让后面四轮失去机会；",
        "- `模型调用` 大于 1 表示命中了既有的重写兜底（重复 / 漏提外观 / 收尾仍提问），"
        "不是新增的独立调用；",
        "- 条数与气泡由 Dialogue 自己决定，视觉话术只影响措辞，不改话题与策略。\n",
    ])

    out = ROOT / args.out
    out.write_text(body, encoding="utf-8")
    print(f"\n实际结果：{total_turns} 轮中 {care_turns} 轮说出外观关怀")
    print(f"记录已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
