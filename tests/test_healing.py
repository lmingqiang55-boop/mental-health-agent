"""Support boundaries: grounded methods, feedback, retries and screening separation."""

import asyncio
import hashlib
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import assessment, healing
from backend.core.memory_store import MemoryStore
from backend.core.session_manager import session_manager
from backend.healing.agent import AgentDraft, HealingAgent, NarrativeCheck, choose_scene
from backend.healing.client import HealingUnavailable
from backend.healing.knowledge import validate_item
from backend.healing.retriever import HealingRetriever
from backend.healing.suitability import FitCheck, FitDecision
from backend.healing.store import HealingStore
from backend.main import app
from backend.models.healing import Evidence, Feedback, HealingBackground, KnowledgeItem, student_view
from backend.models.states import RiskResult

client = TestClient(app)
SOURCE = "适用于儿童青少年，其中本条面向初中学生，学生在成人指导下先说出困扰。"


def knowledge(key="name-concern", scene="study_stress", **updates):
    item = KnowledgeItem(
        knowledge_id=key, method_key=key, source_id="synthetic", source_url="https://example.org/support",
        source_title="合成来源", source_version="test:1", source_digest=hashlib.sha256(SOURCE.encode()).hexdigest(),
        source_location="paragraph:1", title="说出考试困扰", scenes=[scene],
        audience="children_adolescents", school_stages=["middle"], executor="adult_guided", purpose="method",
        goal="梳理考试压力", steps=["在成人指导下说出让你有压力的事情。"], prerequisites=["成人指导"],
        evidence=[Evidence(field=field, quote=SOURCE, start=0, end=len(SOURCE))
                  for field in ["audience", "executor", "school_stages", "steps", "prerequisites"]],
        status="usable", semantic_checked=True,
    )
    return item.model_copy(update=updates)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.feedback = []
        self.recommendations = None
        self.referral = False
        self.simplify_id = None
        self.fit_overrides = {}

    async def generate(self, system, payload, schema, **kwargs):
        if self.fail:
            raise HealingUnavailable("synthetic failure")
        if schema is NarrativeCheck:
            return NarrativeCheck(valid=True)
        if schema is FitCheck:
            return FitCheck(decisions=[FitDecision(knowledge_id=item["knowledge_id"],
                **self.fit_overrides.get(item["knowledge_id"], {"verdict": "suitable"}))
                for item in payload["knowledge"]])
        self.calls.append(payload)
        await asyncio.sleep(.01)
        ids = [item["knowledge_id"] for item in payload.get("knowledge", [])]
        chosen = (ids[:1] if payload.get("phase") == "report" else []) if self.recommendations is None else self.recommendations
        return AgentDraft(
            understanding="想到考试时，你感到紧张，我听到了。", focus="眼下的考试压力。",
            question=f"开始前最担心遇到什么困难（第{len(self.calls)}次回应）？", recommendation_ids=chosen,
            feedback=self.feedback, safety_referral=self.referral, simplify_suggestion_id=self.simplify_id,
        )


@pytest.fixture
def support(tmp_path, monkeypatch, evaluation_stub):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    fake = FakeClient()
    monkeypatch.setattr(assessment, "memory_store", store)
    monkeypatch.setattr(healing, "memory_store", store)
    monkeypatch.setattr(healing, "healing_store", HealingStore())
    monkeypatch.setattr(healing, "healing_agent", HealingAgent(fake, HealingRetriever([
        knowledge(), knowledge("other", title="另一种压力表达", steps=["在成人指导下表达考试担忧。"]),
    ])))
    session = client.post("/api/session").json()
    sid = session["session_id"]
    result = client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": "最近考试压力很大"}],
    }}).json()["result"]
    return sid, result, store, fake


def start(sid, **kwargs):
    return client.post("/api/healing/start", json={"session_id": sid, "request_id": str(uuid4()),
        "background": {"school_stage": "middle", "current_concern": "考试压力", "adult_support_available": True}, **kwargs})


def chat(sid, hid, text, message_id=None):
    return client.post("/api/healing/chat", json={"session_id": sid, "healing_id": hid,
                      "message_id": message_id or str(uuid4()), "text": text})


def update_screening_risk(sid, *, crisis=False, level="high", score=.9):
    def update(session):
        session.latest_risk = RiskResult(risk_level=level, risk_score=score,
            requires_intervention=level == "high", risk_reasons=["合成风险更新"])
        session.crisis_mode = crisis
    assert session_manager.modify_session(sid, update) is not None


@pytest.mark.parametrize("access", ["get", "restore", "start_retry", "chat_retry"])
@pytest.mark.parametrize("signal", ["high", "crisis"])
def test_existing_report_refreshes_screening_risk_without_duplicate_turns(support, access, signal):
    sid, result, store, fake = support
    request = {"session_id": sid, "request_id": "risk-enter",
               "background": {"school_stage": "middle", "current_concern": "考试压力"}}
    first = client.post("/api/healing/start", json=request).json()
    if access == "chat_retry":
        assert chat(sid, first["healing_id"], "还没试", "risk-answer").status_code == 200
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    calls = len(fake.calls)
    update_screening_risk(sid, crisis=signal == "crisis",
                          level="low" if signal == "crisis" else "high",
                          score=0 if signal == "crisis" else .9)
    screening = session_manager.get_session(sid)
    records = store.list_by_student(screening.student_ref)
    fake.fail = True  # Recovery and retries must not need a model for referral.
    if access == "get":
        response = client.get(f"/api/healing/{sid}")
    elif access == "restore":
        response = start(sid)
    elif access == "start_retry":
        response = client.post("/api/healing/start", json=request)
    else:
        response = chat(sid, first["healing_id"], "还没试", "risk-answer")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "referred" and data["risk"]["risk_level"] == "high"
    assert data["risk"]["requires_intervention"]
    assert data["report"]["suggestions"] == [] and data["report"]["question"] is None
    assert data["healing_id"] == first["healing_id"]
    assert data["assessment_result_id"] == result["result_id"]
    state = healing.healing_store.slot(sid).state
    assert not any(item.active for item in state.suggestions)
    assert state.turn_count == before.turn_count and state.feedback == before.feedback
    assert state.receipts == before.receipts and state.context_updates == before.context_updates
    assert len(state.messages) <= len(before.messages) + 1
    assert client.get(f"/api/healing/{sid}").json() == data
    assert start(sid).json() == data and len(fake.calls) == calls
    assert session_manager.get_session(sid) == screening
    assert store.list_by_student(screening.student_ref) == records


@pytest.mark.parametrize("previous_status", ["paused", "ended"])
def test_paused_or_ended_report_still_observes_new_screening_risk(support, previous_status):
    sid, _, _, fake = support
    first = start(sid).json()
    text = "先暂停" if previous_status == "paused" else "不想继续聊了"
    assert chat(sid, first["healing_id"], text).json()["status"] == previous_status
    update_screening_risk(sid)
    assert client.get(f"/api/healing/{sid}").json()["status"] == "referred"
    update_screening_risk(sid, level="low", score=0)
    fake.fail = True
    data = start(sid).json()
    assert data["status"] == "referred" and data["risk"]["risk_level"] == "high"
    assert not data["report"]["suggestions"]


def test_referral_escalates_to_new_high_risk_only_once(support):
    sid, _, _, fake = support
    fake.referral = True
    first = start(sid).json()
    assert first["status"] == "referred" and first["risk"]["risk_level"] == "medium"
    update_screening_risk(sid)
    data = client.get(f"/api/healing/{sid}").json()
    assert data["risk"]["risk_level"] == "high"
    assert data["report"]["understanding"] != first["report"]["understanding"]
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert start(sid).json() == data
    assert healing.healing_store.slot(sid).state == state


def test_screening_chat_risk_is_seen_by_existing_healing_report(support, policy_stub):
    sid, result, store, fake = support
    first = start(sid).json()
    policy_stub()
    response = client.post("/api/chat", json={"session_id": sid, "text": "我想自杀"})
    assert response.status_code == 200, response.text
    screening = session_manager.get_session(sid)
    assert screening.latest_risk.requires_intervention and screening.crisis_mode
    records = store.list_by_student(screening.student_ref)
    calls = len(fake.calls)
    data = client.get(f"/api/healing/{sid}").json()
    assert data["status"] == "referred" and data["risk"]["risk_level"] == "high"
    assert data["assessment_result_id"] == result["result_id"] and len(fake.calls) == calls
    assert session_manager.get_session(sid) == screening
    assert store.list_by_student(screening.student_ref) == records


@pytest.mark.parametrize("access", ["get", "restore", "chat_retry"])
def test_new_assessment_transcript_risk_is_seen_without_rebinding_report(support, access):
    sid, result, store, fake = support
    first = start(sid).json()
    if access == "chat_retry":
        assert chat(sid, first["healing_id"], "还没试", "assessment-risk-answer").status_code == 200
    assessment_response = client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": "我想自杀"}],
    }})
    assert assessment_response.status_code == 200, assessment_response.text
    latest = assessment_response.json()["result"]
    assert latest["risk"]["requires_intervention"] and latest["result_id"] != result["result_id"]
    # Assessment accepts transcripts without writing risk into latest_risk.
    screening = session_manager.get_session(sid)
    assert screening.latest_risk.risk_level == "low"
    records = store.list_by_student(screening.student_ref)
    calls = len(fake.calls)
    fake.fail = True
    if access == "get":
        response = client.get(f"/api/healing/{sid}")
    elif access == "restore":
        response = start(sid)
    else:
        response = chat(sid, first["healing_id"], "还没试", "assessment-risk-answer")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "referred" and data["risk"]["risk_level"] == "high"
    assert data["assessment_result_id"] == result["result_id"] and data["healing_id"] == first["healing_id"]
    assert data["report"]["suggestions"] == [] and data["report"]["question"] is None
    assert start(sid).json() == data and len(fake.calls) == calls
    assert session_manager.get_session(sid) == screening
    assert store.list_by_student(screening.student_ref) == records


