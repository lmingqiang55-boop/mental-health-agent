# -*- coding: utf-8 -*-
"""Phase 1：LangGraph 底座与 legacy 路径的等价性。

本文件的核心主张是**等价**，而不是"新功能可用"：

1. 同一串输入下，``DIALOGUE_ENGINE=graph`` 与 ``legacy`` 产出同样的回复、
   策略、阶段、评估就绪标记、收尾原因、视觉反馈与话题计数；
2. Safety 每轮**恰好一次**，graph 不会重复判定、也不绕过判定；
3. 普通轮每轮**恰好一次**决策调用（Phase 1 保持原有行为），收尾轮不调用；
4. ``utterance_id`` 幂等、话题次数上限与收尾规则、视觉线索全部保留；
5. 同一会话中途切换引擎会被明确拒绝，且该轮整体丢弃、不留半轮；
6. 图内不存在 ``asyncio.run``，也不使用异步 ``ainvoke``。
"""

import ast
import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient
from conftest import create_consented_session
from backend.core.screening_flow import MAX_TURNS

from backend.graph.engine import (
    DIALOGUE_ENGINE_ENV,
    ENGINE_GRAPH,
    ENGINE_LEGACY,
    DialogueEngineConfigError,
    dialogue_engine,
)
from backend.graph.nodes import TurnNodes
from backend.main import app
from backend.safety.schemas import SafetyLevel

client = TestClient(app)

#: 一段脚本化会话，覆盖普通轮、追问与收尾之外的常见路径。
SCRIPT = (
    "最近总是觉得压力很大",
    "晚上常常睡不着",
    "主要是半夜醒了就不好再睡",
    "醒来之后会想很多事情",
    "白天上课也集中不了注意力",
)


@pytest.fixture(autouse=True)
def _offline_decision_model(policy_stub):
    """本文件一律用模拟的决策模型，不启动真实模型。"""
    policy_stub()


def new_session() -> str:
    return create_consented_session(client)


def chat(session_id: str, text: str, **extra: Any):
    return client.post("/api/chat", json={"session_id": session_id, "text": text, **extra})


def drive(session_id: str, texts) -> list[dict]:
    bodies = []
    for text in texts:
        response = chat(session_id, text)
        assert response.status_code == 200, response.text
        bodies.append(response.json())
    return bodies


def session_state(session_id: str) -> dict:
    return client.get(f"/api/session/{session_id}").json()


def comparable(body: dict) -> dict:
    """响应里所有应当与引擎无关的字段。"""
    return {
        "reply": body["reply"],
        "messages": body["messages"],
        "next_strategy": body["next_strategy"],
        "current_stage": body["current_stage"],
        "assessment_ready": body["assessment_ready"],
        "completion_reason": body["completion_reason"],
        "visual_feedback": body["visual_feedback"],
        "screening_progress": body["screening_progress"],
        "turn_count": body["turn_count"],
    }


def progress_of(state: dict) -> dict:
    return state["screening_progress"]


# ---------------------------------------------------------------------------
# 引擎选择
# ---------------------------------------------------------------------------

def test_default_engine_is_legacy(monkeypatch):
    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    assert dialogue_engine() == ENGINE_LEGACY


def test_engine_value_is_normalised(monkeypatch):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, "  GRAPH  ")
    assert dialogue_engine() == ENGINE_GRAPH


