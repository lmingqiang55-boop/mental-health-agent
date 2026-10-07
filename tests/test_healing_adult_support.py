"""Adult conditions are confirmed only when a proposed method requires them."""

from uuid import uuid4

import pytest

from backend.api import healing
from backend.core.session_manager import session_manager
from backend.healing.adult_support import ADULT_QUESTION, support_signal
from backend.healing.retriever import HealingRetriever
from test_healing import chat, client, knowledge, support


def enter(sid, available="omitted"):
    background = {"school_stage": "middle", "current_concern": "考试压力"}
    if available != "omitted":
        background["adult_support_available"] = available
    return client.post("/api/healing/start", json={"session_id": sid,
        "request_id": str(uuid4()), "background": background})


@pytest.mark.parametrize("text,answering,recognized,value", [
    ("有", True, True, True), ("可以", True, True, True), ("没有", True, True, False),
    ("不行", True, True, False), ("不知道", True, True, None), ("不想说", True, True, None),
    ("有", False, False, None), ("没有", False, False, None),
    ("我有父母", False, False, None), ("我有父母", True, True, None),
    ("妈妈能陪我", False, True, True), ("老师愿意指导我", False, True, True),
    ("妈妈不能陪我", False, True, False), ("没有成人能陪我", False, True, False),
    ("妈妈愿意陪我，但她没有时间", False, True, False),
    ("妈妈不能陪我，但是老师能陪我", False, True, True),
    ("老师可以陪我，但妈妈不愿意陪我", False, True, True),
    ("我不信任妈妈，妈妈可以陪我", False, True, False),
    ("妈妈可能能陪我", False, True, None), ("昨天妈妈能陪我", False, False, None),
    ("妈妈能陪我吗", False, True, None), ("如果妈妈能陪我就好了", False, True, None),
    ("妈妈能陪我，但我不信任她", False, True, False),
    ("妈妈能陪我，但我没有时间", False, True, True),
    ("有，妈妈不能陪我", True, True, False),
    ("有，我试了第一个方法", True, True, True),
    ("第一个方法没有成人能陪我", False, False, None),
    ("爷爷愿意陪我", False, True, True), ("班主任能帮忙", False, True, True),
    ("我不愿意聊妈妈", False, False, None),
    ("没有爷爷能陪我", False, True, False),
    ("没有一个愿意陪我的大人", False, True, False),
    ("我没有朋友，老师能陪我", False, True, True),
    ("我没有朋友，但老师能陪我", False, True, True),
])
def test_adult_support_requires_explicit_current_evidence(text, answering, recognized, value):
    assert support_signal(text, answering=answering) == (recognized, value)


def test_unknown_adult_method_waits_for_one_question_and_preserves_screening(support):
    sid, result, store, fake = support
    before = session_manager.get_session(sid)
    records = store.list_by_student(before.student_ref)
    response = enter(sid)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["report"]["question"] == ADULT_QUESTION
    assert data["report"]["suggestions"] == []
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.waiting and state.adult_support.available is None
    assert state.adult_support.deferred_knowledge_ids == ["name-concern"]
    assert not state.suggestions and not state.feedback
    assert data["assessment_result_id"] == result["result_id"]
    calls = len(fake.calls)
    assert client.get(f"/api/healing/{sid}").json() == data
    assert enter(sid).json() == data and len(fake.calls) == calls
    assert session_manager.get_session(sid) == before
    assert store.list_by_student(before.student_ref) == records


