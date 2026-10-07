"""Cross-turn regressions from the pre-commit review."""

from uuid import uuid4

import pytest

from backend.core.session_manager import session_manager
from backend.healing.adult_support import support_signal
from backend.healing.conversation import question_problem
from backend.healing.execution import feedback_targets, preparation_targets, simplification_targets
from backend.healing.interaction import pause_signal
from backend.healing.retriever import HealingRetriever
from backend.healing.safety import guard_risk
from backend.models.healing import Feedback
from backend.models.states import RiskResult
from test_healing import chat, client, healing, knowledge, start, support


@pytest.mark.parametrize("text", [
    "现在完全无法上学，今晚准备跳楼",
    "今晚准备跳楼，现在完全无法上学",
    "我被同学威胁，今晚准备跳楼",
    "今晚准备跳楼，我被同学威胁",
])
def test_explicit_plan_is_high_regardless_of_clause_order(support, text):
    sid, _, _, fake = support
    response = start(sid, background={"current_concern": text})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "referred"
    assert response.json()["risk"]["risk_level"] == "high"
    assert any("跳楼" in evidence and evidence in text for evidence in response.json()["risk"]["key_evidence"])
    assert not fake.calls


@pytest.mark.parametrize("earlier", ["assessment", "background", "transcript", "event"])
def test_earlier_medium_context_never_hides_later_plan(support, earlier):
    sid, _, _, _ = support
    start(sid)
    memory = healing.healing_store.slot(sid).state.memory.model_copy(deep=True)
    memory.background.current_concern = None
    memory.current_session_messages = ["今晚准备跳楼"]
    if earlier == "assessment":
        memory.assessment.risk = RiskResult(risk_level="medium", risk_score=.7, requires_intervention=True)
    elif earlier == "background":
        memory.background.current_concern = "现在完全无法上学"
    elif earlier == "transcript":
        memory.current_session_messages.insert(0, "现在完全无法上学")
    else:
        memory.current_session_messages = []
        memory.background.important_events = ["现在完全无法上学", "今晚准备跳楼"]
    risk = guard_risk(memory, session_risk=RiskResult())
    assert risk.risk_level == "high" and risk.requires_intervention


def test_read_refreshes_medium_report_to_later_plan_once(support):
    from backend.models.enums import MessageRole
    from backend.models.states import Message

    sid, _, _, fake = support
    initial = start(sid, background={"current_concern": "现在完全无法上学"}).json()
    assert initial["risk"]["risk_level"] == "medium"
    session_manager.modify_session(sid, lambda state: state.conversation_history.append(
        Message(role=MessageRole.USER, content="今晚准备跳楼")))
    refreshed = client.get(f"/api/healing/{sid}")
    assert refreshed.status_code == 200 and refreshed.json()["risk"]["risk_level"] == "high"
    assert client.get(f"/api/healing/{sid}").json() == refreshed.json()
    assert not fake.calls


@pytest.mark.parametrize("effect,quote", [
    ("ineffective", "第一个方法没有帮助"),
    ("worse", "第一个方法让我更难受"),
    ("helpful", "第一个方法有帮助"),
])
@pytest.mark.parametrize("closing", ["先暂停", "第二个方法准备试试"])
def test_pause_retains_effect_of_already_confirmed_attempt(support, effect, quote, closing):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    state = healing.healing_store.slot(sid).state
    target_id, second_id = [item.suggestion_id for item in state.suggestions]
    fake.recommendations = []
    fake.feedback = [Feedback(suggestion_id=target_id, execution="attempted", evidence="第一个方法我试了")]
    assert chat(sid, hid, "第一个方法我试了").status_code == 200
    fake.feedback = [Feedback(suggestion_id=target_id, execution="attempted", effect=effect, evidence=quote)]
    text, mid = quote + "，" + closing, str(uuid4())
    response = chat(sid, hid, text, mid)
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    assert state.status == "paused"
    assert state.suggestions[0].execution == "attempted" and state.suggestions[0].effect == effect
    assert state.suggestions[0].active == (effect == "helpful")
    assert len(state.feedback) == (3 if "准备" in closing else 2)
    if "准备" in closing:
        assert state.suggestions[1].execution == "prepared"
        assert state.feedback[-1].suggestion_id == second_id
    calls = len(fake.calls)
    assert chat(sid, hid, text, mid).json() == response.json()
    assert healing.healing_store.slot(sid).state == state and len(fake.calls) == calls


