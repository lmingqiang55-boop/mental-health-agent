# -*- coding: utf-8 -*-
"""演示用的 Agent 运行轨迹（``/api/chat`` 的 ``trace`` 字段）。

这里锁三件事：

1. **默认关闭**：不设 ``AGENT_TRACE`` 时 ``trace`` 为 ``None``，且响应里不出现
   内部搬运字段 ``scheduling``；
2. **如实反映真实执行**：Decision 跳过就是 ``skipped``、调用就是 ``ran``、
   安全分支就把下游标成 ``short_circuit``，Safety 标为图外前置；
3. **只搬运、不生产**：开不开 trace，回复、气泡、轮次完全一样。
"""

import pytest
from fastapi.testclient import TestClient

from backend.api import chat
from backend.core.agent_trace import TRACE_ENV
from backend.core.session_manager import session_manager
from backend.graph.engine import DIALOGUE_ENGINE_ENV, ENGINE_GRAPH, ENGINE_LEGACY
from backend.main import app
from backend.models.dialogue import DialogueAgentResponse
from backend.models.requests import ChatRequest
from backend.models.states import (
    VisionFrameObservation, VisionSegment, VisionState,
)
from backend.safety.schemas import SafetyLevel
from backend.vision.aggregation import aggregate_frames

client = TestClient(app)

#: 与 ``test_dialogue_autonomy`` 同一套策略桩：「共情安慰」不是话题，
#: 「睡眠」才是，这样第 1 轮强制决策后才会有可复用的当前话题。
SLEEP = ("共情安慰", "睡眠")


def _chat(session_id: str, text: str, **extra):
    return chat.chat(ChatRequest(session_id=session_id, text=text, **extra))


def _turn(session_id: str, text: str) -> str:
    """先说一句、拿到本轮载荷；``payload`` 在聊天响应里已经展平。"""
    return _chat(session_id, text)


def _preset_vision_session(*, emotion="sad", confidence=0.92, valence=None):
    """与线上结构一致的预设视觉帧（测试输入，不是真实摄像头）。"""
    session_id = session_manager.create_session().session_id
    frames = [VisionState(face_detected=True, emotion=emotion,
                          emotion_confidence=confidence, valence=valence)
              for _ in range(3)]
    snapshot = aggregate_frames(frames)
    observations = [VisionFrameObservation(
        frame_id=f"frame-{index}", capture_id="camera",
        captured_at_ms=index * 100, image_digest="test", state=frame,
        source="real",
    ) for index, frame in enumerate(frames)]

    def install(session):
        session.vision_frames = observations
        session.vision_segments["turn"] = VisionSegment(
            capture_id="camera", start_ms=0, end_ms=300,
            vision_snapshot=snapshot, frame_count=3, valid_frame_count=3,
            dialogue_frames=observations)
        session.active_vision_capture_id = "camera"

    session_manager.modify_session(session_id, install)
    return session_id, snapshot


# ---------------------------------------------------------------------------
# 1. 默认关闭
# ---------------------------------------------------------------------------

def test_trace_is_off_unless_switched_on(monkeypatch):
    monkeypatch.delenv(TRACE_ENV, raising=False)
    session_id = session_manager.create_session().session_id

    body = client.post("/api/chat", json={
        "session_id": session_id, "text": "最近有点累"}).json()

    assert body["trace"] is None
    # 内部搬运字段不得出现在 HTTP 响应里。
    assert "scheduling" not in body


def test_trace_can_be_switched_on(monkeypatch):
    monkeypatch.setenv(TRACE_ENV, "on")
    session_id = session_manager.create_session().session_id

    body = client.post("/api/chat", json={
        "session_id": session_id, "text": "最近有点累"}).json()

    assert set(body["trace"]) == {
        "engine", "safety", "dialogue", "decision", "vision", "output"}
    assert "scheduling" not in body


# ---------------------------------------------------------------------------
# 2. 场景 A：Dialogue 自主追问 -> Decision 复用
# ---------------------------------------------------------------------------

