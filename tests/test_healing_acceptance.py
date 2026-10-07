"""Current API and expanded-library acceptance with fixed, independent cases."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api import assessment, healing
from backend.core.memory_store import MemoryStore
from backend.core.session_manager import session_manager
from backend.healing.agent import AgentDraft, HealingAgent, NarrativeCheck
from backend.healing.client import HealingUnavailable
from backend.healing.knowledge import load_knowledge
from backend.healing.retriever import HealingRetriever
from backend.healing.store import HealingStore
from backend.healing.suitability import FitCheck, FitDecision
from backend.main import app

client = TestClient(app)
SCENES = {"study_stress": "想聊考试压力", "low_mood": "想聊心情低落",
          "relationships": "想聊人际关系，和同学意见不一致", "sleep": "想聊睡眠，最近睡得晚"}
DEMOGRAPHICS = [(6, "一年级", "primary"), (10, "四年级", "primary"), (11, "六年级", "primary"),
                (11, "初一", "middle"), (12, "初二", "middle"), (13, "初三", "middle"),
                (14, "高一", "high"), (18, "高三", "high")]
RETRIEVAL_CASES = json.loads((Path(__file__).parent / "fixtures/healing_expanded_retrieval_cases.json").read_text(encoding="utf-8"))


class ControlledClient:
    """Only remote decisions are simulated; API, records and knowledge are real."""
    def __init__(self):
        self.calls = []
        self.fail = False
        self.feedback = []
        self.simplify_id = None

    async def generate(self, system, payload, schema, **kwargs):
        self.calls.append(schema.__name__)
        if self.fail:
            raise HealingUnavailable("synthetic unavailable")
        if schema is NarrativeCheck:
            return NarrativeCheck(valid=True)
        if schema is FitCheck:
            return FitCheck(decisions=[FitDecision(knowledge_id=item["knowledge_id"], verdict="suitable") for item in payload["knowledge"]])
        return AgentDraft(understanding="我听到了你的困扰。", focus="先聊你关心的事情。", question="你想先说说哪一部分？",
            recommendation_ids=[item["knowledge_id"] for item in payload.get("knowledge", [])][:2] if payload["phase"] == "report" else [],
            feedback=self.feedback, simplify_suggestion_id=self.simplify_id)


@pytest.fixture
def acceptance(tmp_path, monkeypatch, evaluation_stub):
    store = MemoryStore(tmp_path / "acceptance.sqlite3")
    model = ControlledClient()
    monkeypatch.setattr(assessment, "memory_store", store)
    monkeypatch.setattr(healing, "memory_store", store)
    monkeypatch.setattr(healing, "healing_store", HealingStore())
    monkeypatch.setattr(healing, "healing_agent", HealingAgent(model, HealingRetriever(load_knowledge())))
    sid = client.post("/api/session").json()["session_id"]
    return sid, store, model


def evaluate(sid, text):
    response = client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {"dialogue_history": [{"role": "user", "content": text}]}})
    assert response.status_code == 200, response.json()
    return response.json()["result"]


def enter(sid, background):
    return client.post("/api/healing/start", json={"session_id": sid, "request_id": str(uuid4()), "background": background})


def reply(sid, hid, text, message_id=None):
    return client.post("/api/healing/chat", json={"session_id": sid, "healing_id": hid, "message_id": message_id or str(uuid4()), "text": text})


@pytest.mark.parametrize("scene", SCENES)
@pytest.mark.parametrize("age,grade,stage", DEMOGRAPHICS)
def test_minimal_background_full_library_age_scene_matrix(acceptance, age, grade, stage, scene):
    sid, store, model = acceptance
    result = evaluate(sid, f"我{age}岁，读{grade}。{SCENES[scene]}。平时正常上学吃饭。")
    saved = store.list_by_student(result["student_ref"])
    screening = session_manager.get_session(sid)
    response = enter(sid, {"current_concern": SCENES[scene], "adult_support_available": False})
    assert response.status_code == 200, response.json()
    state = healing.healing_store.slot(sid).state
    assert state.scene == scene and state.memory.background.age == age and state.memory.background.school_stage == stage
    assert state.memory.assessment.result_id == result["result_id"]
    assert len(state.suggestions) <= 2
    if not state.suggestions:
        # Explanation-only knowledge can support a response when executable
        # methods have no lexical match. It must not turn into invented steps.
        assert state.status == "active" and state.report.question and not state.report.suggestion_ids
        assert any(event.get("explanations") and not event.get("knowledge") for event in state.audit)
    items = {item.knowledge_id: item for item in load_knowledge()}
    for suggestion in state.suggestions:
        item = items[suggestion.knowledge_id]
        assert item.status == "usable" and item.executor == "student" and scene in item.scenes
        assert item.audience == "children_adolescents" or item.audience == ("children" if age <= 12 else "adolescents")
        assert suggestion.steps in [item.steps, *[value.steps for value in item.wordings if value.semantic_checked and not value.validation_issues]]
        assert set(item.prerequisites) <= set(suggestion.prerequisites)
    assert state.memory.background.preferences == state.memory.background.constraints == state.memory.background.previous_attempts == []
    assert state.memory.background.important_events == []
    assert "knowledge_id" not in response.text and "source_url" not in response.text
    assert session_manager.get_session(sid) == screening and store.list_by_student(result["student_ref"]) == saved


@pytest.mark.parametrize("text,age,stage,methods", [
    ("最近考试压力大", None, None, False),
    ("我读初一，最近考试压力大", None, "middle", False),
    ("我读高一，最近考试压力大", None, "high", False),
    ("我读四年级，最近考试压力大", None, "primary", True),
    ("我10岁，最近考试压力大", 10, None, True),
    ("我13岁，最近考试压力大", 13, None, True),
    ("我18岁，最近考试压力大", 18, None, True),
])
def test_absent_demographics_never_borrow_older_age(acceptance, text, age, stage, methods):
    sid, store, model = acceptance
    evaluate(sid, "我16岁，读高一，最近考试压力大")
    latest = evaluate(sid, text)
    response = enter(sid, {"current_concern": "想聊考试压力", "adult_support_available": False})
    assert response.status_code == 200, response.json()
    state = healing.healing_store.slot(sid).state
    assert state.memory.assessment.result_id == latest["result_id"]
    assert state.memory.background.age == age and state.memory.background.school_stage == stage
    assert bool(state.suggestions) == methods
    if not methods:
        assert not model.calls


@pytest.mark.parametrize("background", [
    {"current_concern": "考试压力", "preferences": [""]},
    {"current_concern": "考试压力", "constraints": [" " ]},
    {"current_concern": "考试压力", "important_events": ["a" * 501]},
    {"current_concern": "考试压力", "previous_attempts": ["未尝试"] * 11},
])
def test_invalid_optional_background_does_not_replace_existing_report(acceptance, background):
    sid, store, model = acceptance
    evaluate(sid, "我13岁，读初二，最近考试压力大")
    initial = enter(sid, {"current_concern": "考试压力", "adult_support_available": False}).json()
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    calls = len(model.calls)
    response = client.post("/api/healing/start", json={"session_id": sid, "request_id": str(uuid4()),
        "regenerate": True, "expected_healing_id": initial["healing_id"], "background": background})
    assert response.status_code == 422 and healing.healing_store.slot(sid).state == before
    assert len(model.calls) == calls


def test_unknown_background_pause_end_and_invalid_reply_without_model(acceptance):
    sid, store, model = acceptance
    evaluate(sid, "最近有一点考试压力")
    initial = enter(sid, {}).json()
    model.fail = True
    assert reply(sid, initial["healing_id"], "先暂停").json()["status"] == "paused"
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert reply(sid, initial["healing_id"], " " * 10).status_code == 422
    assert healing.healing_store.slot(sid).state == before
    message = str(uuid4())
    ended = reply(sid, initial["healing_id"], "今天先到这里", message)
    assert ended.status_code == 200 and ended.json()["status"] == "ended"
    assert reply(sid, initial["healing_id"], "今天先到这里", message).json() == ended.json()
    assert reply(sid, initial["healing_id"], "继续说").status_code == 409 and not model.calls


@pytest.mark.parametrize("case", RETRIEVAL_CASES, ids=lambda row: row["id"])
def test_expanded_library_fixed_bm25_cases(case):
    from backend.models.healing import HealingBackground
    items = load_knowledge()
    expected = set(case["expected_methods"])
    assert len(items) == 127 and expected <= {item.method_key for item in items if item.status == "usable"}
    hits = HealingRetriever(items).retrieve(case["query"], case["scene"], HealingBackground(**case["background"]),
        set(case.get("excluded_methods", [])), top_k=2)
    keys = [hit.item.method_key for hit in hits]
    assert expected.intersection(keys) if expected else not keys
    assert len(keys) == len(set(keys)) and not set(keys).intersection(case.get("excluded_methods", []))
    assert all(hit.item.status == "usable" and hit.item.semantic_checked and not hit.item.validation_issues for hit in hits)
    if case["background"].get("adult_support_available") is False:
        assert all(hit.item.executor == "student" for hit in hits)