def test_preparing_second_method_does_not_drop_first_method_decline(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    state = healing.healing_store.slot(sid).state
    first_id, second_id = [item.suggestion_id for item in state.suggestions]
    fake.recommendations = []
    fake.feedback = [Feedback(suggestion_id=first_id, execution="declined", evidence="第一个方法我不想用")]
    fake.fit_overrides = {"name-concern": {"verdict": "blocked", "evidence": "第一个方法我不想用"}}
    response = chat(sid, hid, "第一个方法我不想用，第二个方法准备试试")
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert state.status == "paused"
    assert state.suggestions[0].execution == "declined" and not state.suggestions[0].active
    assert state.suggestions[1].execution == "prepared"
    assert {(item.suggestion_id, item.execution) for item in state.feedback} == {
        (first_id, "declined"), (second_id, "prepared")}


def test_mixed_pause_feedback_failure_is_atomic_and_retry_records_once(support):
    sid, _, _, fake = support
    hid = start(sid).json()["healing_id"]
    target = healing.healing_store.slot(sid).state.suggestions[0].suggestion_id
    fake.feedback = [Feedback(suggestion_id=target, execution="attempted", evidence="我试了")]
    assert chat(sid, hid, "我试了").status_code == 200
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    text, mid = "第一个方法让我更难受，先暂停", str(uuid4())
    fake.feedback = [Feedback(suggestion_id=target, execution="attempted", effect="worse", evidence=text)]
    fake.fail = True
    assert chat(sid, hid, text, mid).status_code == 503
    assert healing.healing_store.slot(sid).state == before
    fake.fail = False
    response = chat(sid, hid, text, mid)
    assert response.status_code == 200
    assert chat(sid, hid, text, mid).json() == response.json()
    state = healing.healing_store.slot(sid).state
    assert len(state.feedback) == 2 and state.turn_count == before.turn_count + 1
    assert state.suggestions[0].effect == "worse" and not state.suggestions[0].active


@pytest.mark.parametrize("text,requested", [
    ("先暂停", True), ("今天先暂停一下", True), ("不要先暂停，我想继续聊考试", False),
    ("不想先暂停", False), ("别先暂停", False), ("不用先暂停", False),
    ("不必先暂停", False), ("不需要先暂停", False), ("无需先暂停", False),
    ("我说的不是先暂停", False), ("先暂停，算了不要先暂停", False),
    ("不要先暂停，还是先暂停吧", True), ("不是不要先暂停", True),
    ("我还想继续聊", None),
])
def test_pause_request_keeps_original_polarity_and_latest_correction(text, requested):
    assert pause_signal(text) is requested


@pytest.mark.parametrize("text", ["不要先暂停，我想继续聊考试", "先暂停，算了不要先暂停，我想继续聊考试"])
def test_denied_pause_does_not_pause(support, text):
    sid, _, _, _ = support
    hid = start(sid).json()["healing_id"]
    response = chat(sid, hid, text)
    assert response.status_code == 200 and response.json()["status"] == "active"


def test_denied_pause_overrides_automatic_preparation_pause(support):
    sid, _, _, _ = support
    hid = start(sid).json()["healing_id"]
    response = chat(sid, hid, "不要先暂停，第一个方法我准备试试，还想继续聊考试")
    assert response.status_code == 200 and response.json()["status"] == "active"
    assert healing.healing_store.slot(sid).state.suggestions[0].execution == "prepared"


def test_restore_operation_id_reuse_with_changed_content_conflicts(support):
    sid, _, _, _ = support
    initial = start(sid).json()
    request_id = str(uuid4())
    restore = {"session_id": sid, "request_id": request_id}
    response = client.post("/api/healing/start", json=restore)
    assert response.status_code == 200
    assert client.post("/api/healing/start", json=restore).json() == response.json()
    changed = {**restore, "regenerate": True, "expected_healing_id": initial["healing_id"]}
    assert client.post("/api/healing/start", json=changed).status_code == 409
    assert healing.healing_store.slot(sid).state.healing_id == initial["healing_id"]


def test_restore_retry_after_regeneration_reports_state_change(support):
    sid, _, _, _ = support
    initial = start(sid).json()
    restore = {"session_id": sid, "request_id": str(uuid4())}
    assert client.post("/api/healing/start", json=restore).status_code == 200
    regenerated = start(sid, regenerate=True, expected_healing_id=initial["healing_id"])
    assert regenerated.status_code == 200
    response = client.post("/api/healing/start", json=restore)
    assert response.status_code == 409 and response.json()["error"]["code"] == "HEALING_STATE_CHANGED"


def test_original_second_ordinal_survives_first_method_deactivation(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    first_id, second_id = [item.suggestion_id for item in healing.healing_store.slot(sid).state.suggestions]
    fake.recommendations = []
    fake.feedback = [Feedback(suggestion_id=first_id, execution="declined", evidence="第一个方法我不想用")]
    assert chat(sid, hid, "第一个方法我不想用").status_code == 200
    text = "第二个方法我试了，有帮助"
    fake.feedback = [Feedback(suggestion_id=second_id, execution="attempted", effect="helpful", evidence=text)]
    response = chat(sid, hid, text)
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert [item.display_number for item in state.suggestions] == [1, 2]
    assert state.suggestions[1].execution == "attempted" and state.suggestions[1].effect == "helpful"
    assert "display_number" not in response.text


def test_inactive_first_ordinal_is_not_reassigned_to_second(support):
    sid, _, _, fake = support
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    state = healing.healing_store.slot(sid).state
    state.suggestions[0].active = False
    references = state.suggestions
    assert feedback_targets("第一个方法我试了", "我试了", references) == {references[0].suggestion_id}
    assert feedback_targets("我试了", "我试了", references) == set()
    assert preparation_targets("第二个方法准备试试", references) == {references[1].suggestion_id}
    assert preparation_targets("第一个方法准备试试", references) == set()
    assert preparation_targets("我准备试试", references) == set()
    assert simplification_targets("第二个方法看不懂", references) == {references[1].suggestion_id}
    assert simplification_targets("第一个方法看不懂", references) == {references[0].suggestion_id}


def test_replacement_method_keeps_global_number_in_messages_and_context(support):
    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([knowledge(key) for key in ["name-concern", "other", "third"]])
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    first = healing.healing_store.slot(sid).state.suggestions[0]
    fake.recommendations = ["third"]
    quote = "第一个方法我试了，没有帮助"
    fake.feedback = [Feedback(suggestion_id=first.suggestion_id, execution="attempted", effect="ineffective", evidence=quote)]
    response = chat(sid, hid, quote)
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert [item.display_number for item in state.suggestions] == [1, 2, 3]
    assert "第3个方法" in response.json()["messages"][-1]["content"]
    fake.feedback, fake.recommendations = [], []
    assert chat(sid, hid, "第三个方法不方便做，先暂停").status_code == 200
    state = healing.healing_store.slot(sid).state
    snapshot = state.context_updates[-1].reference_suggestions
    assert [item.display_number for item in snapshot] == [2, 3]
    assert feedback_targets("第3个方法我试了", "我试了", snapshot) == {state.suggestions[2].suggestion_id}
    assert feedback_targets("第三个方法我试了", "我试了", snapshot) == {state.suggestions[2].suggestion_id}
    assert feedback_targets("两个方法都试了", "试了", state.suggestions) == set()
    assert support_signal("第三个方法没有成人能陪我") == (False, None)
    assert question_problem("你说的是哪一个方法？", "第3个方法我试了", state)


def test_ambiguous_late_feedback_clarifies_instead_of_using_only_survivor(support):
    from test_healing_conversation import QuestionClient

    sid, _, _, _ = support
    model = QuestionClient()
    healing.healing_agent.client = model
    model.recommendations = ["name-concern", "other"]
    hid = start(sid).json()["healing_id"]
    state = healing.healing_store.slot(sid).state
    state.suggestions[0].active = False
    target = state.suggestions[1]
    model.recommendations = []
    model.feedback = [Feedback(suggestion_id=target.suggestion_id, execution="attempted", evidence="我试了")]
    response = chat(sid, hid, "我试了")
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert not state.feedback and target.execution == "unconfirmed"
    assert "哪一个方法" in response.json()["messages"][-1]["content"]


def test_deferred_adult_method_after_replacements_does_not_renumber_report(support):
    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([
        knowledge(key, executor="student", prerequisites=[]) for key in ["name-concern", "other", "third"]
    ] + [knowledge("fourth")])
    fake.recommendations = ["name-concern", "other"]
    hid = start(sid, background={"school_stage": "middle", "current_concern": "考试压力"}).json()["healing_id"]
    state = healing.healing_store.slot(sid).state
    report_ids = list(state.report.suggestion_ids)
    for target_id, quote, replacement in [
        (report_ids[0], "第一个方法我不想用", "third"),
        (report_ids[1], "第二个方法我不想用", "fourth"),
    ]:
        fake.feedback = [Feedback(suggestion_id=target_id, execution="declined", evidence=quote)]
        fake.recommendations = [replacement]
        response = chat(sid, hid, quote)
        assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert state.adult_support.waiting and state.adult_support.deferred_knowledge_ids == ["fourth"]
    fake.feedback, fake.recommendations = [], []
    response = chat(sid, hid, "有")
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state
    assert [item.display_number for item in state.suggestions] == [1, 2, 3, 4]
    assert state.report.suggestion_ids == report_ids and len(response.json()["report"]["suggestions"]) == 2
    assert "第4个方法" in response.json()["messages"][-1]["content"]
    assert sum(item.active for item in state.suggestions) == 2