@pytest.mark.parametrize("answer", ["有", "可以", "有的", "妈妈能陪我", "妈妈不能陪我，但是老师能陪我"])
def test_answer_to_adult_question_enables_bound_method_without_attempt_feedback(support, answer):
    sid, _, _, _ = support
    first = enter(sid).json()
    response = chat(sid, first["healing_id"], answer)
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.available is True and not state.adult_support.waiting
    assert state.adult_support.source == "dialogue" and state.adult_support.evidence == answer
    assert state.memory.background.adult_support_available is None
    assert len(state.suggestions) == 1 and state.suggestions[0].active
    assert state.suggestions[0].knowledge_id == "name-concern"
    assert state.suggestions[0].prerequisites == ["成人指导"]
    assert not state.feedback and state.suggestions[0].execution == "unconfirmed"
    assert ADULT_QUESTION not in response.json()["messages"][-1]["content"]
    assert response.json()["report"]["question"] != ADULT_QUESTION


@pytest.mark.parametrize("answer,value", [("没有", False), ("不行", False), ("不知道", None),
    ("不想说", None), ("我有父母", None), ("我还是有点紧张", None)])
def test_negative_or_unknown_answer_uses_autonomous_methods_without_reasking(support, answer, value):
    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([knowledge(), knowledge("solo", executor="student",
        title="表达考试压力", steps=["写下考试让你担心的事。"], prerequisites=[])])
    fake.recommendations = ["name-concern"]
    first = enter(sid).json()
    assert first["report"]["question"] == ADULT_QUESTION
    fake.recommendations = None
    response = chat(sid, first["healing_id"], answer)
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.available is value and state.adult_support.asked
    assert fake.calls[-1]["memory"]["background"]["adult_support_available"] is value
    assert not state.adult_support.waiting
    assert [item.knowledge_id for item in state.suggestions if item.active] == ["solo"]
    assert not state.feedback
    assert ADULT_QUESTION not in response.json()["messages"][-1]["content"]
    assert ADULT_QUESTION != response.json()["report"]["question"]
    assert chat(sid, first["healing_id"], "我还是担心考试").status_code == 200
    assert not healing.healing_store.slot(sid).state.adult_support.waiting


@pytest.mark.parametrize("available", [True, False])
def test_caller_condition_is_optional_and_known_value_does_not_trigger_question(support, available):
    sid, _, _, _ = support
    data = enter(sid, available).json()
    assert data["report"]["question"] != ADULT_QUESTION
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.available is available and state.adult_support.source == "caller"
    assert bool(data["report"]["suggestions"]) is available


def test_autonomous_method_never_triggers_adult_question_or_unscoped_yes(support):
    sid, _, _, _ = support
    healing.healing_agent.retriever = HealingRetriever([knowledge(executor="student", prerequisites=[])])
    first = enter(sid).json()
    assert first["report"]["question"] != ADULT_QUESTION and first["report"]["suggestions"]
    assert chat(sid, first["healing_id"], "有").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert not state.adult_support.asked and state.adult_support.available is None


def test_dialogue_condition_can_override_caller_and_survives_later_answers(support):
    sid, _, _, fake = support
    first = enter(sid, False).json()
    response = chat(sid, first["healing_id"], "现在老师能陪我了")
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.available is True
    assert state.memory.background.adult_support_available is False
    assert len(state.suggestions) == 1 and state.suggestions[0].active
    target = state.suggestions[0].suggestion_id
    assert fake.calls[-1]["memory"]["background"]["adult_support_available"] is True
    assert chat(sid, first["healing_id"], "我还是担心考试").status_code == 200
    assert healing.healing_store.slot(sid).state.adult_support.available is True
    assert chat(sid, first["healing_id"], "现在老师不能陪我了").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.available is False and not any(item.active for item in state.suggestions)
    assert chat(sid, first["healing_id"], "老师现在可以陪我了").status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.suggestions[0].suggestion_id == target and state.suggestions[0].active
    assert len(state.suggestions) == 1 and not state.feedback


def test_adult_answer_failure_and_retry_commit_once(support):
    sid, _, _, fake = support
    first = enter(sid).json()
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.fail = True
    assert chat(sid, first["healing_id"], "有", "adult-answer").status_code == 503
    assert healing.healing_store.slot(sid).state == before
    fake.fail = False
    response = chat(sid, first["healing_id"], "有", "adult-answer")
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert chat(sid, first["healing_id"], "有", "adult-answer").json() == response.json()
    assert healing.healing_store.slot(sid).state == state and state.turn_count == 1