def test_invalid_engine_is_loud_instead_of_silently_legacy(monkeypatch):
    """写错引擎名时绝不能悄悄按 legacy 跑——那会让人以为在验证 graph。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, "graphh")
    with pytest.raises(DialogueEngineConfigError):
        dialogue_engine()

    session_id = new_session()
    response = chat(session_id, "最近睡不好")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DIALOGUE_ENGINE_INVALID"


# ---------------------------------------------------------------------------
# 等价性：本轮改造的核心主张
# ---------------------------------------------------------------------------

def test_graph_matches_legacy_turn_by_turn(monkeypatch):
    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    legacy_id = new_session()
    legacy = drive(legacy_id, SCRIPT)

    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    graph_id = new_session()
    graph = drive(graph_id, SCRIPT)

    assert [comparable(body) for body in graph] == [comparable(body) for body in legacy]
    assert progress_of(session_state(graph_id)) == progress_of(session_state(legacy_id))


def test_graph_matches_legacy_for_the_closing_turn(monkeypatch):
    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    legacy_id = new_session()
    legacy = drive(legacy_id, ("最近睡不好", "结束对话"))

    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    graph_id = new_session()
    graph = drive(graph_id, ("最近睡不好", "结束对话"))

    assert [comparable(body) for body in graph] == [comparable(body) for body in legacy]
    assert graph[-1]["completion_reason"] == "user_requested"
    assert graph[-1]["assessment_ready"] is True
    assert graph[-1]["next_strategy"] == "结束本次筛查"


def test_graph_matches_legacy_conversation_history(monkeypatch):
    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    legacy_id = new_session()
    drive(legacy_id, SCRIPT)
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    graph_id = new_session()
    drive(graph_id, SCRIPT)

    def transcript(state: dict) -> list[tuple[str, str]]:
        return [(item["role"], item["content"])
                for item in state["conversation_history"]]

    legacy_state = session_state(legacy_id)
    graph_state = session_state(graph_id)
    assert transcript(graph_state) == transcript(legacy_state)
    assert graph_state["turn_count"] == legacy_state["turn_count"]
    assert graph_state["current_stage"] == legacy_state["current_stage"]


def test_graph_reports_a_closed_screening(monkeypatch):
    """收尾之后再发言，两个引擎都必须拒绝，而不是继续普通问答。"""
    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    legacy_id = new_session()
    drive(legacy_id, ("最近睡不好", "结束对话"))
    legacy = chat(legacy_id, "我还想说一句")

    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    graph_id = new_session()
    drive(graph_id, ("最近睡不好", "结束对话"))
    graph = chat(graph_id, "我还想说一句")

    assert graph.status_code == legacy.status_code == 409
    assert graph.json()["error"]["code"] == legacy.json()["error"]["code"] == "SCREENING_FINISHED"


# ---------------------------------------------------------------------------
# 调用次数：Safety 恰好一次、Decision 每普通轮一次
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("engine", [ENGINE_LEGACY, ENGINE_GRAPH])
def test_safety_runs_exactly_once_per_user_message(monkeypatch, safety_stub, engine):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, engine)
    safety_stub.calls.clear()
    session_id = new_session()
    drive(session_id, SCRIPT)
    assert [text for text, _ in safety_stub.calls] == list(SCRIPT)


@pytest.mark.parametrize("engine", [ENGINE_LEGACY, ENGINE_GRAPH])
def test_decision_runs_once_per_open_turn(monkeypatch, policy_stub, engine):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, engine)
    requests: list[Any] = []
    policy_stub(requests=requests)
    session_id = new_session()
    drive(session_id, SCRIPT)
    # Phase 1 保持原有行为：每个普通轮都调用一次决策模型。
    assert len(requests) == len(SCRIPT)


@pytest.mark.parametrize("engine", [ENGINE_LEGACY, ENGINE_GRAPH])
def test_closing_turn_does_not_call_decision(monkeypatch, policy_stub, engine):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, engine)
    requests: list[Any] = []
    policy_stub(requests=requests)
    session_id = new_session()
    drive(session_id, ("最近睡不好",))
    assert len(requests) == 1

    body = chat(session_id, "结束对话").json()
    assert body["completion_reason"] == "user_requested"
    # 收尾轮在决策之前就分流了，不应再多调一次决策模型。
    assert len(requests) == 1


def test_graph_does_not_call_safety_itself(monkeypatch, safety_stub):
    """graph 只做调度，安全判定仍由 /api/chat 的闸门负责。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    safety_stub.calls.clear()
    session_id = new_session()
    drive(session_id, SCRIPT)
    assert len(safety_stub.calls) == len(SCRIPT)


