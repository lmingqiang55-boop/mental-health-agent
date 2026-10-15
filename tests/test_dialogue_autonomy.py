# -*- coding: utf-8 -*-
"""Phase 2：Dialogue 主控 + Decision 按需调用。

本文件验证的是"**Dialogue 能自主追问，但话题推进仍然受控**"这一对约束：

1. Dialogue 可以连续局部追问，那些轮次不再调用决策模型；
2. 但话题次数上限、初始策略、用户换话题、高风险话题这些条件下**必须**决策；
3. 话题计数与"本轮是否调用过决策模型"**解耦**——每条回答都被明确归属到
   某个话题并只计一次；
4. 路由本身坏掉时安全回退到"每轮都决策"的既有流程；
5. Safety 仍恰好一次，风险分支不进普通图。

【关于 Mock 的边界】这里的"决策调用次数"是**离线桩上的调度次数**，
证明的是图的分支逻辑，**不是**真实模型下的对话质量或省钱幅度。
真实效果需要跑真模型实验，本文件不做这个结论。
"""

import pytest
from fastapi.testclient import TestClient

from backend.agents.dialogue_agent import (
    DialogueAgentError, parse_route_decision, route_fallback,
)
from backend.graph.engine import DIALOGUE_ENGINE_ENV, ENGINE_GRAPH, ENGINE_LEGACY
from backend.main import app
from backend.safety.schemas import SafetyLevel

client = TestClient(app)

SLEEP = ("共情安慰", "睡眠")


@pytest.fixture(autouse=True)
def _offline_decision_model(policy_stub):
    policy_stub()


def new_session() -> str:
    return client.post("/api/session").json()["session_id"]


def chat(session_id: str, text: str, **extra):
    return client.post("/api/chat", json={"session_id": session_id, "text": text, **extra})


def turn(session_id: str, text: str, **extra) -> dict:
    response = chat(session_id, text, **extra)
    assert response.status_code == 200, response.text
    return response.json()


def counts(requests, dialogue_stub) -> tuple[int, int, int]:
    """(决策模型调用次数, 路由模型调用次数, 回复生成次数)。"""
    return len(requests), len(dialogue_stub.route_requests), len(dialogue_stub.requests)


# ---------------------------------------------------------------------------
# 1 / 3 / 6：自主追问、初始策略、每轮最多一次决策
# ---------------------------------------------------------------------------

def test_first_turn_forces_a_decision_without_asking_dialogue(
        monkeypatch, policy_stub, dialogue_stub):
    """尚无有效全局策略时，后端直接决策，不花一次模型调用去问 Dialogue。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    dialogue_stub.set_route(False, "continue_topic")  # 即使 Dialogue 想继续也没用

    session_id = new_session()
    body = turn(session_id, "最近睡不好")

    assert body["next_strategy"] == "睡眠"
    assert len(requests) == 1
    assert dialogue_stub.route_requests == [], "被后端强制时不应调用路由模型"


def test_dialogue_follow_up_skips_the_decision_model(
        monkeypatch, policy_stub, dialogue_stub):
    """策略仍有效、话题未超预算时，Dialogue 自主追问，不再调用决策模型。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    session_id = new_session()
    turn(session_id, "最近睡不好")
    assert len(requests) == 1

    dialogue_stub.set_route(False, "continue_topic")
    body = turn(session_id, "半夜总是醒")

    assert body["next_strategy"] == "睡眠", "自主追问必须沿用当前话题"
    assert len(requests) == 1, "自主追问那一轮不应再调用决策模型"
    assert len(dialogue_stub.route_requests) == 1
    assert len(dialogue_stub.requests) == 2, "回复仍然要正常生成"


def test_dialogue_can_follow_up_on_several_consecutive_turns(
        monkeypatch, policy_stub, dialogue_stub):
    """连续局部追问是允许的，直到话题预算用尽。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    dialogue_stub.set_route(False, "clarify")

    session_id = new_session()
    for text in ("最近睡不好", "半夜总是醒"):
        turn(session_id, text)

    # 第 1 轮强制决策；第 2 轮起自主追问。此时睡眠话题计到 1 轮，还没到上限。
    decisions, routes, replies = counts(requests, dialogue_stub)
    assert (decisions, routes, replies) == (1, 1, 2)


def test_decision_is_never_called_twice_in_one_turn(
        monkeypatch, policy_stub, dialogue_stub):
    """每轮决策调用次数最多一次——逐轮检查增量。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    dialogue_stub.set_route(False, "continue_topic")

    session_id = new_session()
    seen = 0
    for index, text in enumerate(("最近睡不好", "半夜总是醒", "白天没精神"), start=1):
        turn(session_id, text)
        assert len(requests) - seen <= 1, f"第 {index} 轮调用了多次决策模型"
        seen = len(requests)