@pytest.mark.parametrize("operation", ["initial", "regenerate", "chat"])
@pytest.mark.parametrize("fails", [False, True])
def test_risk_update_during_generation_cannot_publish_active_methods(support, monkeypatch, operation, fails):
    sid, _, _, fake = support
    first = start(sid).json() if operation != "initial" else None
    previous = healing.healing_store.slot(sid).state
    previous = previous.model_copy(deep=True) if previous else None
    if operation == "chat":
        fake.feedback = [Feedback(suggestion_id=previous.suggestions[0].suggestion_id,
            execution="attempted", effect="ineffective", evidence="我试了但没用")]
    original_generate = fake.generate
    async def run():
        generating, released = asyncio.Event(), asyncio.Event()
        async def delayed(system, payload, schema, **kwargs):
            if schema is AgentDraft:
                generating.set()
                await released.wait()
                if fails:
                    raise HealingUnavailable("synthetic late failure")
            return await original_generate(system, payload, schema, **kwargs)
        monkeypatch.setattr(fake, "generate", delayed)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
            if operation == "chat":
                pending = asyncio.create_task(http.post("/api/healing/chat", json={
                    "session_id": sid, "healing_id": first["healing_id"], "message_id": "late-answer",
                    "text": "我试了但没用"}))
            else:
                pending = asyncio.create_task(http.post("/api/healing/start", json={
                    "session_id": sid, "request_id": "late-enter", "regenerate": operation == "regenerate",
                    "expected_healing_id": first["healing_id"] if first else None,
                    "background": {"school_stage": "middle", "current_concern": "考试压力"}}))
            await asyncio.wait_for(generating.wait(), timeout=3)
            update_screening_risk(sid)
            screening = session_manager.get_session(sid)
            released.set()
            response = await asyncio.wait_for(pending, timeout=3)
            assert response.status_code == (503 if fails else 200), response.text
            if not fails:
                data = response.json()
                assert data["status"] == "referred" and data["risk"]["risk_level"] == "high"
                assert data["report"]["suggestions"] == [] and data["report"]["question"] is None
                state = healing.healing_store.slot(sid).state
                assert not any(item.active for item in state.suggestions)
                if operation == "chat":
                    assert state.feedback == previous.feedback  # Discard the unsafe late ordinary reply.
                    assert state.suggestions == [item.model_copy(update={"active": False}) for item in previous.suggestions]
                    assert state.turn_count == previous.turn_count + 1
                    assert [item.role for item in state.messages[len(previous.messages):]] == ["user", "assistant"]
                    assert state.memory_update_suggestions == previous.memory_update_suggestions
                    assert "late-answer" in state.receipts
            else:
                state = healing.healing_store.slot(sid).state
                if previous is not None:
                    assert state.status == "referred" and not any(item.active for item in state.suggestions)
                    assert state.healing_id == previous.healing_id and state.feedback == previous.feedback
                    assert state.turn_count == previous.turn_count and state.receipts == previous.receipts
                else:
                    assert state is None  # A failed first generation has no accepted report.
            assert session_manager.get_session(sid) == screening
    asyncio.run(run())


@pytest.mark.parametrize("text,refers", [("我没有想自杀", False), ("我没有想自杀，但我被同学威胁", True)])
def test_current_screening_text_risk_keeps_negation_local(support, text, refers):
    sid, result, _, fake = support
    first = start(sid).json()
    assert client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": text}],
    }}).status_code == 200
    calls = len(fake.calls)
    data = client.get(f"/api/healing/{sid}").json()
    assert (data["status"] == "referred") == refers
    assert data["assessment_result_id"] == result["result_id"] and len(fake.calls) == calls
    if not refers:
        assert data == first  # Updating ordinary text cannot change the bound report.


def test_report_uses_record_and_hides_evidence_without_modifying_screening(support):
    sid, result, store, fake = support
    before = session_manager.get_session(sid)
    records = store.list_by_student(before.student_ref)
    response = start(sid)
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["assessment_result_id"] == result["result_id"]
    assert data["report"]["suggestions"][0]["steps"] == knowledge().steps
    assert data["report"]["question"].count("？") == 1
    assert "source_url" not in response.text and "knowledge_id" not in response.text
    assert "method_key" not in response.text and "example.org" not in response.text
    assert chat(sid, data["healing_id"], "还没试").status_code == 200
    assert session_manager.get_session(sid) == before
    assert store.list_by_student(before.student_ref) == records
    assert fake.calls[0]["memory"]["provenance"]["assessment"] == "persistent_evaluation_record"


def test_missing_age_and_unknown_concern_degrade_without_inventing_methods(support):
    sid, _, _, fake = support
    response = start(sid, background={})
    assert response.status_code == 200
    assert response.json()["report"]["suggestions"] == []
    assert len(fake.calls) == 0
    # All-zero profile without current text is not evidence of low mood.
    state = healing.healing_store.slot(sid).state
    memory = state.memory.model_copy(update={"current_session_messages": []})
    assert choose_scene("", memory) == "general"
    assert choose_scene("现在最困扰的是睡不着", memory) == "sleep"
    assert choose_scene("现在是人际困扰，关系很紧张", memory) == "relationships"


def test_filters_run_before_ranking_and_old_retriever_stays_compatible():
    retriever = HealingRetriever([knowledge(), knowledge("adult", executor="adult"),
                                 knowledge("pending", status="pending"), knowledge("sleep", scene="sleep")])
    assert [hit.item.knowledge_id for hit in retriever.retrieve("考试压力", "study_stress", HealingBackground(school_stage="middle"))] == ["name-concern"]
    assert retriever.retrieve("考试压力", "study_stress", HealingBackground(school_stage="high")) == []
    assert retriever.retrieve("考试压力", "study_stress", HealingBackground()) == []
    assert retriever.retrieve("考试压力", "study_stress", HealingBackground(school_stage="middle", adult_support_available=False)) == []
    assert retriever.retrieve("考试压力", "study_stress", HealingBackground(school_stage="middle"), {"name-concern"}) == []
    from backend.rag.retriever import retrieve
    assert all(isinstance(item, str) for item in retrieve("情绪低落"))


def test_source_intervals_scope_and_semantic_counterexamples():
    original = knowledge()
    assert validate_item(original, SOURCE, [(0, len(SOURCE))], []).status == "usable"
    assert validate_item(original, SOURCE, [(0, 2)], []).status == "pending"
    assert validate_item(original, SOURCE, [(0, len(SOURCE))], None).status == "pending"
    medical = original.model_copy(update={"prerequisites": ["成人指导，完成必要医学评估"]})
    assert "medical_prerequisite_unconfirmed" in validate_item(medical, SOURCE, [(0, len(SOURCE))], []).validation_issues
    for issue, bad in [
        ("age_expanded", original.model_copy(update={"age_min": 6, "age_max": 18})),
        ("executor_changed", original.model_copy(update={"executor": "student"})),
        ("prerequisite_missing", original.model_copy(update={"prerequisites": []})),
        ("unsupported_step", original.model_copy(update={"steps": ["独自做十次呼吸练习"]})),
    ]:
        checked = validate_item(bad, SOURCE, [(0, len(SOURCE))], [issue])
        assert checked.status == "pending" and issue in checked.validation_issues
    bad_interval = original.model_copy(deep=True)
    bad_interval.evidence[0].start = 2
    assert "source_interval_mismatch" in validate_item(bad_interval, SOURCE, [(0, len(SOURCE))], []).validation_issues


def test_duplicate_start_and_chat_retry_generate_once_and_conflicts_fail(support):
    sid, _, _, fake = support
    request = {"session_id": sid, "request_id": "enter", "background": {"school_stage": "middle", "current_concern": "考试压力"}}
    first = client.post("/api/healing/start", json=request).json()
    second = client.post("/api/healing/start", json=request).json()
    assert first["healing_id"] == second["healing_id"] and len(fake.calls) == 1
    before = len(fake.calls)
    one = chat(sid, first["healing_id"], "还没试", "answer")
    two = chat(sid, first["healing_id"], "还没试", "answer")
    assert one.json() == two.json() and len(fake.calls) == before + 1
    assert chat(sid, first["healing_id"], "不同回答", "answer").status_code == 409
    assert client.post("/api/healing/start", json={**request, "regenerate": True}).status_code == 409


def test_concurrent_enter_serializes_and_different_sessions_can_progress(support):
    sid, _, _, fake = support
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
            requests = [http.post("/api/healing/start", json={"session_id": sid, "request_id": str(i),
                "background": {"school_stage": "middle", "current_concern": "考试压力"}}) for i in range(3)]
            responses = await asyncio.gather(*requests)
            assert all(item.status_code == 200 for item in responses)
            assert len({item.json()["healing_id"] for item in responses}) == 1
    asyncio.run(run())
    assert len(fake.calls) == 1


def test_generation_failure_preserves_previous_feedback_and_binding(support):
    sid, result, store, fake = support
    first = start(sid).json()
    state = healing.healing_store.slot(sid).state
    fake.fail = True
    response = chat(sid, first["healing_id"], "试了但没用")
    assert response.status_code == 503
    assert healing.healing_store.slot(sid).state == state
    response = start(sid, regenerate=True, expected_healing_id=first["healing_id"])
    assert response.status_code == 503
    assert healing.healing_store.slot(sid).state == state
    fake.fail = False
    # A later assessment does not silently rebind an ongoing support conversation.
    second = client.post("/api/assessment", json={"session_id": sid}).json()["result"]
    assert start(sid).json()["assessment_result_id"] == result["result_id"]
    regenerated = start(sid, regenerate=True, expected_healing_id=first["healing_id"]).json()
    assert regenerated["assessment_result_id"] == second["result_id"]
    assert regenerated["healing_id"] != first["healing_id"]
    assert chat(sid, first["healing_id"], "迟到的回答").status_code == 409


def test_not_attempted_preparation_and_ineffective_feedback_are_distinct(support):
    sid, _, _, fake = support
    response = start(sid).json()
    hid = response["healing_id"]
    state = healing.healing_store.slot(sid).state
    target = state.suggestions[0].suggestion_id
    fake.feedback = [Feedback(suggestion_id=target, execution="not_attempted", evidence="还没试")]
    assert chat(sid, hid, "还没试").status_code == 200
    assert healing.healing_store.slot(sid).state.suggestions[0].execution == "not_attempted"
    chat(sid, hid, "现在准备试试")
    assert healing.healing_store.slot(sid).state.suggestions[0].execution == "prepared"
    fake.feedback = [Feedback(suggestion_id=target, execution="attempted", effect="ineffective", evidence="试了但没用")]
    fake.recommendations = [state.suggestions[0].knowledge_id]
    chat(sid, hid, "试了但没用")
    state = healing.healing_store.slot(sid).state
    assert state.suggestions[0].execution == "attempted" and state.suggestions[0].effect == "ineffective"
    assert not state.suggestions[0].active
    assert student_view(state).report.suggestions[0].active is False
    assert len(state.suggestions) == 1
    assert state.memory_update_suggestions[-1]["persisted"] is False