def test_safety_branch_never_enters_the_graph(monkeypatch, safety_stub, policy_stub):
    """安全分支必须绕过普通图，不产生任何决策调用。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list[Any] = []
    policy_stub(requests=requests)
    session_id = new_session()
    safety_stub.force(SafetyLevel.HIGH, message="我们先停下来，你现在安全吗？")

    body = chat(session_id, "我不想活了").json()
    assert body["current_stage"] == "safety_stop"
    assert body["reply"] == "我们先停下来，你现在安全吗？"
    assert requests == []


# ---------------------------------------------------------------------------
# 话题计数 / 收尾规则 / 视觉线索
# ---------------------------------------------------------------------------

def test_repeated_target_is_not_overridden_under_graph(monkeypatch, policy_stub):
    """模型反复选择同一小项时，后端保持其目标，不按次数改题。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub('sleep_disturbance')
    session_id = new_session()
    drive(session_id, ("睡不好",) * 4)

    counts = progress_of(session_state(session_id))["topic_turns"]
    # 4次输入中有3次是在回答此前选定的小项。
    assert counts == {"sleep_disturbance": 3}


def test_screening_closes_within_the_turn_limit_under_graph(monkeypatch):
    """普通回答持续至第35轮强制收尾，收尾后不再接受普通轮。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    session_id = new_session()
    closing = None
    for index in range(MAX_TURNS):
        response = chat(session_id, f"这是第{index}句话")
        if response.status_code == 409:
            break
        assert response.status_code == 200, response.text
        if response.json()["assessment_ready"]:
            closing = response.json()
            break
    assert closing is not None, f"{MAX_TURNS} 轮之内没有收尾"
    assert closing["completion_reason"] == "turn_limit"
    assert closing["turn_count"] == MAX_TURNS == 35
    assert chat(session_id, "还想再说一句").status_code == 409


def test_long_run_closes_identically_on_both_engines(monkeypatch):
    """长会话下的话题覆盖推进与收尾判定也必须与 legacy 完全一致。"""
    texts = [f"这是第{index}句话" for index in range(MAX_TURNS)]

    def run(engine: str):
        monkeypatch.setenv(DIALOGUE_ENGINE_ENV, engine)
        session_id = new_session()
        bodies = []
        for text in texts:
            response = chat(session_id, text)
            if response.status_code == 409:
                break
            assert response.status_code == 200, response.text
            bodies.append(response.json())
            if bodies[-1]["assessment_ready"]:
                break
        return bodies, session_state(session_id)

    legacy_bodies, legacy_state = run(ENGINE_LEGACY)
    graph_bodies, graph_state = run(ENGINE_GRAPH)

    assert len(graph_bodies) == len(legacy_bodies)
    assert graph_bodies[-1]["completion_reason"] == legacy_bodies[-1]["completion_reason"]
    assert [comparable(body) for body in graph_bodies] == \
        [comparable(body) for body in legacy_bodies]
    assert progress_of(graph_state) == progress_of(legacy_state)
    assert graph_state["current_stage"] == legacy_state["current_stage"]


def test_visual_feedback_is_unchanged_under_graph(monkeypatch, dialogue_stub,
                                                  policy_stub):
    """带真实冻结视觉帧时，两个引擎给出的视觉线索与反馈必须一致。"""
    from backend.core.session_manager import session_manager
    from backend.models.states import VisionFrameObservation, VisionSegment, VisionState
    from backend.vision.aggregation import aggregate_frames

    policy_stub('depressed_mood')

    def make_frozen(session) -> None:
        frames = [VisionState(face_detected=True, emotion="sad", emotion_confidence=0.95)
                  for _ in range(3)]
        session.vision_frames = [VisionFrameObservation(
            frame_id=f"frame-{index}", capture_id="camera", captured_at_ms=index * 100,
            image_digest="test", state=frame, source="real",
        ) for index, frame in enumerate(frames)]
        session.vision_segments["turn"] = VisionSegment(
            capture_id="camera", start_ms=0, end_ms=300,
            vision_snapshot=aggregate_frames(frames), frame_count=3,
            valid_frame_count=3, dialogue_frames=session.vision_frames)
        session.active_vision_capture_id = "camera"

    def run(engine: str):
        monkeypatch.setenv(DIALOGUE_ENGINE_ENV, engine)
        session_id = new_session()
        # 先走两轮：外观线索有首轮门限（VISION_ACK_FIRST_TURN），第 1 轮不允许提及。
        drive(session_id, ("第一句", "第二句"))
        session_manager.modify_session(session_id, make_frozen)
        # 取回**被冻结的那一份**快照；modify_session 返回的是整个会话。
        frozen = session_manager.get_session(
            session_id).vision_segments["turn"].vision_snapshot
        response = chat(session_id, "第三句", utterance_id="turn",
                        vision_snapshot=frozen.model_dump(mode="json"))
        assert response.status_code == 200, response.text
        return response.json(), dialogue_stub.requests[-1]

    legacy_body, legacy_request = run(ENGINE_LEGACY)
    graph_body, graph_request = run(ENGINE_GRAPH)

    assert graph_body["visual_feedback"] == legacy_body["visual_feedback"]
    # 关键：合格的视觉线索必须真的送到了对话 Agent，而不是被图吞掉。
    assert graph_request.visual_observation == legacy_request.visual_observation == "sad"
    assert graph_request.current_user_input.visual is not None
    # 线索确实通过门限（而不是退化成"没有可用视觉"）。
    assert graph_body["visual_feedback"]["reason"] in {"mentioned", "generation_omitted"}


# ---------------------------------------------------------------------------
# 幂等性
# ---------------------------------------------------------------------------

def test_utterance_id_replay_is_idempotent_under_graph(
        monkeypatch, policy_stub, safety_stub):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    requests: list[Any] = []
    policy_stub(requests=requests)
    session_id = new_session()

    first = chat(session_id, "最近睡不好", utterance_id="utt-1")
    assert first.status_code == 200
    decisions_after_first = len(requests)
    safety_after_first = len(safety_stub.calls)

    replay = chat(session_id, "最近睡不好", utterance_id="utt-1")
    assert replay.status_code == 200
    assert replay.json() == first.json()
    # 重放不得再调决策或再次判定安全。
    assert len(requests) == decisions_after_first
    assert len(safety_stub.calls) == safety_after_first

    state = session_state(session_id)
    assert state["turn_count"] == 1
    # 开场白 + 本轮 USER + 本轮 ASSISTANT。
    assert len(state["conversation_history"]) == 3


def test_utterance_id_conflict_is_rejected_under_graph(monkeypatch):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    session_id = new_session()
    assert chat(session_id, "最近睡不好", utterance_id="utt-1").status_code == 200
    conflict = chat(session_id, "换一句内容", utterance_id="utt-1")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "UTTERANCE_CONFLICT"


# ---------------------------------------------------------------------------
# 引擎绑定：同一会话不得中途切换
# ---------------------------------------------------------------------------

def test_mid_session_engine_switch_is_rejected_and_turn_is_discarded(
        monkeypatch, policy_stub, safety_stub):
    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    session_id = new_session()
    drive(session_id, ("最近睡不好",))
    before = session_state(session_id)
    safety_before = len(safety_stub.calls)

    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    rejected = chat(session_id, "还是睡不好")

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "DIALOGUE_ENGINE_MISMATCH"
    after = session_state(session_id)
    # 该轮被整体丢弃：不留半轮、不加轮数。
    assert after["turn_count"] == before["turn_count"]
    assert len(after["conversation_history"]) == len(before["conversation_history"])
    # 安全判定发生在引擎分派之前，因此这一轮确实判定过一次；
    # 但会话状态没有被写回，说明失败时不会留下只有用户消息的半轮。
    assert len(safety_stub.calls) == safety_before + 1
    assert after["conversation_history"][-1]["role"] == "assistant"


def test_reverse_switch_is_also_rejected(monkeypatch, policy_stub):
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    session_id = new_session()
    drive(session_id, ("最近睡不好",))

    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    rejected = chat(session_id, "还是睡不好")
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "DIALOGUE_ENGINE_MISMATCH"


def test_engine_binding_is_not_exposed_by_the_session_api(monkeypatch):
    """引擎绑定是内部字段，不得改变前端看到的会话响应结构。"""
    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    session_id = new_session()
    drive(session_id, ("最近睡不好",))
    assert "dialogue_engine" not in session_state(session_id)


def test_each_session_pins_its_own_engine(monkeypatch):
    """不同引擎必须用独立会话——各自绑定，互不影响。"""
    monkeypatch.delenv(DIALOGUE_ENGINE_ENV, raising=False)
    legacy_id = new_session()
    drive(legacy_id, ("最近睡不好",))

    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    graph_id = new_session()
    drive(graph_id, ("最近睡不好",))
    # legacy 会话在切到 graph 后拒绝，新会话照常工作。
    assert chat(legacy_id, "还是睡不好").status_code == 409
    assert chat(graph_id, "还是睡不好").status_code == 200


# ---------------------------------------------------------------------------
# 图结构与节点路由
# ---------------------------------------------------------------------------

def test_route_after_closing_splits_closing_from_open():
    assert TurnNodes.route_after_closing({"ending": None}) == "open"
    assert TurnNodes.route_after_closing({}) == "open"
    for ending in ("user_requested", "turn_limit"):
        assert TurnNodes.route_after_closing({"ending": ending}) == "closing"


def test_graph_has_no_dialogue_router_or_decision_reuse():
    from backend.graph.build import build_turn_graph
    from backend.core.dialogue_manager import DialogueManager
    names = set(build_turn_graph(DialogueManager()).get_graph().nodes)
    assert 'dialogue_route' not in names
    assert 'resolve_topic' not in names


def test_graph_calls_are_synchronous_and_never_nest_asyncio_run():
    """图内必须没有 ``asyncio.run``，也不得使用异步 ``ainvoke``。

    用 AST 取真实调用点，避免被文档字符串里对 ``asyncio.run`` 的说明误伤。
    """
    directory = pathlib.Path("backend/graph")
    calls: list[str] = []
    for path in sorted(directory.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute):
                continue
            base = function.value
            calls.append(f"{base.id}.{function.attr}"
                         if isinstance(base, ast.Name) else function.attr)

    assert "asyncio.run" not in calls
    assert "ainvoke" not in calls
    # 必须真的走同步 invoke。
    assert "invoke" in calls


def test_langgraph_is_imported_lazily():
    """``DIALOGUE_ENGINE=legacy`` 不得被图依赖绑架。

    只有 ``build.py`` 可以在模块级导入 langgraph；``__init__.py`` 与
    ``engine.py`` 必须惰性导入，否则 legacy 路径也会连带加载图库，
    "依赖缺失仍能按 legacy 跑" 这条退路就不成立了。
    """
    directory = pathlib.Path("backend/graph")
    offenders: list[str] = []
    for path in sorted(directory.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # 只看模块级语句，函数内导入属于惰性导入
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if module.startswith("langgraph") and path.name != "build.py":
                    offenders.append(f"{path.name} 模块级导入 {module}")
                if path.name == "__init__.py" and module == "backend.graph.build":
                    offenders.append(f"{path.name} 模块级导入 {module}")
    assert offenders == [], offenders


def test_graph_node_names_are_stable():
    """节点名是测试与后续阶段条件的契约，改名必须显式。"""
    from backend.graph.build import build_turn_graph
    from backend.core.dialogue_manager import DialogueManager

    graph = build_turn_graph(DialogueManager())
    assert set(graph.get_graph().nodes) >= {
        "prepare_turn", "closing_check", "decision",
        "resolve_target", "visual_prepare", "dialogue_execute",
        "dialogue_close", "commit",
    }


def test_graph_has_no_back_edges():
    """图必须是有向无环的：节点重复执行会重复更新话题计数与冷却。"""
    from backend.graph.build import build_turn_graph
    from backend.core.dialogue_manager import DialogueManager

    edges = [(edge.source, edge.target)
             for edge in build_turn_graph(DialogueManager()).get_graph().edges]
    assert edges, "图应当有边"

    # Kahn 拓扑排序：存在环时无法取完所有节点。
    nodes = {node for edge in edges for node in edge}
    indegree = dict.fromkeys(nodes, 0)
    for _, target in edges:
        indegree[target] += 1
    queue = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for source, target in edges:
            if source != node:
                continue
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    assert visited == len(nodes), "图存在回边（环），节点会被重复执行"


def test_recursion_limit_failure_becomes_a_clear_error(monkeypatch):
    """递归上限触发时要变成可读错误，而不是挂死或 500 堆栈。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    monkeypatch.setattr("backend.graph.engine.GRAPH_RECURSION_LIMIT", 2)
    session_id = new_session()
    response = chat(session_id, "最近睡不好")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DIALOGUE_UNAVAILABLE"