def test_scenario_a_reuse_shows_decision_skipped(
        monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    session_id = session_manager.create_session().session_id

    # 第 1 轮后端强制决策建起策略；第 2 轮策略仍有效，Dialogue 自主追问。
    _chat(session_id, "最近睡不好")
    assert len(requests) == 1
    dialogue_stub.set_route(False, "continue_topic")

    trace = _chat(session_id, "半夜总是醒").trace

    assert len(requests) == 1, "复用策略那一轮不应再调用决策模型"
    assert trace.engine == ENGINE_GRAPH
    assert trace.dialogue.state == "ran"
    assert trace.dialogue.routed is True
    assert trace.dialogue.need_decision is False
    assert trace.dialogue.reason_code == "continue_topic"
    assert trace.dialogue.reason_label == "当前话题还值得追问"
    assert trace.dialogue.forced_reason is None
    assert trace.decision.state == "skipped"
    assert trace.decision.called is False
    assert trace.decision.label == "复用当前策略"
    assert trace.vision.state == "ran"


# ---------------------------------------------------------------------------
# 3. 场景 B：需要切换话题 -> Decision 真实调用
# ---------------------------------------------------------------------------

def test_scenario_b_new_strategy_shows_decision_called(
        monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    session_id = session_manager.create_session().session_id
    _chat(session_id, "最近睡不好")
    assert len(requests) == 1
    dialogue_stub.set_route(True, "topic_exhausted")

    trace = _chat(session_id, "半夜总是醒").trace

    assert len(requests) == 2, "请求新策略那一轮必须真的调用决策模型"
    assert trace.dialogue.routed is True
    assert trace.dialogue.need_decision is True
    assert trace.dialogue.reason_code == "topic_exhausted"
    assert trace.dialogue.reason_label == "当前话题问得差不多了"
    assert trace.decision.state == "ran"
    assert trace.decision.called is True
    assert trace.decision.label == "本轮已调用决策模型"
    assert trace.decision.strategy


def test_backend_forced_decision_is_shown_as_router_short_circuit(
        monkeypatch, dialogue_stub):
    """后端强制换策略时会短路掉路由模型调用，面板要说清"没问 Dialogue"。"""
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    dialogue_stub.need_decision = True
    session_id = session_manager.create_session().session_id

    trace = _chat(session_id, "第一句").trace

    assert trace.dialogue.routed is False
    assert trace.dialogue.forced_reason == "no_active_decision"
    assert trace.dialogue.forced_label == "还没有有效策略"
    assert trace.decision.called is True


# ---------------------------------------------------------------------------
# 4. 安全分支：下游节点标成"提前结束"，Safety 标成图外前置
# ---------------------------------------------------------------------------

def test_safety_is_labelled_as_a_pre_graph_check(monkeypatch, safety_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    safety_stub.force(SafetyLevel.NORMAL)
    session_id = session_manager.create_session().session_id

    trace = _chat(session_id, "最近有点累").trace

    assert trace.safety.placement == "pre_graph"
    assert "LangGraph 之外" in trace.safety.placement_label
    assert trace.safety.state == "ran"
    assert trace.safety.engine == "graph_safety_v1"
    assert trace.safety.outcome == "continue"


def test_safety_branch_marks_downstream_as_short_circuit(monkeypatch, safety_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    safety_stub.force(SafetyLevel.HIGH)
    session_id = session_manager.create_session().session_id

    response = _chat(session_id, "我不想活了")
    trace = response.trace

    assert trace.safety.state == "ran"
    assert trace.safety.outcome == "stop"
    # Dialogue / Decision / 视觉通道本轮都没有执行。
    assert trace.dialogue.state == "short_circuit"
    assert trace.dialogue.need_decision is None
    assert trace.decision.state == "short_circuit"
    assert trace.decision.called is None
    assert trace.vision.state == "short_circuit"
    assert trace.vision.cue_valid is False
    # 气泡数仍然是真实条数。
    assert trace.output.bubbles == len(response.messages)


def test_safety_branch_without_hotline_is_review(monkeypatch, safety_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    safety_stub.force(SafetyLevel.UNCERTAIN)
    session_id = session_manager.create_session().session_id

    trace = _chat(session_id, "最近还行吧").trace

    assert trace.safety.outcome == "review"
    assert trace.decision.state == "short_circuit"


# ---------------------------------------------------------------------------
# 5. 视觉感知：线索有效 / 真的说出口，是两件事
# ---------------------------------------------------------------------------

def test_vision_trace_separates_valid_cue_from_being_spoken(
        monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    monkeypatch.setattr("backend.core.dialogue_manager.asyncio.run",
                        _resolve_synchronous_stub)
    policy_stub(("情绪",))
    session_id, snapshot = _preset_vision_session()
    for text in ("第一句", "第二句"):
        _chat(session_id, text)

    # conftest 的对话桩不会提外观，所以"线索有效"与"说出口"应当分开。
    trace = _chat(session_id, "第三句", utterance_id="turn",
                  vision_snapshot=snapshot).trace

    assert trace.vision.state == "ran"
    assert trace.vision.cue_valid is True
    assert trace.vision.channel == "emotion"
    assert trace.vision.channel_label == "表情名字"
    assert trace.vision.cue == "难过"
    assert trace.vision.spoken is False
    assert trace.vision.reason == "generation_omitted"


def test_vision_trace_marks_spoken_when_the_reply_mentions_appearance(
        monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    monkeypatch.setattr("backend.core.dialogue_manager.asyncio.run",
                        _resolve_synchronous_stub)

    async def mention(request):
        return DialogueAgentResponse(reply="你看起来有点累，最近睡得怎么样？")

    dialogue_stub.generate_reply = mention
    policy_stub(("情绪",))
    session_id, snapshot = _preset_vision_session()
    for text in ("第一句", "第二句"):
        _chat(session_id, text)

    trace = _chat(session_id, "第三句", utterance_id="turn",
                  vision_snapshot=snapshot).trace

    assert trace.vision.cue_valid is True
    assert trace.vision.spoken is True
    assert trace.vision.reason == "mentioned"


def test_vision_trace_without_a_cue_is_invalid(monkeypatch, policy_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub(("情绪",))
    session_id = session_manager.create_session().session_id

    trace = _chat(session_id, "第一句").trace

    assert trace.vision.state == "ran"
    assert trace.vision.cue_valid is False
    assert trace.vision.channel is None
    assert trace.vision.spoken is False


# ---------------------------------------------------------------------------
# 6. legacy 引擎：如实说"不提供"，不编造调度信息
# ---------------------------------------------------------------------------

def test_legacy_engine_reports_scheduling_unavailable(monkeypatch, policy_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_LEGACY)
    policy_stub(("情绪",))
    session_id = session_manager.create_session().session_id

    trace = _chat(session_id, "第一句").trace

    assert trace.engine == ENGINE_LEGACY
    assert trace.dialogue.state == "unavailable"
    assert trace.dialogue.need_decision is None
    assert trace.decision.state == "unavailable"
    assert trace.decision.called is None
    # 与图无关的两段仍然如实给出。
    assert trace.safety.state == "ran"
    assert trace.output.bubbles == 1


# ---------------------------------------------------------------------------
# 7. 只搬运、不生产；不外泄
# ---------------------------------------------------------------------------

def test_trace_does_not_change_the_reply(monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub(("情绪",))

    monkeypatch.delenv(TRACE_ENV, raising=False)
    off_id = session_manager.create_session().session_id
    without = _chat(off_id, "最近有点累")

    monkeypatch.setenv(TRACE_ENV, "on")
    on_id = session_manager.create_session().session_id
    with_trace = _chat(on_id, "最近有点累")

    assert with_trace.reply == without.reply
    assert with_trace.messages == without.messages
    assert with_trace.turn_count == without.turn_count
    assert with_trace.next_strategy == without.next_strategy
    assert without.trace is None and with_trace.trace is not None


def test_trace_never_carries_reasoning_text_or_raw_vision(
        monkeypatch, safety_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    safety_stub.force(SafetyLevel.HIGH, message="我们先确保你的安全。")
    session_id = session_manager.create_session().session_id

    body = client.post("/api/chat", json={
        "session_id": session_id, "text": "我不想活了"}).json()
    trace = body["trace"]

    # Safety 段只有结论，没有 rationale / evidence_quotes / keyword_signals。
    assert set(trace["safety"]) == {
        "placement", "placement_label", "engine", "risk_level", "route",
        "model_status", "state", "outcome"}
    flat = repr(trace)
    for leaked in ("rationale", "evidence_quotes", "keyword_signals",
                   "api_key", "api-key", "sk-"):
        assert leaked not in flat
    # 视觉段没有原始数值。
    assert set(trace["vision"]) == {
        "state", "cue_valid", "channel", "channel_label", "cue", "spoken",
        "reason"}


def test_idempotent_replay_returns_the_same_trace(monkeypatch, policy_stub):
    monkeypatch.setenv(TRACE_ENV, "on")
    payload = {"session_id": session_manager.create_session().session_id,
               "text": "最近有点累", "utterance_id": "same-turn"}
    first = client.post("/api/chat", json=payload)
    replay = client.post("/api/chat", json=payload)

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()


def _resolve_synchronous_stub(coroutine):
    """Run a stub coroutine without Windows' socket based event loop."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Stub unexpectedly suspended")