@pytest.mark.parametrize("text,status", [("不想聊了", "ended"), ("先暂停", "paused"), ("我想自杀", "referred")])
def test_support_question_cannot_block_stop_pause_or_risk(support, text, status):
    sid, _, _, _ = support
    first = enter(sid).json()
    response = chat(sid, first["healing_id"], text)
    assert response.status_code == 200 and response.json()["status"] == status
    assert response.json()["report"]["question"] is None
    assert not any(item.active for item in healing.healing_store.slot(sid).state.suggestions)


def test_existing_explicit_screening_condition_is_used_without_reasking(support):
    sid, _, _, _ = support
    response = client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": "我12岁，上初一，考试有压力，妈妈能陪我"}],
    }})
    assert response.status_code == 200
    data = enter(sid).json()
    state = healing.healing_store.slot(sid).state
    assert data["report"]["suggestions"] and data["report"]["question"] != ADULT_QUESTION
    assert state.adult_support.source == "context" and state.adult_support.available is True
    assert state.memory.background.adult_support_available is None


def test_mixed_methods_confirm_only_deferred_adult_method_without_exceeding_two(support):
    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([knowledge(), knowledge("solo", executor="student",
        title="表达考试压力", steps=["写下考试让你担心的事。"], prerequisites=[])])
    fake.recommendations = ["name-concern", "solo"]
    first = enter(sid).json()
    state = healing.healing_store.slot(sid).state
    assert [item.knowledge_id for item in state.suggestions] == ["solo"]
    original = state.suggestions[0].model_copy(deep=True)
    fake.recommendations = []
    data = chat(sid, first["healing_id"], "有").json()
    state = healing.healing_store.slot(sid).state
    assert len(state.suggestions) == 2 and all(item.active for item in state.suggestions)
    assert state.suggestions[0] == original and len(data["report"]["suggestions"]) == 2
    assert not state.feedback and state.turn_count == 1


def test_confirmation_does_not_override_other_execution_constraints(support):
    sid, _, _, fake = support
    first = enter(sid).json()
    fake.fit_overrides = {key: {"verdict": "blocked", "evidence": "我没有时间"}
                          for key in ["name-concern", "other"]}
    response = chat(sid, first["healing_id"], "妈妈能陪我，但我没有时间")
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.available is True and not any(item.active for item in state.suggestions)
    assert not state.feedback


def test_simplification_method_scope_does_not_change_global_adult_condition(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    first = enter(sid, True).json()
    fake.recommendations = []
    fake.fit_overrides = {"name-concern": {"verdict": "blocked", "evidence": "第一个方法没有成人能陪我"}}
    response = chat(sid, first["healing_id"], "第一个方法没有成人能陪我")
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.available is True
    assert [item.active for item in state.suggestions] == [False, True]


def test_new_risk_after_question_blocks_method_confirmation(support):
    from test_healing import update_screening_risk
    sid, _, _, fake = support
    first = enter(sid).json()
    update_screening_risk(sid)
    calls = len(fake.calls)
    response = chat(sid, first["healing_id"], "有")
    assert response.status_code == 200 and response.json()["status"] == "referred"
    state = healing.healing_store.slot(sid).state
    assert not state.adult_support.waiting and not state.suggestions
    assert state.adult_support.available is None and len(fake.calls) == calls


def test_pending_method_can_be_abandoned_when_student_changes_goal(support):
    sid, _, _, fake = support
    first = enter(sid).json()
    fake.recommendations = []
    response = chat(sid, first["healing_id"], "我想改聊睡眠")
    assert response.status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.scene == "sleep" and not state.adult_support.waiting
    assert state.adult_support.deferred_knowledge_ids == []
    assert ADULT_QUESTION not in response.json()["messages"][-1]["content"]