# ---------------------------------------------------------------------------
# 2：话题预算用尽 → 强制决策并换话题（用户点名的场景）
# ---------------------------------------------------------------------------

def test_topic_budget_exhaustion_forces_a_decision_and_switches_topic(
        monkeypatch, policy_stub, dialogue_stub):
    """选择睡眠 → 回答 → 自主追问睡眠 → 再回答 → 预算用尽 → 强制换话题。

    决策模型**一直**要求睡眠，因此话题能否切换完全取决于后端的次数约束，
    与模型无关——这正是这条用例要钉住的性质。
    """
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    dialogue_stub.set_route(False, "continue_topic")

    session_id = new_session()
    first = turn(session_id, "最近睡不好")
    second = turn(session_id, "半夜总是醒")
    third = turn(session_id, "醒了就很难再睡着")

    assert first["next_strategy"] == "睡眠"
    assert second["next_strategy"] == "睡眠", "第 2 轮是 Dialogue 自主追问睡眠"
    assert third["next_strategy"] != "睡眠", "睡眠预算用尽后必须换话题"
    assert third["next_strategy"] == "情绪", "换到轮数最少的缺口话题"

    # 第 1、3 轮决策；第 2 轮自主追问。
    decisions, routes, _ = counts(requests, dialogue_stub)
    assert (decisions, routes) == (2, 1)

    progress = client.get(f"/api/session/{session_id}").json()["screening_progress"]
    assert progress["topic_turns"]["睡眠"] == 2
    assert progress["pending_topic"] == "情绪", "下一条回答应计入新话题"


def test_topic_turns_are_counted_regardless_of_the_decision_call(
        monkeypatch, policy_stub, dialogue_stub):
    """话题计数必须与"本轮是否调用决策模型"解耦。

    第 N 轮回答归属于第 N-1 轮确定的话题，因此 N 轮之后计数总和恒为 N-1；
    这条恒等式在"每轮都决策"和"自主追问"两种模式下都必须成立。
    """
    texts = ["第一句", "第二句", "第三句", "第四句", "第五句"]

    def run(need_decision: bool) -> dict:
        monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
        policy_stub(SLEEP)
        dialogue_stub.set_route(need_decision, "continue_topic")
        session_id = new_session()
        for text in texts:
            turn(session_id, text)
        return client.get(f"/api/session/{session_id}").json()["screening_progress"]

    autonomous = run(False)
    always = run(True)

    assert sum(autonomous["topic_turns"].values()) == len(texts) - 1
    assert sum(always["topic_turns"].values()) == len(texts) - 1


# ---------------------------------------------------------------------------
# 4 / 5：换话题请求与路由异常
# ---------------------------------------------------------------------------

def test_route_request_carries_the_context_dialogue_must_consider(
        monkeypatch, policy_stub, dialogue_stub):
    """路由输入必须带上当前话题、已用轮数、上限与整体进度。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub(SLEEP)
    session_id = new_session()
    turn(session_id, "最近睡不好")

    dialogue_stub.set_route(False, "continue_topic")
    turn(session_id, "半夜总是醒")

    request = dialogue_stub.route_requests[-1]
    assert request.active_topic == "睡眠"
    assert request.active_actions == ["共情安慰", "睡眠"]
    assert request.active_topic_turns == 1
    assert request.topic_limit == 2
    assert request.turn_count == 1
    assert request.min_turns == 10
    assert request.max_turns == 20
    assert request.current_user_input.text == "半夜总是醒"
    # 本轮输入不得同时出现在历史里。
    assert all("半夜总是醒" not in message.content
               for message in request.conversation_history)


def test_user_wants_to_change_topic_triggers_a_decision(
        monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    session_id = new_session()
    turn(session_id, "最近睡不好")
    assert len(requests) == 1

    dialogue_stub.set_route(True, "user_wants_change")
    turn(session_id, "这个没什么好说的了，我想聊聊别的")

    assert len(requests) == 2, "Dialogue 请求新策略时必须真的调用决策模型"


def test_route_exception_falls_back_to_the_decision_flow(
        monkeypatch, policy_stub, dialogue_stub):
    """路由模型报错不能让这一轮失败，必须回退到"每轮都决策"。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    session_id = new_session()
    turn(session_id, "最近睡不好")

    async def explode(request):
        raise DialogueAgentError("路由模型不可用")

    monkeypatch.setattr(dialogue_stub, "route", explode)
    body = turn(session_id, "半夜总是醒")

    assert body["next_strategy"] == "睡眠"
    assert len(requests) == 2, "路由失败必须回退到决策流程"
    assert len(dialogue_stub.requests) == 2, "这一轮仍然正常生成回复"