def test_unsubstantiated_feedback_and_methods_are_rejected(support):
    sid, _, _, fake = support
    response = start(sid).json()
    target = healing.healing_store.slot(sid).state.suggestions[0].suggestion_id
    fake.feedback = [Feedback(suggestion_id=target, execution="attempted", effect="helpful", evidence="准备试试")]
    chat(sid, response["healing_id"], "我准备试试")
    assert healing.healing_store.slot(sid).state.suggestions[0].execution != "attempted"
    fake.feedback = []
    fake.recommendations = ["invented-knowledge"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert chat(sid, response["healing_id"], "我有点担心").status_code == 503
    assert healing.healing_store.slot(sid).state == before


def test_new_crisis_blocks_methods_and_retains_screening(support):
    sid, _, _, fake = support
    response = start(sid).json()
    before = session_manager.get_session(sid)
    calls = len(fake.calls)
    data = chat(sid, response["healing_id"], "我想自杀").json()
    assert data["status"] == "referred" and data["risk"]["requires_intervention"]
    assert "联系" in data["messages"][-1]["content"] and "？" not in data["messages"][-1]["content"]
    assert len(fake.calls) == calls and session_manager.get_session(sid) == before
    assert data["report"]["suggestions"] == [] and data["report"]["question"] is None


def test_existing_crisis_and_model_safety_flag_route_without_interview(support):
    sid, _, _, fake = support
    session_manager.modify_session(sid, lambda session: setattr(session, "crisis_mode", True))
    data = start(sid).json()
    assert data["status"] == "referred" and data["report"]["question"] is None
    assert data["report"]["suggestions"] == [] and not fake.calls


def test_retrieval_failure_degrades_and_restart_cannot_invent_old_history(support):
    sid, _, _, fake = support
    class Broken:
        def retrieve(self, *args, **kwargs):
            raise OSError("test unavailable")
    healing.healing_agent.retriever = Broken()
    first = start(sid).json()
    assert first["report"]["suggestions"] == []
    assert not fake.calls
    healing.healing_store.slots.clear()
    response = client.get(f"/api/healing/{sid}")
    assert response.status_code == 404 and response.json()["error"]["code"] == "HEALING_NOT_FOUND"
    assert chat(sid, first["healing_id"], "继续").status_code == 404


def test_pause_stop_and_missing_assessment(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    paused = chat(sid, hid, "现在准备试试").json()
    assert paused["status"] == "paused" and paused["report"]["question"] is None
    assert chat(sid, hid, "不想继续聊了").json()["status"] == "ended"
    assert chat(sid, hid, "继续").status_code == 409
    other = client.post("/api/session").json()["session_id"]
    assert start(other).status_code == 409
    assert start("missing-session").status_code == 404


def test_explicit_age_is_not_accepted_by_start_interface():
    response = client.post("/api/healing/start", json={"session_id": "s", "request_id": "r",
                                                     "background": {"age": 6, "school_stage": "high"}})
    assert response.status_code == 422


def test_feedback_cannot_turn_negative_effect_or_ordinary_answer_into_success(support):
    sid, _, _, fake = support
    start(sid)
    state = healing.healing_store.slot(sid).state
    target = state.suggestions[0].suggestion_id
    assert HealingAgent.apply_feedback(state, [Feedback(suggestion_id=target, execution="attempted",
        effect="helpful", evidence="我试了但没有帮助")], "我试了但没有帮助") == []
    assert HealingAgent.apply_feedback(state, [Feedback(suggestion_id=target, execution="prepared",
        evidence="我很紧张")], "我很紧张") == []
    assert state.suggestions[0].execution == "unconfirmed"


def test_ordinal_feedback_does_not_reject_another_method(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    start(sid)
    state = healing.healing_store.slot(sid).state
    second = state.suggestions[1]
    text = "第一个方法我试了但没用"
    assert HealingAgent.apply_feedback(state, [Feedback(suggestion_id=second.suggestion_id,
        execution="attempted", effect="ineffective", evidence=text)], text) == []
    assert second.active


def test_bullying_uses_existing_help_flow_and_wanting_less_stress_is_not_a_stop(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    assert chat(sid, hid, "我不想继续这么紧张").json()["status"] == "active"
    assert chat(sid, hid, "没有被威胁，也没有霸凌").json()["status"] == "active"
    before = len(fake.calls)
    response = chat(sid, hid, "我被同学威胁，不交钱就殴打我").json()
    assert response["status"] == "referred" and len(fake.calls) == before
    assert response["report"]["suggestions"] == []


def test_pause_alone_does_not_invent_action_preparation(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    response = chat(sid, hid, "先暂停").json()
    current = healing.healing_store.slot(sid).state
    assert response["status"] == "paused"
    assert current.suggestions == state.suggestions and current.feedback == state.feedback
    assert current.memory_update_suggestions == state.memory_update_suggestions


def test_multiple_goals_confirm_before_methods_and_keep_selected_goal(support):
    sid, _, _, fake = support
    data = start(sid, background={"school_stage": "middle", "current_concern": "考试紧张，也总是睡不着", "adult_support_available": True}).json()
    assert data["report"]["suggestions"] == [] and not fake.calls
    assert data["report"]["question"].count("？") == 1
    confirmed = chat(sid, data["healing_id"], "先聊考试压力").json()
    assert confirmed["status"] == "active"
    state = healing.healing_store.slot(sid).state
    assert state.scene == "study_stress" and state.suggestions
    assert chat(sid, state.healing_id, "昨天没睡好所以更紧张").status_code == 200
    assert healing.healing_store.slot(sid).state.scene == "study_stress"


def test_explicit_priority_outvotes_more_background_keywords():
    from backend.healing.interaction import resolve_goal
    goal = resolve_goal("睡不着、失眠、熬夜让我累，但现在最困扰的是考试紧张")
    assert goal.scene == "study_stress" and not goal.needs_confirmation
    assert "考试" in goal.evidence
    assert resolve_goal("同学关系很紧张").scene == "relationships"


@pytest.mark.parametrize("age,expected", [(6, "simple"), (10, "simple"), (11, "conversational"),
    (13, "conversational"), (14, "autonomous"), (18, "autonomous")])
def test_age_specific_expression_does_not_infer_source_ages(support, age, expected):
    from backend.healing.interaction import communication_style
    assert communication_style(HealingBackground(age=age)) == expected
    sid, _, _, fake = support
    save_demographic_assessment(sid, "我12岁，上初一，最近考试压力很大")
    start(sid, background={"current_concern": "考试压力"})
    assert fake.calls[0]["communication"]["style"] == "conversational"
    assert "比较" in fake.calls[0]["communication"]["instructions"]
    assert fake.calls[0]["knowledge"][0]["age_min"] is None


@pytest.mark.parametrize("change", ["missing_object", "missing_score", "missing_intervention", "defaults_on_save"])
def test_incomplete_stored_risk_blocks_support_without_false_crisis(support, change):
    import json
    sid, _, store, fake = support
    record = store.list_by_student(sid)[-1]
    if change == "defaults_on_save":
        result = record.result.model_copy(update={"result_id": str(uuid4()), "risk": RiskResult()})
        # Keep report binding valid while testing loss of field provenance.
        result.report = result.report.model_copy(deep=True)
        result.report.metadata.assessment_id = result.result_id
        store.save_result(result)
    else:
        raw = record.model_dump(mode="json")
        if change == "missing_object":
            raw["result"].pop("risk")
        else:
            raw["result"]["risk"].pop("risk_score" if change == "missing_score" else "requires_intervention")
        with store._connection() as connection:
            connection.execute("UPDATE assessment_records SET payload = ? WHERE record_id = ?",
                               (json.dumps(raw), record.record_id))
    data = start(sid).json()
    assert data["status"] == "referred" and not fake.calls
    assert data["report"]["suggestions"] == [] and data["report"]["question"] is None
    assert "不表示" in data["report"]["understanding"]
    assert data["risk"]["risk_level"] == "medium"


@pytest.mark.parametrize("updates", [
    {"risk_level": "low", "risk_score": .9, "requires_intervention": False},
    {"risk_level": "high", "risk_score": .2, "requires_intervention": False},
    {"risk_level": "low", "risk_score": .1, "requires_intervention": True},
    {"risk_level": "low", "risk_score": .1, "requires_intervention": False, "key_evidence": ["我想自杀"]},
])
def test_conflicting_risk_values_never_admit_ordinary_methods(support, updates):
    from backend.healing.safety import guard_risk
    sid, _, _, _ = support
    start(sid)
    state = healing.healing_store.slot(sid).state
    memory = state.memory.model_copy(deep=True)
    memory.assessment.risk = RiskResult(**updates)
    risk = guard_risk(memory)
    assert risk is not None and risk.requires_intervention


@pytest.mark.parametrize("text,refers", [
    ("我计划今晚跳楼", True), ("我今晚不打算跳楼", False),
    ("我不打算今晚跳楼", False), ("我没有计划明天吞药", False),
    ("我今晚不打算跳楼，但明天准备吞药", True),
    ("我已经完全无法上学", True), ("我没有完全无法上学，今天只是迟到", False),
    ("连续三天没睡", True), ("我越来越难受", True), ("我不是越来越难受", False),
    ("朋友和我因为座位吵架了", False),
])
def test_plan_function_and_worsening_routes_with_negative_controls(support, text, refers):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    before = len(fake.calls)
    data = chat(sid, hid, text).json()
    assert (data["status"] == "referred") == refers
    if refers:
        assert len(fake.calls) == before and data["report"]["suggestions"] == []
        assert "已经联系" not in data["messages"][-1]["content"]


def test_explicit_constraints_and_previous_failures_filter_before_generation(support):
    sid, _, _, fake = support
    fake.fit_overrides = {"name-concern": {"verdict": "blocked", "evidence": "说出困扰这个方法试过没有帮助",
                                          "reason": "明确反馈同一方法无效"}}
    data = start(sid, background={"school_stage": "middle", "current_concern": "考试压力",
        "previous_attempts": ["说出困扰这个方法试过没有帮助"], "adult_support_available": True}).json()
    assert data["report"]["suggestions"][0]["title"] == "另一种压力表达"
    assert [item["knowledge_id"] for item in fake.calls[0]["knowledge"]] == ["other"]
    assert not healing.healing_store.slot(sid).state.feedback


def test_new_execution_limitation_deactivates_old_action_without_inventing_attempt(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    fake.fit_overrides = {key: {"verdict": "blocked", "evidence": "没有成人能陪我", "reason": "必要成人不可用"}
                          for key in ["name-concern", "other"]}
    assert chat(sid, hid, "没有成人能陪我").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert not state.suggestions[0].active and not state.feedback


def test_verified_simplification_keeps_original_conditions_and_feedback_identity(support):
    from backend.models.healing import KnowledgeWording
    sid, _, _, fake = support
    item = knowledge(wordings=[KnowledgeWording(wording_id="simple-1", style="simple", title="说说担心",
        goal="弄清楚你担心的事", steps=["和可信成人一起，说出考试让你担心的事。"], semantic_checked=True)])
    healing.healing_agent.retriever = HealingRetriever([item])
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.suggestions[0].model_copy(deep=True)
    fake.simplify_id = before.suggestion_id
    assert chat(sid, hid, "这段话太复杂，可以简单一点吗").status_code == 200
    after = healing.healing_store.slot(sid).state.suggestions[0]
    assert after.suggestion_id == before.suggestion_id and after.knowledge_id == before.knowledge_id
    assert after.steps == item.wordings[0].steps and after.prerequisites == before.prerequisites
    assert after.execution == "unconfirmed" and after.revisions[0]["previous_steps"] == before.steps
    fake.simplify_id = None
    fake.feedback = [Feedback(suggestion_id=after.suggestion_id, execution="attempted", effect="ineffective", evidence="试了但没用")]
    assert chat(sid, hid, "试了但没用").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert not state.suggestions[0].active
    assert HealingAgent.simplify(state, after.suggestion_id, "能简单一点吗") is None


def test_repeated_noninformative_answers_pause_without_resetting_progress(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    assert chat(sid, hid, "不知道").json()["status"] == "active"
    calls = len(fake.calls)
    assert chat(sid, hid, "不知道。").json()["status"] == "paused"
    state = healing.healing_store.slot(sid).state
    assert len(fake.calls) == calls and state.suggestions[0].execution == "unconfirmed"
    assert not state.feedback


def test_explanatory_knowledge_can_inform_prose_but_never_becomes_steps(support):
    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([knowledge(purpose="explanation", status="explanation_only",
        steps=[], title="了解考试压力", goal="考试压力可能让人感到紧张，原因仍需要了解。")])
    data = start(sid).json()
    assert data["report"]["suggestions"] == []
    assert fake.calls[0]["explanations"][0]["explanation"].startswith("考试压力")
    assert fake.calls[0]["knowledge"] == []


def test_explicit_goal_switch_is_not_misread_as_ending(support):
    sid, _, _, fake = support
    start(sid)
    state = healing.healing_store.slot(sid).state
    response = chat(sid, state.healing_id, "不想聊考试，换成睡眠").json()
    assert response["status"] == "active"
    current = healing.healing_store.slot(sid).state
    assert current.scene == "sleep" and not current.suggestions[0].active


def test_pause_appends_timing_without_rewriting_report_audit(support):
    sid, _, _, _ = support
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert chat(sid, hid, "先暂停").status_code == 200
    current = healing.healing_store.slot(sid).state
    assert current.audit[:-1] == before.audit
    assert current.audit[-1]["phase"] == "state_transition"
    assert current.audit[-1]["model_calls"] == []


def test_simplification_without_approved_variant_keeps_original(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.suggestions[0].model_copy(deep=True)
    fake.simplify_id = before.suggestion_id
    assert chat(sid, hid, "看不懂，能简单一点吗").status_code == 200
    after = healing.healing_store.slot(sid).state.suggestions[0]
    assert after == before


@pytest.mark.parametrize("knowledge_id,background", [
    ("heal-484883ea4f1c", {"age": 16, "school_stage": "high", "current_concern": "想先聊睡眠，白天运动少，最近总是晚睡"}),
    ("heal-53bb4aef2601", {"age": 11, "school_stage": "primary", "current_concern": "想先聊心情，最近有点难过"}),
])
def test_expanded_knowledge_simplifies_without_losing_identity_or_feedback(support, knowledge_id, background):
    from backend.healing.knowledge import load_knowledge
    sid, _, _, fake = support
    item = next(value for value in load_knowledge() if value.knowledge_id == knowledge_id)
    healing.healing_agent.retriever = HealingRetriever([item])
    grade = "高一" if background["school_stage"] == "high" else "五年级"
    save_demographic_assessment(sid, f"我{background['age']}岁，上{grade}。{background['current_concern']}")
    response = start(sid, background={key: value for key, value in background.items() if key != "age"})
    assert response.status_code == 200, response.json()
    hid = response.json()["healing_id"]
    assert response.json()["report"]["suggestions"], response.json()
    before = healing.healing_store.slot(sid).state.suggestions[0].model_copy(deep=True)
    style = "conversational" if background["age"] <= 13 else "autonomous"
    wording = next(value for value in item.wordings if value.style == style)
    assert before.wording_id == wording.wording_id and before.steps == wording.steps
    assert before.prerequisites == item.prerequisites
    fake.feedback = [Feedback(suggestion_id=before.suggestion_id, execution="not_attempted",
                              effect="unknown", evidence="还没试")]
    assert chat(sid, hid, "我还没试").status_code == 200
    feedback_before = healing.healing_store.slot(sid).state.feedback.copy()
    fake.feedback = []
    fake.simplify_id = before.suggestion_id
    assert chat(sid, hid, "这个方法看不懂，可以用简单的话说吗").status_code == 200
    state = healing.healing_store.slot(sid).state
    changed = state.suggestions[0]
    simple = next(value for value in item.wordings if value.style == "simple")
    assert changed.steps == simple.steps and changed.wording_id == simple.wording_id
    assert changed.suggestion_id == before.suggestion_id and changed.knowledge_id == before.knowledge_id
    assert changed.method_key == before.method_key and changed.prerequisites == before.prerequisites
    assert changed.cautions == before.cautions and changed.active
    assert changed.execution == "not_attempted" and changed.effect == "unknown"
    assert state.feedback == feedback_before and len(changed.revisions) == 1


def test_feedback_ordinal_preserves_reference_after_constraint_filter(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    start(sid)
    state = healing.healing_store.slot(sid).state
    before = state.model_copy(deep=True)
    state.suggestions[0].active = False
    text = "第一个方法我试了但没用"
    wrong = Feedback(suggestion_id=state.suggestions[1].suggestion_id, execution="attempted",
                     effect="ineffective", evidence=text)
    assert HealingAgent.apply_feedback(state, [wrong], text, before.suggestions) == []
    right = wrong.model_copy(update={"suggestion_id": state.suggestions[0].suggestion_id})
    assert HealingAgent.apply_feedback(state, [right], text, before.suggestions)
    assert state.suggestions[1].execution == "unconfirmed"


def test_adjustment_retains_at_most_two_active_methods(support):
    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([knowledge(key) for key in ["name-concern", "other", "third", "fourth"]])
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    state = healing.healing_store.slot(sid).state
    fake.recommendations = ["third", "fourth"]
    fake.feedback = [Feedback(suggestion_id=state.suggestions[0].suggestion_id, execution="attempted",
        effect="ineffective", evidence="第一个方法我试了但没用")]
    assert chat(sid, hid, "第一个方法我试了但没用").status_code == 200
    current = healing.healing_store.slot(sid).state
    assert sum(item.active for item in current.suggestions) == 2
    assert len(current.suggestions) == 3


def test_feedback_alone_does_not_filter_untried_candidate(support):
    from backend.healing.suitability import filter_context
    class NoCalls:
        async def generate(self, *args, **kwargs):
            raise AssertionError("pure feedback should use its bound action")
    hits = HealingRetriever([knowledge()]).retrieve("考试压力", "study_stress", HealingBackground(school_stage="middle"))
    kept, removed = asyncio.run(filter_context(NoCalls(), hits, HealingBackground(), "第一个方法我试了，但没有帮助"))
    assert kept == hits and removed == []


def test_source_help_is_kept_as_caution_only_for_same_verified_scope():
    from backend.healing.knowledge import attach_source_help
    method = knowledge()
    helper = knowledge("help", purpose="help", status="explanation_only", goal="持续困扰时告诉可信成人。")
    other = knowledge("other-source", source_id="another")
    rejected = helper.model_copy(update={"validation_issues": ["unsupported_step"]})
    assert not attach_source_help([method, rejected])[0].referral_conditions
    results = attach_source_help([method, helper, other])
    assert results[0].referral_conditions == [helper.goal]
    assert results[0].steps == method.steps
    assert not results[2].referral_conditions


def test_rejected_narrative_uses_checked_fallback_with_original_method(support):
    sid, _, _, _ = support
    class UngroundedClient(FakeClient):
        async def generate(self, system, payload, schema, **kwargs):
            if schema is NarrativeCheck:
                return NarrativeCheck(valid=payload["understanding"] != "你最近每晚只睡三小时。",
                    issues=["unsupported_fact"] if payload["understanding"] == "你最近每晚只睡三小时。" else [])
            draft = await super().generate(system, payload, schema, **kwargs)
            if schema is AgentDraft:
                draft.understanding = "你最近每晚只睡三小时。"
            return draft
    healing.healing_agent.client = UngroundedClient()
    response = start(sid)
    assert response.status_code == 200
    assert "三小时" not in response.text
    state = healing.healing_store.slot(sid).state
    assert state.audit[-1]["narrative_fallback"]
    assert state.suggestions[0].steps == knowledge().steps
    assert not state.feedback


def test_later_effect_can_use_an_already_confirmed_attempt(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    target = healing.healing_store.slot(sid).state.suggestions[0].suggestion_id
    fake.feedback = [Feedback(suggestion_id=target, execution="attempted", evidence="我试了")]
    assert chat(sid, hid, "我试了").status_code == 200
    fake.feedback = [Feedback(suggestion_id=target, execution="attempted", effect="ineffective", evidence="没有帮助")]
    assert chat(sid, hid, "没有帮助").status_code == 200
    suggestion = healing.healing_store.slot(sid).state.suggestions[0]
    assert suggestion.effect == "ineffective" and not suggestion.active


def test_validated_adult_task_is_background_only():
    adult = knowledge("adult", executor="adult", status="explanation_only", title="承认不舒服",
        goal="感受被认真听到", steps=["成人听孩子说出不舒服。"])
    retriever = HealingRetriever([adult])
    background = HealingBackground(age=12, school_stage="middle")
    assert retriever.retrieve("不舒服", "study_stress", background) == []
    assert retriever.retrieve_explanations("不舒服", "study_stress", background) == [adult]


def test_initial_history_is_never_converted_to_current_feedback(support):
    sid, _, _, fake = support
    fake.feedback = [Feedback(suggestion_id="old-unknown-action", execution="attempted",
        effect="ineffective", evidence="过去试过但没有帮助")]
    response = start(sid, background={"school_stage": "middle", "current_concern": "考试压力",
        "previous_attempts": ["过去试过但没有帮助"]})
    assert response.status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.memory.background.previous_attempts == ["过去试过但没有帮助"]
    assert not state.feedback and not state.memory_update_suggestions
    assert all(item.execution == "unconfirmed" for item in state.suggestions)


@pytest.mark.parametrize("text,refers", [
    ("我并不担心考试但现在已经完全无法上学", True),
    ("我并没有和同学吵架可是连续三天没睡", True),
    ("我没有出现考试焦虑但是越来越难受", True),
    ("我现在并没有完全无法上学", False),
    ("我不是一直无法上学", False),
    ("我并没有连续三天没睡", False),
    ("我没有感到越来越难受", False),
    ("我没有完全无法上学但现在完全无法吃饭", True),
])
def test_severe_risk_negation_only_applies_to_its_own_statement(support, text, refers):
    sid, _, _, fake = support
    data = start(sid, background={"current_concern": text}).json()
    assert (data["status"] == "referred") == refers
    assert data["report"]["suggestions"] == [] and not fake.calls
    if refers:
        assert data["report"]["question"] is None


def test_new_constraint_survives_later_turns_and_explicit_correction(support):
    sid, _, _, _ = support

    class ContextClient(FakeClient):
        async def generate(self, system, payload, schema, **kwargs):
            if schema is FitCheck:
                texts = [entry["text"] for entry in payload.get("context_updates", [])]
                if payload["latest_answer"]:
                    texts.append(payload["latest_answer"])
                latest = next((text for text in reversed(texts)
                               if "没有成人能陪我" in text or "有老师能陪我" in text), "")
                blocked = "没有成人能陪我" in latest
                return FitCheck(decisions=[FitDecision(knowledge_id=item["knowledge_id"],
                    verdict="blocked" if blocked else "suitable", evidence=latest if blocked else None)
                    for item in payload["knowledge"]])
            draft = await super().generate(system, payload, schema, **kwargs)
            if schema is AgentDraft:
                draft.recommendation_ids = [item["knowledge_id"] for item in payload.get("knowledge", [])][:1]
            return draft

    healing.healing_agent.client = ContextClient()
    hid = start(sid).json()["healing_id"]
    original_memory = healing.healing_store.slot(sid).state.memory.model_copy(deep=True)
    assert chat(sid, hid, "没有成人能陪我").status_code == 200
    for turn in range(14):
        assert chat(sid, hid, f"我还是担心考试，这次是第{turn}次说起").status_code == 200
        state = healing.healing_store.slot(sid).state
        assert not any(item.active for item in state.suggestions)
        assert not state.feedback and state.memory == original_memory
    assert len(state.context_updates) == 1
    assert state.context_updates[0].text == "没有成人能陪我"
    assert state.context_updates[0].reference_suggestions[0].active
    assert chat(sid, hid, "现在有老师能陪我了").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert any(item.active for item in state.suggestions)
    assert len(state.context_updates) == 2 and state.memory == original_memory


@pytest.mark.parametrize("text", [
    "我不打算尝试这个方法", "我不准备试试", "我现在不想试试", "我没有打算试一下",
])
def test_negated_preparation_never_becomes_prepared_feedback(support, text):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    target = healing.healing_store.slot(sid).state.suggestions[0].suggestion_id
    fake.feedback = [Feedback(suggestion_id=target, execution="prepared", evidence=text)]
    assert chat(sid, hid, text).status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.suggestions[0].execution == "unconfirmed" and not state.feedback


@pytest.mark.parametrize("text,evidence", [
    ("我没有试过这个方法", "我没有试过这个方法"),
    ("我没有试过这个方法", "试过"),
    ("我还没有尝试过这个方法", "尝试过"),
    ("这个方法我并未练过", "练过"),
])
def test_negated_attempt_is_rejected_even_when_evidence_omits_negation(support, text, evidence):
    sid, _, _, _ = support
    start(sid)
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    target = state.suggestions[0].suggestion_id
    feedback = Feedback(suggestion_id=target, execution="attempted", evidence=evidence)
    assert HealingAgent.apply_feedback(state, [feedback], text) == []
    assert not state.feedback and state.suggestions[0].execution == "unconfirmed"


def test_affirmative_execution_after_unrelated_negation_still_counts(support):
    sid, _, _, _ = support
    start(sid)
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    text = "我之前没有试过，但今天试了这个方法"
    feedback = Feedback(suggestion_id=state.suggestions[0].suggestion_id, execution="attempted", evidence=text)
    assert HealingAgent.apply_feedback(state, [feedback], text)
    assert state.suggestions[0].execution == "attempted"


@pytest.mark.parametrize("text,scene", [
    ("我没有睡眠问题，只想聊考试压力", "study_stress"),
    ("不是同学关系的问题，是最近学习压力大", "study_stress"),
    ("睡眠没有问题，我和同学吵架了", "relationships"),
    ("我不想聊考试，只想聊睡眠", "sleep"),
    ("我没有朋友，感到孤独", "relationships"),
    ("我没有睡好", "sleep"),
    ("我没有解决睡眠问题", "sleep"),
    ("不是失眠，是学习压力", "study_stress"),
    ("不是同学关系，而是学习压力", "study_stress"),
    ("考试没有压力，只是失眠", "sleep"),
    ("我不是不难过", "low_mood"),
])
def test_negated_concerns_do_not_create_extra_goals(text, scene):
    from backend.healing.interaction import resolve_goal
    goal = resolve_goal(text)
    assert goal.scene == scene and not goal.needs_confirmation
    assert goal.mentioned_scenes == [scene]


def test_constraint_updates_commit_atomically_and_retry_once(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.fail = True
    mid = str(uuid4())
    assert chat(sid, hid, "没有成人能陪我", mid).status_code == 503
    assert healing.healing_store.slot(sid).state == before
    fake.fail = False
    fake.fit_overrides = {key: {"verdict": "blocked", "evidence": "没有成人能陪我"}
                          for key in ["name-concern", "other"]}
    assert chat(sid, hid, "没有成人能陪我", mid).status_code == 200
    assert chat(sid, hid, "没有成人能陪我", mid).status_code == 200
    state = healing.healing_store.slot(sid).state
    assert len(state.context_updates) == 1 and state.turn_count == 1
    assert state.memory == before.memory and not state.feedback


def test_pause_retains_new_constraint_without_inventing_attempt(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    fake.fit_overrides = {key: {"verdict": "blocked", "evidence": "没有成人能陪我"}
                          for key in ["name-concern", "other"]}
    assert chat(sid, hid, "没有成人能陪我，先暂停").json()["status"] == "paused"
    state = healing.healing_store.slot(sid).state
    assert state.context_updates[0].text == "没有成人能陪我，先暂停"
    assert not state.feedback
    assert not any(item.active for item in state.suggestions)
    assert not student_view(state).report.suggestions[0].active
    assert chat(sid, hid, "我还是想谈考试").status_code == 200
    assert not any(item.active for item in healing.healing_store.slot(sid).state.suggestions)


def test_negated_concern_enters_matching_report_without_confirmation(support):
    sid, _, _, _ = support
    data = start(sid, background={"school_stage": "middle",
        "current_concern": "我没有睡眠问题，只想聊考试压力", "adult_support_available": True}).json()
    state = healing.healing_store.slot(sid).state
    assert state.scene == "study_stress" and not state.goal.needs_confirmation
    assert data["report"]["suggestions"]
    assert "context_updates" not in data


def test_persisted_ordinal_constraint_keeps_original_method_reference(support):
    sid, _, _, _ = support

    class ScopedClient(FakeClient):
        async def generate(self, system, payload, schema, **kwargs):
            if schema is FitCheck:
                blocked = {entry["reference_suggestions"][0]["knowledge_id"]
                           for entry in payload.get("context_updates", [])
                           if "第一个方法太难" in entry["text"] and entry["reference_suggestions"]}
                return FitCheck(decisions=[FitDecision(knowledge_id=item["knowledge_id"],
                    verdict="blocked" if item["knowledge_id"] in blocked else "suitable",
                    evidence="第一个方法太难" if item["knowledge_id"] in blocked else None)
                    for item in payload["knowledge"]])
            draft = await super().generate(system, payload, schema, **kwargs)
            if schema is AgentDraft:
                draft.recommendation_ids = [item["knowledge_id"] for item in payload.get("knowledge", [])][
                    :2 if payload["phase"] == "report" else 1]
            return draft

    healing.healing_agent = HealingAgent(ScopedClient(), HealingRetriever([
        knowledge(), knowledge("other", title="另一种压力表达"), knowledge("third", title="第三种压力表达")]))
    hid = start(sid).json()["healing_id"]
    original = healing.healing_store.slot(sid).state.suggestions[0].knowledge_id
    assert chat(sid, hid, "第一个方法太难").status_code == 200
    for text in ["考试还是让我担心", "我想再聊一下"]:
        assert chat(sid, hid, text).status_code == 200
        state = healing.healing_store.slot(sid).state
        assert state.context_updates[0].reference_suggestions[0].knowledge_id == original
        assert not next(item for item in state.suggestions if item.knowledge_id == original).active
        assert sum(item.active for item in state.suggestions) == 2


@pytest.mark.parametrize("text,refers", [
    ("我不开心想自杀", True),
    ("我没有朋友想自杀", True),
    ("我没有希望想自杀", True),
    ("我不是不想自杀", True),
    ("我不想自杀", False),
    ("我并没有想要伤害自己", False),
    ("I don't want to kill myself", False),
    ("I am not happy and want to kill myself", True),
    ("我今晚准备跳楼", True),
    ("我今晚没有准备跳楼", False),
    ("我没有准备今晚跳楼", False),
    ("我今晚并未打算跳楼", False),
    ("我今晚不打算从楼上跳下去", False),
    ("我今晚没有准备跳楼但明天打算吞药", True),
    ("我今晚没有准备但现在想跳楼", True),
])
def test_review_risk_negation_unknown_age_never_needs_model(support, text, refers):
    sid, _, _, fake = support
    data = start(sid, background={"current_concern": text}).json()
    assert (data["status"] == "referred") == refers
    assert not data["report"]["suggestions"] and not fake.calls
    if refers:
        assert data["risk"]["requires_intervention"] and data["report"]["question"] is None


@pytest.mark.parametrize("text,evidence,effect,accepted", [
    ("我试了，但并没有更难受", "我试了，但并没有更难受", "worse", False),
    ("我试了，但并没有更难受", "更难受", "worse", False),
    ("我试了，并不是没有帮助", "我试了，并不是没有帮助", "ineffective", False),
    ("我试了，并不是没有帮助", "没有帮助", "ineffective", False),
    ("我试了，没有觉得轻松", "轻松", "helpful", False),
    ("我试了，更不难受了", "我试了，更不难受了", "worse", False),
    ("我试了，并没有变得更难受", "更难受", "worse", False),
    ("我试了，没有比以前更难受", "更难受", "worse", False),
    ("我试了，没有明显加重", "加重", "worse", False),
    ("我试了，没有帮助", "我试了，没有帮助", "ineffective", True),
    ("我试了，比以前更难受", "我试了，比以前更难受", "worse", True),
    ("我没有试过，但今天试了，有帮助", "我没有试过，但今天试了，有帮助", "helpful", True),
    ("我试了，先前没有帮助，现在有用了", "我试了，先前没有帮助，现在有用了", "helpful", True),
    ("我试了，先前没有帮助，现在有用了", "我试了，先前没有帮助，现在有用了", "ineffective", False),
    ("我试了，并没有更难受，反而舒服多了", "我试了，并没有更难受，反而舒服多了", "helpful", True),
])
def test_review_effect_feedback_checks_original_negation_and_correction(support, text, evidence, effect, accepted):
    sid, _, _, _ = support
    start(sid)
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    target = state.suggestions[0]
    if "试了" not in evidence:
        target.execution = "attempted"
    before = state.model_copy(deep=True)
    proposal = Feedback(suggestion_id=target.suggestion_id, execution="attempted", effect=effect, evidence=evidence)
    result = HealingAgent.apply_feedback(state, [proposal], text)
    assert bool(result) == accepted
    if accepted:
        assert target.effect == effect and target.active == (effect == "helpful")
    else:
        assert state == before


class ReviewFitClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.fit_batches = []
        self.fail_fit_batch = None

    async def generate(self, system, payload, schema, **kwargs):
        if schema is FitCheck:
            self.fit_batches.append([item["knowledge_id"] for item in payload["knowledge"]])
            if len(self.fit_batches) == self.fail_fit_batch:
                raise HealingUnavailable("synthetic refill failure")
        draft = await super().generate(system, payload, schema, **kwargs)
        if schema is AgentDraft and self.recommendations is None:
            draft.recommendation_ids = [item["knowledge_id"] for item in payload["knowledge"]][:1]
        return draft


@pytest.mark.parametrize("blocked_count", [3, 4, 8])
def test_review_report_refills_after_personal_filter_with_same_hard_limits(support, blocked_count):
    sid, _, _, _ = support
    items = [knowledge(f"method-{number}", title=f"考试方法{number}", executor="student", prerequisites=[])
             for number in range(8)]
    retriever = HealingRetriever(items + [
        knowledge("invalid-pending", status="pending"), knowledge("invalid-adult", executor="adult"),
        knowledge("invalid-age", age_min=14), knowledge("invalid-stage", school_stages=["high"]),
    ])
    background = HealingBackground(age=12, school_stage="middle", adult_support_available=False)
    ranked = retriever.retrieve("考试压力\n学习 考试 压力 焦虑", "study_stress", background, top_k=30)
    assert len(ranked) == 8
    blocked = ranked[:blocked_count]
    fake = ReviewFitClient()
    attempts = {hit.item.knowledge_id: hit.item.title + "我试过，没有帮助" for hit in blocked}
    fake.fit_overrides = {key: {"verdict": "blocked", "evidence": evidence} for key, evidence in attempts.items()}
    healing.healing_agent = HealingAgent(fake, retriever)
    save_demographic_assessment(sid, "我12岁，上初一，最近考试压力很大")
    data = start(sid, background={**background.model_dump(exclude={"age"}), "current_concern": "考试压力",
                                  "previous_attempts": list(attempts.values())}).json()
    state = healing.healing_store.slot(sid).state
    assert all(len(batch) <= 4 for batch in fake.fit_batches)
    assert len({key for batch in fake.fit_batches for key in batch}) == sum(map(len, fake.fit_batches))
    assert not any(key.startswith("invalid-") for batch in fake.fit_batches for key in batch)
    if blocked_count == 8:
        assert not data["report"]["suggestions"] and not fake.calls
    else:
        expected = [hit.item.knowledge_id for hit in ranked[blocked_count:blocked_count + 4]]
        assert [item["knowledge_id"] for item in fake.calls[0]["knowledge"]] == expected
        assert data["report"]["suggestions"] and state.suggestions[0].knowledge_id == expected[0]
    assert not state.feedback


def test_review_follow_up_refills_without_recommending_old_or_blocked_methods(support):
    sid, _, _, _ = support
    fake = ReviewFitClient()
    retriever = HealingRetriever([knowledge(f"method-{number}") for number in range(8)])
    healing.healing_agent = HealingAgent(fake, retriever)
    hid = start(sid).json()["healing_id"]
    state = healing.healing_store.slot(sid).state
    original = state.suggestions[0]
    remaining = retriever.retrieve("考试压力\n没有时间\n学习 考试 压力 焦虑", "study_stress",
                                   state.memory.background, {original.method_key}, top_k=30)
    blocked_ids = {original.knowledge_id, *(hit.item.knowledge_id for hit in remaining[:4])}
    fake.fit_overrides = {key: {"verdict": "blocked", "evidence": "没有时间"} for key in blocked_ids}
    assert chat(sid, hid, "没有时间").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert not state.suggestions[0].active and not state.feedback
    active = [item for item in state.suggestions if item.active]
    assert len(active) == 1 and active[0].knowledge_id == remaining[4].item.knowledge_id
    assert not {item.knowledge_id for item in active} & blocked_ids


def test_review_refill_failure_preserves_previous_report(support):
    sid, _, _, _ = support
    fake = ReviewFitClient()
    retriever = HealingRetriever([knowledge(f"method-{number}") for number in range(8)])
    healing.healing_agent = HealingAgent(fake, retriever)
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    background = before.memory.background
    first = retriever.retrieve("考试压力\n学习 考试 压力 焦虑", "study_stress", background)
    attempts = {hit.item.knowledge_id: hit.item.title + "试过没有帮助" for hit in first}
    fake.fit_overrides = {key: {"verdict": "blocked", "evidence": evidence} for key, evidence in attempts.items()}
    fake.fail_fit_batch = 2
    response = start(sid, regenerate=True, expected_healing_id=hid,
                     background={**background.model_dump(exclude={"age"}), "previous_attempts": list(attempts.values())})
    assert response.status_code == 503
    assert healing.healing_store.slot(sid).state == before


def test_review_pause_only_deactivates_methods_blocked_by_new_constraint(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    text = "第一个方法我不方便做，先暂停"
    fake.fit_overrides = {before.suggestions[0].knowledge_id: {"verdict": "blocked", "evidence": text}}
    data = chat(sid, hid, text).json()
    state = healing.healing_store.slot(sid).state
    assert data["status"] == "paused" and data["report"]["question"] is None
    assert [item.active for item in state.suggestions] == [False, True]
    assert not state.feedback and state.memory == before.memory
    assert state.context_updates[0].reference_suggestions == before.suggestions


def test_review_explicit_adult_absence_can_pause_without_model_and_retry_applies_once(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.fail = True
    mid = str(uuid4())
    text = "没有成人能陪我，先暂停"
    assert chat(sid, hid, text, mid).status_code == 200
    assert healing.healing_store.slot(sid).state.adult_support.available is False
    fake.fail = False
    fake.fit_overrides = {key: {"verdict": "blocked", "evidence": "没有成人能陪我"}
                          for key in ["name-concern", "other"]}
    assert chat(sid, hid, text, mid).status_code == 200
    assert chat(sid, hid, text, mid).status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.status == "paused" and not any(item.active for item in state.suggestions)
    assert state.turn_count == 1 and len(state.context_updates) == 1 and not state.feedback


def test_review_plain_pause_remains_available_when_model_fails(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.fail = True
    assert chat(sid, hid, "先暂停").json()["status"] == "paused"
    state = healing.healing_store.slot(sid).state
    assert state.suggestions == before.suggestions and state.feedback == before.feedback


@pytest.mark.parametrize("text,prepared", [
    ("我准备试试第二个方法", [1]),
    ("第二个方法我准备试试", [1]),
    ("第二个方法我准备试试了", [1]),
    ("第二个方法，我准备试试", [1]),
    ("我打算尝试第2条建议", [1]),
    ("我准备试试第一个方法", [0]),
    ("我准备试试说出考试困扰", [0]),
    ("另一种压力表达，我准备试试", [1]),
    ("两个方法我都准备试试", [0, 1]),
    ("第一个和第二个方法都准备试试", [0, 1]),
    ("第一个我不准备试试，第二个我准备试试", [1]),
    ("第一个我准备试试，第二个我不准备试试", [0]),
    ("第一个方法我准备试试，但第一个方法我不准备试试，先暂停", []),
    ("第一个方法我不准备试试，但第一个方法我准备试试", [0]),
    ("我准备试试第二个，但还是不准备试试了，先暂停", []),
    ("我准备试试", []),
    ("我准备试试第三个方法", []),
    ("我不准备试试第二个方法，先暂停", []),
    ("先暂停", []),
])
def test_explicit_preparation_binds_only_selected_methods_without_model(support, text, prepared):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.fail = True
    response = chat(sid, hid, text)
    assert response.status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.status == "paused" and response.json()["report"]["question"] is None
    assert [item.execution for item in state.suggestions] == [
        "prepared" if index in prepared else "unconfirmed" for index in range(2)]
    assert {item.suggestion_id for item in state.feedback} == {
        before.suggestions[index].suggestion_id for index in prepared}
    assert all(item.effect == "unknown" and item.evidence == text for item in state.feedback)
    assert len(state.memory_update_suggestions) == len(prepared)
    assert state.memory == before.memory


@pytest.mark.parametrize("selected,expected", [("第二个", ["unconfirmed", "prepared"]),
                                              ("第一个", ["unconfirmed", "unconfirmed"])])
def test_preparation_uses_original_order_before_same_turn_filter(support, selected, expected):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    text = "第一个方法不方便做，我准备试试" + selected + "方法"
    fake.fit_overrides = {"name-concern": {"verdict": "blocked", "evidence": "第一个方法不方便做"}}
    assert chat(sid, hid, text).status_code == 200
    state = healing.healing_store.slot(sid).state
    assert [item.active for item in state.suggestions] == [False, True]
    assert [item.execution for item in state.suggestions] == expected
    assert len(state.feedback) == expected.count("prepared")


def test_preparation_selection_retry_and_filter_failure_are_atomic(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    text = "第一个方法不方便做，我准备试试第二个方法"
    message_id = str(uuid4())
    fake.fail = True
    assert chat(sid, hid, text, message_id).status_code == 503
    assert healing.healing_store.slot(sid).state == before
    fake.fail = False
    fake.fit_overrides = {"name-concern": {"verdict": "blocked", "evidence": "第一个方法不方便做"}}
    first = chat(sid, hid, text, message_id)
    retry = chat(sid, hid, text, message_id)
    assert first.status_code == retry.status_code == 200 and first.json() == retry.json()
    state = healing.healing_store.slot(sid).state
    assert state.turn_count == 1 and len(state.feedback) == 1
    assert state.feedback[0].suggestion_id == before.suggestions[1].suggestion_id
    assert state.suggestions[1].execution == "prepared"


def test_preparation_keeps_second_reference_beside_first_method_attempt(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.feedback = [
        Feedback(suggestion_id=before.suggestions[0].suggestion_id, execution="attempted",
                 evidence="第一个方法我试过了"),
        Feedback(suggestion_id=before.suggestions[1].suggestion_id, execution="prepared",
                 evidence="第二个方法我准备试试"),
    ]
    assert chat(sid, hid, "第一个方法我试过了，第二个方法我准备试试").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert [item.execution for item in state.suggestions] == ["attempted", "prepared"]
    assert [item.execution for item in state.feedback] == ["attempted", "prepared"]
    assert all(item.effect == "unknown" for item in state.feedback)


def test_two_method_effect_feedback_and_retry_keep_separate_associations(support):
    sid, _, store, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    records = store.list_by_student(before.memory.student_ref)
    fake.recommendations = []
    fake.feedback = [
        Feedback(suggestion_id=before.suggestions[0].suggestion_id, execution="attempted",
                 effect="helpful", evidence="第一个方法我试了，有帮助"),
        Feedback(suggestion_id=before.suggestions[1].suggestion_id, execution="attempted",
                 effect="ineffective", evidence="第二个方法我试了，没有帮助"),
    ]
    text = "第一个方法我试了，有帮助；第二个方法我试了，没有帮助"
    message_id = str(uuid4())
    first = chat(sid, hid, text, message_id)
    calls = len(fake.calls)
    retry = chat(sid, hid, text, message_id)
    assert first.status_code == retry.status_code == 200 and first.json() == retry.json()
    state = healing.healing_store.slot(sid).state
    assert [(item.effect, item.active) for item in state.suggestions] == [("helpful", True), ("ineffective", False)]
    assert len(state.feedback) == len(state.memory_update_suggestions) == 2
    assert [item.suggestion_id for item in state.feedback] == [item.suggestion_id for item in before.suggestions]
    assert state.turn_count == 1 and len(fake.calls) == calls
    assert state.memory == before.memory and store.list_by_student(before.memory.student_ref) == records


def save_demographic_assessment(sid, text):
    response = client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": text}],
    }})
    assert response.status_code == 200, response.json()
    return response.json()["result"]


@pytest.mark.parametrize("background", [None, {"current_concern": "考试压力"},
                                        {"school_stage": "high", "current_concern": "考试压力"}])
def test_start_reads_saved_age_and_grade_without_repeating_demographics(support, background):
    sid, _, store, fake = support
    result = save_demographic_assessment(sid, "我今年12岁，上初一，最近考试压力很大")
    records = store.list_by_student(result["student_ref"])
    request = {"session_id": sid, "request_id": str(uuid4())}
    if background is not None:
        request["background"] = background
    response = client.post("/api/healing/start", json=request)
    assert response.status_code == 200, response.json()
    state = healing.healing_store.slot(sid).state
    assert state.memory.background.age == 12 and state.memory.background.school_stage == "middle"
    assert state.memory.assessment.grade == "初一" and state.memory.assessment.age == 12
    assert state.memory.provenance["background.age"] == "persistent_evaluation_record.age"
    assert state.memory.provenance["background.school_stage"] == "persistent_evaluation_record.grade_to_school_stage"
    assert response.json()["assessment_result_id"] == result["result_id"]
    assert not response.json()["report"]["suggestions"] and state.adult_support.waiting
    assert fake.calls[0]["communication"]["style"] == "conversational"
    assert store.list_by_student(result["student_ref"]) == records


def test_new_session_reads_demographics_from_reopened_persistent_memory(support, monkeypatch):
    sid, _, store, _ = support
    result = save_demographic_assessment(sid, "我12岁，上初一，最近考试压力很大")
    fresh = client.post("/api/session", json={"student_ref": result["student_ref"]}).json()["session_id"]
    reopened = MemoryStore(store._db_path)
    monkeypatch.setattr(healing, "memory_store", reopened)
    response = client.post("/api/healing/start", json={"session_id": fresh, "request_id": str(uuid4()),
                                                      "background": {"current_concern": "考试压力"}})
    assert response.status_code == 200 and not response.json()["report"]["suggestions"]
    state = healing.healing_store.slot(fresh).state
    assert state.adult_support.waiting
    assert state.memory.background.age == 12 and state.memory.background.school_stage == "middle"
    assert state.memory.current_session_messages == []
    assert state.memory.assessment.result_id == result["result_id"]


def test_grade_without_age_does_not_infer_age_or_reuse_older_age(support):
    sid, _, _, _ = support
    save_demographic_assessment(sid, "我12岁，上初一，最近考试压力很大")
    latest = save_demographic_assessment(sid, "我上初二，最近考试压力很大")
    response = client.post("/api/healing/start", json={"session_id": sid, "request_id": str(uuid4()),
        "background": {"adult_support_available": False}})
    assert response.status_code == 200 and response.json()["report"]["suggestions"] == []
    state = healing.healing_store.slot(sid).state
    assert state.memory.background.age is None and state.memory.background.school_stage == "middle"
    assert state.memory.assessment.result_id == latest["result_id"]


@pytest.mark.parametrize("text", ["我19岁，上高三，最近考试压力很大", "我8岁，上高二，最近考试压力很大"])
def test_invalid_saved_demographics_return_validation_error_not_missing_assessment(support, text):
    sid, _, _, fake = support
    save_demographic_assessment(sid, text)
    response = client.post("/api/healing/start", json={"session_id": sid, "request_id": str(uuid4())})
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert healing.healing_store.slot(sid).state is None and not fake.calls


def test_regeneration_reads_latest_demographics_but_failed_generation_preserves_binding(support):
    sid, _, _, _ = support
    original = save_demographic_assessment(sid, "我12岁，上初一，最近考试压力很大")
    first = client.post("/api/healing/start", json={"session_id": sid, "request_id": str(uuid4())}).json()
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    save_demographic_assessment(sid, "我19岁，上高三，最近考试压力很大")
    request = {"session_id": sid, "request_id": str(uuid4()), "regenerate": True,
               "expected_healing_id": first["healing_id"], "background": {"current_concern": "考试压力"}}
    failed = client.post("/api/healing/start", json=request)
    assert failed.status_code == 422 and healing.healing_store.slot(sid).state == before
    latest = save_demographic_assessment(sid, "我16岁，上高一，最近考试压力很大")
    restored = client.post("/api/healing/start", json={"session_id": sid, "request_id": str(uuid4())})
    assert restored.json()["assessment_result_id"] == original["result_id"]
    assert healing.healing_store.slot(sid).state.memory.background.age == 12
    regenerated = client.post("/api/healing/start", json=request)
    assert regenerated.status_code == 200 and regenerated.json()["assessment_result_id"] == latest["result_id"]
    after = healing.healing_store.slot(sid).state
    assert after.memory.background.age == 16 and after.memory.background.school_stage == "high"
    assert after.healing_id != before.healing_id and before.memory.background.age == 12


@pytest.mark.parametrize("age", [12, 16, None])
def test_caller_cannot_supply_or_override_recorded_age(support, age):
    sid, _, _, fake = support
    save_demographic_assessment(sid, "我12岁，上初一，最近考试压力很大")
    response = start(sid, background={"age": age, "current_concern": "考试压力"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert healing.healing_store.slot(sid).state is None and not fake.calls


@pytest.mark.parametrize("grade,expected", [
    ("小学一年级", "primary"), ("小学6年级", "primary"), ("五年级", "primary"),
    ("初一", "middle"), ("初3", "middle"), ("初中二年级", "middle"), ("7年级", "middle"),
    ("九年级", "middle"), ("高一", "high"), ("高3", "high"), ("高中三年级", "high"),
    (" 初 一 ", "middle"), (None, None), ("大一", None), ("其他", None), ("初四", None),
])
def test_stored_grade_mapping_preserves_unknown_labels(grade, expected):
    from backend.core.healing_adapter import grade_to_school_stage
    assert grade_to_school_stage(grade) == expected


def test_grade_only_cannot_satisfy_numerical_source_age_limits(support):
    sid, _, _, fake = support
    latest = save_demographic_assessment(sid, "我上初一，最近考试压力很大")
    healing.healing_agent.retriever = HealingRetriever([knowledge(age_min=11, age_max=13)])
    response = start(sid, background={"current_concern": "考试压力"})
    assert response.status_code == 200 and response.json()["report"]["suggestions"] == []
    state = healing.healing_store.slot(sid).state
    assert state.memory.background.age is None and state.memory.background.school_stage == "middle"
    assert state.memory.assessment.result_id == latest["result_id"] and not fake.calls


def test_unknown_recorded_grade_preserves_raw_value_without_guessing_stage(support):
    sid, _, _, fake = support
    save_demographic_assessment(sid, "我上大一，最近考试压力很大")
    response = start(sid, background={"current_concern": "考试压力"})
    assert response.status_code == 200 and response.json()["report"]["suggestions"] == []
    state = healing.healing_store.slot(sid).state
    assert state.memory.assessment.grade == "大一" and state.memory.background.school_stage is None
    assert state.memory.provenance["background.age"] == "unknown" and not fake.calls


@pytest.mark.parametrize("text,expected_status,expected_scene", [
    ("我不想聊睡眠，只想聊考试压力", "active", "study_stress"),
    ("我不想继续聊睡眠，还想聊考试压力", "active", "study_stress"),
    ("我不想聊同学关系", "active", "study_stress"),
    ("我不是不想聊", "active", "study_stress"),
    ("别结束吧，我只想聊考试", "active", "study_stress"),
    ("不想继续聊考试，先聊睡眠", "active", "sleep"),
    ("不想聊考试，换成睡眠，结束吧", "ended", "study_stress"),
    ("我不想聊睡眠，结束吧", "ended", "study_stress"),
    ("不想继续了", "ended", "study_stress"),
    ("不想继续聊了", "ended", "study_stress"),
    ("不想聊了", "ended", "study_stress"),
    ("不聊了", "ended", "study_stress"),
    ("我不想继续说话了", "ended", "study_stress"),
    ("先这样聊考试", "active", "study_stress"),
    ("不想聊昨天的事，还是聊考试", "active", "study_stress"),
])
def test_topic_refusal_is_separate_from_ending_companionship(support, text, expected_status, expected_scene):
    sid, _, _, fake = support
    initial = start(sid).json()
    calls = len(fake.calls)
    if expected_status == "ended":
        fake.fail = True  # An explicit exit remains available without a model.
    response = chat(sid, initial["healing_id"], text)
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == expected_status
    current = healing.healing_store.slot(sid).state
    assert current.scene == expected_scene and not current.feedback
    if expected_status == "ended":
        assert len(fake.calls) == calls and response.json()["report"]["question"] is None
    else:
        assert len(fake.calls) > calls


def simplification_state():
    from types import SimpleNamespace
    from backend.healing.agent import make_suggestion
    from backend.models.healing import KnowledgeHit, KnowledgeWording

    items = [knowledge(key, title=title, wordings=[KnowledgeWording(
        wording_id=key + "-simple", style="simple", title=title + "简短版",
        goal="说出担心的事", steps=["和成人一起，说出你的考试担心。"], semantic_checked=True,
    )]) for key, title in [("first", "记录考试担心"), ("second", "说出考试感受")]]
    hits = [KnowledgeHit(item=item, score=1, age_match="synthetic", scene_match="study_stress")
            for item in items]
    return SimpleNamespace(suggestions=[make_suggestion(hit, 0) for hit in hits], turn_count=1,
        audit=[{"knowledge": [hit.model_dump(mode="json") for hit in hits]}], memory_update_suggestions=[])


@pytest.mark.parametrize("text,selected,expected", [
    ("第一个方法太复杂，第二个方法我看得懂，不用改", 0, True),
    ("第一个方法太复杂，第二个方法我看得懂，不用改", 1, False),
    ("第二个方法太复杂，第一个方法不用改", 0, False),
    ("第二个方法太复杂，第一个方法不用改", 1, True),
    ("第一个方法并不复杂，先别改", 0, False),
    ("第一个方法不是看不懂，只是不喜欢", 0, False),
    ("第一个方法太复杂，但是现在看得懂，不用改", 0, False),
    ("第一个方法看得懂，但请简单一点", 0, True),
    ("第一个方法太复杂，第二个方法也复杂", 0, True),
    ("第一个方法太复杂，第二个方法也复杂", 1, True),
    ("第一个方法不要简化，第二个方法能简单一点吗", 0, False),
    ("第一个方法不要简化，第二个方法能简单一点吗", 1, True),
    ("第1条建议看不懂", 0, True),
    ("第2种方法听不懂", 1, True),
    ("两个方法都太复杂", 0, True),
    ("两个方法都太复杂", 1, True),
    ("第一个方法并不是不复杂", 0, True),
    ("第一个方法并不难懂，第二个方法太复杂", 0, False),
    ("第一个方法并不难懂，第二个方法太复杂", 1, True),
    ("记录考试担心看不懂，说出考试感受不用改", 0, True),
    ("记录考试担心看不懂，说出考试感受不用改", 1, False),
    ("第一个方法不需要更简单一点", 0, False),
    ("第一个方法已经很简单", 0, False),
    ("第一个方法，能用简单的话说吗", 0, True),
    ("第一个方法太复杂，但我不想改", 0, False),
    ("第一个方法别用简单的话说", 0, False),
    ("第一个方法不要改成简单一点", 0, False),
    ("第一个方法太复杂。先别改", 0, False),
])
def test_simplification_checks_local_request_and_negation(text, selected, expected):
    state = simplification_state()
    before = [item.model_copy(deep=True) for item in state.suggestions]
    changed = HealingAgent.simplify(state, before[selected].suggestion_id, text)
    assert (changed is not None) == expected
    assert state.suggestions[1 - selected] == before[1 - selected]
    if expected:
        target = state.suggestions[selected]
        assert target.suggestion_id == before[selected].suggestion_id
        assert target.prerequisites == before[selected].prerequisites
        assert target.execution == before[selected].execution and target.effect == before[selected].effect
        assert len(target.revisions) == 1 and len(state.memory_update_suggestions) == 1
    else:
        assert state.suggestions == before and not state.memory_update_suggestions


@pytest.mark.parametrize("text,expected", [("第二个方法看不懂", False), ("看不懂，能简单一点吗", True)])
def test_single_method_does_not_absorb_an_invalid_ordinal_simplification(text, expected):
    state = simplification_state()
    state.suggestions = state.suggestions[:1]
    assert (HealingAgent.simplify(state, state.suggestions[0].suggestion_id, text) is not None) == expected


@pytest.mark.parametrize("selected,expected", [(0, False), (1, True)])
def test_simplification_preserves_ordinals_before_same_turn_filter(selected, expected):
    state = simplification_state()
    references = [item.model_copy(deep=True) for item in state.suggestions]
    state.suggestions[0].active = False
    changed = HealingAgent.simplify(state, state.suggestions[selected].suggestion_id,
        "第一个方法没有成人能陪我，第二个方法看不懂", references)
    assert (changed is not None) == expected


def test_api_rejects_wrong_simplification_target_and_retry_does_not_revise_twice(support):
    from backend.models.healing import KnowledgeWording
    sid, _, _, fake = support
    items = [knowledge(key, title=title, wordings=[KnowledgeWording(
        wording_id=key + "-simple", style="simple", title=title + "简短版", goal="梳理担心",
        steps=["和成人一起，说出担心的事。"], semantic_checked=True,
    )]) for key, title in [("name-concern", "记录担心"), ("other", "表达感受")]]
    healing.healing_agent.retriever = HealingRetriever(items)
    fake.recommendations = [item.knowledge_id for item in items]
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.recommendations = []
    fake.simplify_id = before.suggestions[1].suggestion_id
    assert chat(sid, hid, "第一个方法太复杂，第二个方法我看得懂，不用改").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.suggestions == before.suggestions and not state.memory_update_suggestions
    fake.simplify_id = before.suggestions[0].suggestion_id
    mid = str(uuid4())
    request = "第一个方法看不懂，能简单一点吗"
    fake.fail = True
    snapshot = state.model_copy(deep=True)
    assert chat(sid, hid, request, mid).status_code == 503
    assert healing.healing_store.slot(sid).state == snapshot
    fake.fail = False
    assert chat(sid, hid, request, mid).status_code == 200
    after = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert len(after.suggestions[0].revisions) == 1 and not after.suggestions[1].revisions
    assert chat(sid, hid, request, mid).status_code == 200
    assert healing.healing_store.slot(sid).state == after


def test_api_simplification_uses_original_second_method_after_first_is_filtered(support):
    from backend.models.healing import KnowledgeWording
    sid, _, _, fake = support
    items = [knowledge(key, wordings=[KnowledgeWording(
        wording_id=key + "-simple", style="simple", title="说说担心", goal="梳理担心",
        steps=["和成人一起，说出担心的事。"], semantic_checked=True,
    )]) for key in ["name-concern", "other"]]
    healing.healing_agent.retriever = HealingRetriever(items)
    fake.recommendations = [item.knowledge_id for item in items]
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.recommendations = []
    fake.simplify_id = before.suggestions[1].suggestion_id
    fake.fit_overrides = {before.suggestions[0].knowledge_id: {
        "verdict": "blocked", "evidence": "第一个方法没有成人能陪我"}}
    response = chat(sid, hid, "第一个方法没有成人能陪我，第二个方法看不懂")
    assert response.status_code == 200, response.json()
    state = healing.healing_store.slot(sid).state
    assert not state.suggestions[0].active and not state.suggestions[0].revisions
    assert state.suggestions[1].active and len(state.suggestions[1].revisions) == 1
    assert state.suggestions[1].suggestion_id == before.suggestions[1].suggestion_id
    assert state.suggestions[1].prerequisites == before.suggestions[1].prerequisites
    assert not state.feedback


@pytest.mark.parametrize("model_execution", [None, "prepared", "not_attempted"])
def test_api_resume_preserves_prepared_and_records_absence_once(support, model_execution):
    sid, _, store, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    fake.recommendations = []
    target = healing.healing_store.slot(sid).state.suggestions[1].suggestion_id
    session_before = session_manager.get_session(sid).model_copy(deep=True)
    records_before = store.list_by_student(session_before.student_ref)
    assert chat(sid, hid, "第二个方法我准备试试").json()["status"] == "paused"
    assert chat(sid, hid, "先暂停").json()["status"] == "paused"
    fake.feedback = [] if model_execution is None else [Feedback(
        suggestion_id=target, execution=model_execution, evidence="第二个方法还没试")]
    text, mid = "我们继续聊考试压力，第二个方法还没试", str(uuid4())
    response = chat(sid, hid, text, mid)
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["status"] == "active" and "你说的是刚才哪一个方法" not in data["messages"][-1]["content"]
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert [item.execution for item in state.suggestions] == ["unconfirmed", "prepared"]
    assert [(item.suggestion_id, item.execution) for item in state.feedback] == [
        (target, "prepared"), (target, "not_attempted")]
    assert state.feedback[-1].evidence in text and state.feedback[-1].turn == state.turn_count
    assert len(state.memory_update_suggestions) == 2
    assert state.memory_update_suggestions[-1]["persisted"] is False
    calls = len(fake.calls)
    assert chat(sid, hid, text, mid).json() == data and len(fake.calls) == calls
    assert healing.healing_store.slot(sid).state == state
    assert session_manager.get_session(sid) == session_before
    assert store.list_by_student(session_before.student_ref) == records_before


def test_api_prepared_absence_failure_rolls_back_before_retry(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    assert chat(sid, hid, "我准备试试").status_code == 200
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    text, mid = "还没试", str(uuid4())
    fake.fail = True
    assert chat(sid, hid, text, mid).status_code == 503
    assert healing.healing_store.slot(sid).state == before
    fake.fail = False
    assert chat(sid, hid, text, mid).status_code == 200
    after = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert after.suggestions[0].execution == "prepared"
    assert len(after.feedback) == len(before.feedback) + 1
    assert after.feedback[-1].execution == "not_attempted"
    assert chat(sid, hid, text, mid).status_code == 200
    assert healing.healing_store.slot(sid).state == after


def test_api_pause_with_prepared_absence_remains_model_free(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    assert chat(sid, hid, "我准备试试").status_code == 200
    calls = len(fake.calls)
    fake.fail = True
    response = chat(sid, hid, "还没试，先暂停")
    assert response.status_code == 200 and response.json()["status"] == "paused"
    state = healing.healing_store.slot(sid).state
    assert state.suggestions[0].execution == "prepared"
    assert [item.execution for item in state.feedback] == ["prepared", "not_attempted"]
    assert len(fake.calls) == calls


@pytest.mark.parametrize("execution,effect,text", [
    ("attempted", "helpful", "我试了，有帮助"),
    ("declined", "unknown", "我不想用这个方法了"),
])
def test_api_prepared_absence_does_not_block_subsequent_progress(support, execution, effect, text):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    assert chat(sid, hid, "我准备试试").status_code == 200
    assert chat(sid, hid, "还没试").status_code == 200
    target = healing.healing_store.slot(sid).state.suggestions[0].suggestion_id
    fake.feedback = [Feedback(suggestion_id=target, execution=execution, effect=effect, evidence=text)]
    response = chat(sid, hid, text)
    assert response.status_code == 200, response.json()
    state = healing.healing_store.slot(sid).state
    assert state.suggestions[0].execution == execution and state.suggestions[0].effect == effect
    assert state.suggestions[0].active is (execution != "declined")
    assert [item.execution for item in state.feedback] == ["prepared", "not_attempted", execution]


@pytest.mark.parametrize("reverse,attempt", [(False, "试过"), (True, "试过"), (False, "做过"), (False, "练过")])
def test_mixed_attempt_and_preparation_with_absence_keeps_both_local_facts(support, reverse, attempt):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    first = f"第一个方法我{attempt}了，有帮助"
    second = "第二个方法我准备试试，但还没有试过"
    text = "；".join([second, first] if reverse else [first, second])
    fake.recommendations = []
    fake.feedback = [
        Feedback(suggestion_id=before.suggestions[0].suggestion_id, execution="attempted", effect="helpful", evidence=first),
        Feedback(suggestion_id=before.suggestions[1].suggestion_id, execution="prepared", evidence="第二个方法我准备试试"),
    ]
    mid = str(uuid4())
    response = chat(sid, hid, text, mid)
    assert response.status_code == 200, response.json()
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert [(item.execution, item.effect) for item in state.suggestions] == [("attempted", "helpful"), ("prepared", "unknown")]
    assert [item.suggestion_id for item in state.feedback] == [item.suggestion_id for item in before.suggestions]
    calls = len(fake.calls)
    assert chat(sid, hid, text, mid).json() == response.json()
    assert len(fake.calls) == calls and healing.healing_store.slot(sid).state == state


def test_same_method_attempt_retraction_still_allows_model_free_preparation(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    calls = len(fake.calls)
    fake.fail = True
    response = chat(sid, hid, "第一个方法我试过了，但刚才说错了，其实没有试过；第二个方法我准备试试")
    assert response.status_code == 200 and response.json()["status"] == "paused"
    state = healing.healing_store.slot(sid).state
    assert [item.execution for item in state.suggestions] == ["unconfirmed", "prepared"]
    assert len(fake.calls) == calls


def test_api_negated_decline_does_not_deactivate_and_retry_remains_atomic(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    target = healing.healing_store.slot(sid).state.suggestions[0].suggestion_id
    fake.recommendations = []
    fake.feedback = [Feedback(suggestion_id=target, execution="declined", evidence="不想用")]
    text, mid = "第一个方法我并不是不想用，只是还没时间试", str(uuid4())
    fake.fail = True
    previous = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert chat(sid, hid, text, mid).status_code == 503
    assert healing.healing_store.slot(sid).state == previous
    fake.fail = False
    response = chat(sid, hid, text, mid)
    assert response.status_code == 200, response.json()
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert state.suggestions[0].active and state.suggestions[0].execution == "unconfirmed"
    assert not state.feedback
    calls = len(fake.calls)
    assert chat(sid, hid, text, mid).json() == response.json()
    assert len(fake.calls) == calls and healing.healing_store.slot(sid).state == state