def test_route_unexpected_failure_also_falls_back(
        monkeypatch, policy_stub, dialogue_stub):
    """路由抛出非预期异常同样不能中断对话。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    session_id = new_session()
    turn(session_id, "最近睡不好")

    async def explode(request):
        raise RuntimeError("客户端跨事件循环复用了")

    monkeypatch.setattr(dialogue_stub, "route", explode)
    assert turn(session_id, "半夜总是醒")["next_strategy"] == "睡眠"
    assert len(requests) == 2


@pytest.mark.parametrize("garbage", [
    "", "   ", "不是 JSON", "[]", "null",
    '{"reason_code": "continue_topic"}',
    '{"need_decision": "也许", "reason_code": "continue_topic"}',
])
def test_unparseable_route_output_falls_back_to_decision(garbage):
    decision = parse_route_decision(garbage)
    assert decision.need_decision is True
    assert decision.reason_code == "route_error"


def test_off_contract_reason_code_falls_back_to_decision():
    """布尔值明确但原因码不在约定集合内 → 视为路由异常，回退决策。"""
    decision = parse_route_decision(
        '{"need_decision": false, "reason_code": "whatever"}')
    assert decision.need_decision is True
    assert decision.reason_code == "route_uncertain"


def test_route_output_tolerates_code_fences_and_string_booleans():
    fenced = parse_route_decision(
        '```json\n{"need_decision": false, "reason_code": "continue_topic"}\n```')
    assert fenced.need_decision is False
    assert fenced.reason_code == "continue_topic"
    assert parse_route_decision('{"need_decision": "false", '
                               '"reason_code": "clarify"}').need_decision is False


def test_route_fallback_helper_is_conservative():
    assert route_fallback("测试").need_decision is True


# ---------------------------------------------------------------------------
# 7：话题覆盖、收尾规则、视觉机制不失效
# ---------------------------------------------------------------------------

def test_autonomous_follow_ups_still_respect_every_existing_constraint(
        monkeypatch, policy_stub, dialogue_stub):
    """一路自主追问也不能突破话题上限或收尾规则。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub(SLEEP)
    dialogue_stub.set_route(False, "continue_topic")

    session_id = new_session()
    closing = None
    for index in range(20):
        response = chat(session_id, f"这是第{index}句话")
        if response.status_code == 409:
            break
        assert response.status_code == 200, response.text
        if response.json()["assessment_ready"]:
            closing = response.json()
            break

    assert closing is not None, "自主追问模式下 20 轮内必须仍然收尾"
    assert closing["completion_reason"] in {
        "topic_coverage", "turn_limit", "user_requested"}

    progress = client.get(f"/api/session/{session_id}").json()["screening_progress"]
    assert all(count <= 2 for count in progress["topic_turns"].values()), progress
    # 覆盖率是 topic_coverage 的前提，必须真的推进到了全部 8 个话题。
    if closing["completion_reason"] == "topic_coverage":
        assert len(progress["topic_turns"]) == 8


def test_worst_case_route_still_completes_coverage_before_the_turn_limit(
        monkeypatch, policy_stub, dialogue_stub):
    """Dialogue **一直**要求继续（最坏情况）时，覆盖面仍须在轮数上限前补齐。

    这条用例是"不得为了减少决策调用而牺牲筛查逻辑"的直接检验：
    自主追问会让每个话题用满 2 轮，覆盖面推进明显变慢，因此 ``coverage_lag``
    必须在过了最少轮数后优先补齐没聊过的话题。
    """
    from backend.core.screening_flow import TOPICS

    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub(SLEEP)
    dialogue_stub.set_route(False, "continue_topic")

    session_id = new_session()
    closing = None
    for index in range(20):
        response = chat(session_id, f"这是第{index}句话")
        if response.status_code == 409:
            break
        assert response.status_code == 200, response.text
        if response.json()["assessment_ready"]:
            closing = response.json()
            break

    assert closing is not None, "20 轮之内必须收尾"
    assert closing["completion_reason"] == "topic_coverage", (
        "最坏情况下也必须靠覆盖率收尾，而不是撞上轮数上限")
    progress = client.get(
        f"/api/session/{session_id}").json()["screening_progress"]
    assert len(progress["topic_turns"]) == len(TOPICS), progress
    assert all(count <= 2 for count in progress["topic_turns"].values()), progress


def test_closing_turn_still_skips_the_decision_model(
        monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    session_id = new_session()
    turn(session_id, "最近睡不好")
    assert len(requests) == 1

    body = turn(session_id, "结束对话")
    assert body["completion_reason"] == "user_requested"
    assert body["next_strategy"] == "结束本次筛查"
    assert len(requests) == 1, "收尾轮在决策之前就分流了"
    assert dialogue_stub.route_requests == [], "收尾轮不做路由判断"


def test_visual_feedback_is_not_degraded_by_autonomous_follow_ups(
        monkeypatch, policy_stub, dialogue_stub):
    """自主追问模式下，合格的视觉线索仍然要送到对话 Agent。"""
    from backend.core.session_manager import session_manager
    from backend.models.states import (
        VisionFrameObservation, VisionSegment, VisionState,
    )
    from backend.vision.aggregation import aggregate_frames

    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub(SLEEP)
    dialogue_stub.set_route(False, "continue_topic")

    session_id = new_session()
    turn(session_id, "第一句")
    turn(session_id, "第二句")

    def make_frozen(session) -> None:
        frames = [VisionState(face_detected=True, emotion="sad",
                              emotion_confidence=0.95) for _ in range(3)]
        session.vision_frames = [VisionFrameObservation(
            frame_id=f"frame-{index}", capture_id="camera",
            captured_at_ms=index * 100, image_digest="test", state=frame,
            source="real") for index, frame in enumerate(frames)]
        session.vision_segments["turn"] = VisionSegment(
            capture_id="camera", start_ms=0, end_ms=300,
            vision_snapshot=aggregate_frames(frames), frame_count=3,
            valid_frame_count=3, dialogue_frames=session.vision_frames)
        session.active_vision_capture_id = "camera"

    session_manager.modify_session(session_id, make_frozen)
    frozen = session_manager.get_session(
        session_id).vision_segments["turn"].vision_snapshot
    body = turn(session_id, "第三句", utterance_id="turn",
                vision_snapshot=frozen.model_dump(mode="json"))

    assert dialogue_stub.requests[-1].visual_observation == "sad"
    assert body["visual_feedback"]["reason"] in {"mentioned", "generation_omitted"}


# ---------------------------------------------------------------------------
# 8 / 9：Safety 与幂等
# ---------------------------------------------------------------------------

def test_safety_still_runs_once_and_skips_the_graph_entirely(
        monkeypatch, policy_stub, dialogue_stub, safety_stub):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    dialogue_stub.set_route(False, "continue_topic")
    safety_stub.calls.clear()
    session_id = new_session()

    turn(session_id, "最近睡不好")
    safety_stub.force(SafetyLevel.HIGH, message="我们先停下来，你现在安全吗？")
    body = turn(session_id, "我不想活了")

    assert [text for text, _ in safety_stub.calls] == ["最近睡不好", "我不想活了"]
    assert body["current_stage"] == "safety_stop"
    assert body["reply"] == "我们先停下来，你现在安全吗？"
    assert len(requests) == 1, "安全分支不得产生任何决策调用"
    assert dialogue_stub.route_requests == [], "安全分支不得进入普通图"


def test_replay_does_not_spend_models_or_double_count(
        monkeypatch, policy_stub, dialogue_stub, safety_stub):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    dialogue_stub.set_route(False, "continue_topic")
    session_id = new_session()

    first = chat(session_id, "最近睡不好", utterance_id="utt-1")
    assert first.status_code == 200
    decisions, routes, replies = counts(requests, dialogue_stub)
    safety_calls = len(safety_stub.calls)

    replay = chat(session_id, "最近睡不好", utterance_id="utt-1")

    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert counts(requests, dialogue_stub) == (decisions, routes, replies)
    assert len(safety_stub.calls) == safety_calls
    progress = client.get(
        f"/api/session/{session_id}").json()["screening_progress"]
    assert progress["topic_turns"] == {}


# ---------------------------------------------------------------------------
# 前端契约：Phase 2 不得改变前端看到的字段集合
# ---------------------------------------------------------------------------

def test_frontend_contract_is_unchanged(monkeypatch, policy_stub, dialogue_stub):
    """新增的记账字段必须全部排除在响应之外（含自主追问那一轮）。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub(SLEEP)
    dialogue_stub.set_route(False, "continue_topic")
    session_id = new_session()

    body = turn(session_id, "最近睡不好")
    dialogue_stub.set_route(False, "continue_topic")
    body = turn(session_id, "半夜总是醒")

    expected = {"pending_topic", "topic_turns", "end_reason"}
    assert set(body["screening_progress"]) == expected, body["screening_progress"]
    for leaked in ("dialogue_engine", "active_topic", "active_actions"):
        assert leaked not in body, f"{leaked} 不得出现在聊天响应里"

    state = client.get(f"/api/session/{session_id}").json()
    assert set(state["screening_progress"]) == expected
    for leaked in ("dialogue_engine", "active_topic", "active_actions"):
        assert leaked not in state, f"{leaked} 不得出现在会话响应里"


# ---------------------------------------------------------------------------
# 后端强制条件的单元覆盖
# ---------------------------------------------------------------------------

def unit_session(**progress):
    from backend.models.states import ScreeningProgress, SessionState

    session = SessionState(session_id="unit")
    session.screening_progress = ScreeningProgress(**progress)
    return session


def _all_covered() -> dict:
    from backend.core.screening_flow import TOPICS

    return {topic.value: 1 for topic in TOPICS}


@pytest.mark.parametrize("progress, turn_count, expected", [
    # 还没有任何有效全局策略
    ({}, 0, "no_active_decision"),
    # 已存策略含无效动作
    ({"active_actions": ["没有这个动作"]}, 0, "active_decision_invalid"),
    # 有策略但没有话题
    ({"active_actions": ["共情安慰", "睡眠"]}, 0, "no_active_topic"),
    # 话题不在已知集合内
    ({"active_actions": ["共情安慰", "睡眠"], "active_topic": "不存在的话题"},
     0, "active_topic_invalid"),
    # 话题预算用尽
    ({"active_actions": ["共情安慰", "睡眠"], "active_topic": "睡眠",
      "topic_turns": {"睡眠": 2}}, 0, "topic_budget_exhausted"),
    # 高风险话题不做自主追问
    ({"active_actions": ["共情安慰", "自杀倾向"], "active_topic": "自杀倾向"},
     0, "sensitive_topic"),
    # 过了最少轮数、话题已有 1 轮、覆盖不全 → 优先补齐覆盖
    ({"active_actions": ["共情安慰", "睡眠"], "active_topic": "睡眠",
      "topic_turns": {"睡眠": 1}}, 9, "coverage_lag"),
    # 同样条件下还没到最少轮数 → 允许自主追问
    ({"active_actions": ["共情安慰", "睡眠"], "active_topic": "睡眠",
      "topic_turns": {"睡眠": 1}}, 1, None),
    # 覆盖已全 → 不因覆盖原因强制
    ({"active_actions": ["共情安慰", "睡眠"], "active_topic": "睡眠",
      "topic_turns": _all_covered()}, 9, None),
    # 正常进行中
    ({"active_actions": ["共情安慰", "睡眠"], "active_topic": "睡眠",
      "topic_turns": {"睡眠": 0}}, 2, None),
])
def test_should_force_decision_reasons(progress, turn_count, expected):
    from backend.core.screening_flow import should_force_decision

    session = unit_session(**progress)
    session.turn_count = turn_count
    assert should_force_decision(session) == expected


def test_record_answer_is_idempotent_within_a_turn():
    """同一条用户回答重复登记只计数一次——话题计数不会被节点重复执行影响。"""
    from backend.core.screening_flow import record_answer

    session = unit_session(pending_topic="睡眠")
    record_answer(session)
    record_answer(session)
    record_answer(session)
    assert session.screening_progress.topic_turns == {"睡眠": 1}
    assert session.screening_progress.pending_topic is None


def test_carry_over_topic_never_changes_the_global_topic():
    """Dialogue 自主追问只能续用当前话题，不能改写全局话题与动作。"""
    from backend.core.screening_flow import carry_over_topic

    session = unit_session(active_topic="睡眠",
                           active_actions=["共情安慰", "睡眠"],
                           pending_topic=None)
    carry_over_topic(session)
    assert session.screening_progress.pending_topic == "睡眠"
    assert session.screening_progress.active_topic == "睡眠"
    assert session.screening_progress.active_actions == ["共情安慰", "睡眠"]


def test_adopt_decision_records_the_constrained_topic():
    """新策略生效时必须记录被次数约束器裁剪后的那个话题。"""
    from backend.core.screening_flow import adopt_decision
    from backend.policy.client import DialogueAction, PolicyDecision

    session = unit_session(active_topic="睡眠",
                           active_actions=["共情安慰", "睡眠"])
    decision = PolicyDecision(actions=[DialogueAction.EMPATHY, DialogueAction.MOOD])
    adopt_decision(session, decision, "情绪")
    assert session.screening_progress.active_topic == "情绪"
    assert session.screening_progress.active_actions == ["共情安慰", "情绪"]
    assert session.screening_progress.pending_topic == "情绪"


def test_reuse_decision_restores_the_stored_strategy():
    """跳过决策时复用的是**已存**策略，不是新造一个。"""
    from backend.core.dialogue_manager import DialogueManager, DialogueUnavailable
    from backend.policy.client import DialogueAction

    manager = DialogueManager()
    session = unit_session(active_topic="睡眠",
                           active_actions=["共情安慰", "睡眠"])
    decision = manager.reuse_decision(session)
    assert decision.actions == [DialogueAction.EMPATHY, DialogueAction.SLEEP]

    with pytest.raises(DialogueUnavailable):
        manager.reuse_decision(unit_session())


# ---------------------------------------------------------------------------
# 对照组：Legacy 与 Graph 的决策调用次数
# ---------------------------------------------------------------------------

def test_decision_call_counts_legacy_versus_graph(
        monkeypatch, policy_stub, dialogue_stub):
    """6 轮脚本：自主追问模式下的决策次数必须少于迁移前。

    ``graph_all``（Dialogue 每轮都要求新策略）必须与 legacy **完全相同**——
    这说明减少调用完全来自路由判断，而不是顺手改掉了别的东西。
    """
    texts = ("最近睡不好", "半夜总是醒", "白天没精神",
             "不想吃饭", "提不起兴趣", "总是一个人待着")

    def run(engine: str, need_decision: bool) -> int:
        monkeypatch.setenv(DIALOGUE_ENGINE_ENV, engine)
        requests: list = []
        policy_stub(SLEEP, requests=requests)
        dialogue_stub.set_route(need_decision, "continue_topic")
        session_id = new_session()
        for text in texts:
            turn(session_id, text)
        return len(requests)

    legacy = run(ENGINE_LEGACY, True)
    graph_all = run(ENGINE_GRAPH, True)
    graph_autonomous = run(ENGINE_GRAPH, False)

    assert legacy == len(texts)
    assert graph_all == legacy, "Dialogue 每轮都要新策略时必须与 legacy 一致"
    assert graph_autonomous < legacy, "自主追问必须真的减少决策调用"
    assert graph_autonomous == 3, "6 轮里只有话题预算用尽的那 3 轮需要决策"


def test_legacy_engine_never_consults_the_router(
        monkeypatch, policy_stub, dialogue_stub):
    """legacy 路径不得因为 Phase 2 而多出一次路由模型调用。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_LEGACY)
    requests: list = []
    policy_stub(SLEEP, requests=requests)
    dialogue_stub.set_route(False, "continue_topic")

    session_id = new_session()
    for text in ("最近睡不好", "半夜总是醒", "白天没精神"):
        turn(session_id, text)

    assert len(requests) == 3, "legacy 仍然每轮决策"
    assert dialogue_stub.route_requests == [], "legacy 不做路由判断"
