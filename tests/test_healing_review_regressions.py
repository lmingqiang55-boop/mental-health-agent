"""Cross-turn regressions from the pre-commit review."""

from uuid import uuid4

import pytest

from backend.core.session_manager import session_manager
from backend.healing.adult_support import support_signal
from backend.healing.agent import AgentDraft, NarrativeCheck
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
    calls = len(fake.calls)
    refreshed = client.get(f"/api/healing/{sid}")
    assert refreshed.status_code == 200 and refreshed.json()["risk"]["risk_level"] == "high"
    assert client.get(f"/api/healing/{sid}").json() == refreshed.json()
    assert len(fake.calls) == calls


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
    content = response.json()["messages"][-1]["content"]
    assert "第3个方法" not in content and "执行条件" not in content
    citations = response.json()["messages"][-1]["references"]
    assert len(citations) == 1 and citations[0]["title"] == state.suggestions[2].title
    assert citations[0]["text"] and "knowledge_id" not in response.text
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
    citations = response.json()["messages"][-1]["references"]
    assert [item["title"] for item in citations] == [state.suggestions[3].title]
    assert sum(item.active for item in state.suggestions) == 2


def test_reference_carries_conditions_and_cautions_but_no_source(support):
    """浅字给的是知识库原文，连同它本来就要求的条件和要注意的事；来源信息不出现在学生响应里。"""
    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([
        knowledge("name-concern", executor="student", prerequisites=[], exclusions=[]),
        knowledge("other", title="换一种说法", executor="student",
                  prerequisites=["先跟可信任的成人说一声。"], exclusions=["不要在很困的时候做。"]),
    ])
    fake.recommendations = ["name-concern"]
    hid = start(sid).json()["healing_id"]
    target = healing.healing_store.slot(sid).state.suggestions[0]
    quote = "第一个方法我试了，没有帮助"
    fake.recommendations = ["other"]
    fake.feedback = [Feedback(suggestion_id=target.suggestion_id, execution="attempted",
                              effect="ineffective", evidence=quote)]
    response = chat(sid, hid, quote)
    assert response.status_code == 200, response.text
    citations = response.json()["messages"][-1]["references"]
    assert len(citations) == 1 and citations[0]["title"] == "换一种说法"
    assert citations[0]["conditions"] == ["先跟可信任的成人说一声。"]
    assert citations[0]["cautions"] == ["不要在很困的时候做。"]
    assert not citations[0]["text"].startswith("执行条件")
    assert "合成来源" not in response.text and "example.org" not in response.text


def test_simplified_turn_speaks_from_the_verified_wording_and_cites_it(support):
    """学生说看不懂时，交给模型的是已校验的简化版原文，浅字也随之换成那条原文。"""
    from backend.models.healing import KnowledgeWording

    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([knowledge("name-concern", wordings=[
        KnowledgeWording(wording_id="name-concern-simple", style="simple", title="说说今天最烦的事",
                         goal="把担心说出口", steps=["跟身边的大人说一句今天最烦的事。"],
                         semantic_checked=True)])])
    fake.recommendations = ["name-concern"]
    hid = start(sid).json()["healing_id"]
    target = healing.healing_store.slot(sid).state.suggestions[0]
    fake.recommendations = []
    fake.simplify_id = target.suggestion_id
    response = chat(sid, hid, "第一个方法看不懂，能简单一点吗")
    assert response.status_code == 200, response.text
    offers = fake.calls[-1]["simplified_wordings"]
    assert [item["suggestion_id"] for item in offers] == [target.suggestion_id]
    assert offers[0]["steps"] == ["跟身边的大人说一句今天最烦的事。"]
    assert offers[0]["conditions"] == target.prerequisites
    assert offers[0]["steps"] != target.steps
    state = healing.healing_store.slot(sid).state
    assert state.suggestions[0].wording_id == "name-concern-simple"
    citations = response.json()["messages"][-1]["references"]
    assert [item["title"] for item in citations] == ["说说今天最烦的事"]
    assert "跟身边的大人说一句今天最烦的事。" in citations[0]["text"]
    assert "简化文字" not in response.json()["messages"][-1]["content"]


def test_simplification_without_a_verified_wording_offers_nothing(support):
    """没有通过校验的简化表达时，不给模型任何“自己编一个简化版”的口子。"""
    sid, _, _, fake = support
    fake.recommendations = ["name-concern"]
    hid = start(sid).json()["healing_id"]
    target = healing.healing_store.slot(sid).state.suggestions[0]
    fake.recommendations = []
    fake.simplify_id = target.suggestion_id
    assert chat(sid, hid, "第一个方法看不懂，能简单一点吗").status_code == 200
    assert fake.calls[-1]["simplified_wordings"] == []
    state = healing.healing_store.slot(sid).state
    assert state.suggestions[0].wording_id == target.wording_id


def test_narrative_check_receives_already_proposed_methods(support):
    """复核清单里带上已经提出过的方法，复述旧方法不会再被当成编造。"""
    from backend.healing.agent import NarrativeCheck
    from test_healing import FakeClient

    sid, _, _, _ = support

    class RecordingClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.checked = []

        async def generate(self, system, payload, schema, **kwargs):
            if schema is NarrativeCheck:
                self.checked.append(payload)
            return await super().generate(system, payload, schema, **kwargs)

    model = RecordingClient()
    model.recommendations = ["name-concern"]
    healing.healing_agent.client = model
    hid = start(sid).json()["healing_id"]
    target = healing.healing_store.slot(sid).state.suggestions[0]
    model.recommendations = []
    assert chat(sid, hid, "这个方法我试了").status_code == 200
    payload = model.checked[-1]
    assert [item["suggestion_id"] for item in payload["previous_methods"]] == [target.suggestion_id]
    assert payload["previous_methods"][0]["steps"] == target.steps
    assert payload["previous_methods"][0]["conditions"] == target.prerequisites
    assert payload["simplified_wordings"] == []


def test_report_suggestion_gives_the_same_light_text_as_a_citation(support):
    """首报里的方法也带好浅字原文，且与聊天轮引用的连法完全一致。"""
    from backend.healing.agent import make_reference

    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([knowledge("name-concern")])
    fake.recommendations = ["name-concern"]
    suggestion = start(sid).json()["report"]["suggestions"][0]
    target = healing.healing_store.slot(sid).state.suggestions[0]
    assert suggestion["text"] == make_reference(target).text
    assert suggestion["text"] == "梳理考试压力；在成人指导下说出让你有压力的事情。"
    assert suggestion["prerequisites"] == list(target.prerequisites)
    assert suggestion["cautions"] == list(target.cautions)
    assert "\n" not in suggestion["text"] and "1." not in suggestion["text"]


def test_priority_report_status_follows_the_model_instead_of_hardcoded_active(support):
    """学生同时带来两件事时，首报状态也听模型的，不再写死 active。"""
    from backend.healing.agent import AgentDraft
    from test_healing import FakeClient

    sid, _, _, _ = support

    class PausingReportClient(FakeClient):
        async def generate(self, system, payload, schema, **kwargs):
            draft = await super().generate(system, payload, schema, **kwargs)
            if schema is AgentDraft and payload["phase"] == "report":
                draft.next_action = "pause"
                draft.question = None
            return draft

    healing.healing_agent.client = PausingReportClient()
    data = start(sid, background={"school_stage": "middle", "current_concern": "我考试很紧张，晚上也睡不好"}).json()
    assert data["status"] == "paused"
    assert data["report"]["question"] is None
    assert data["report"]["suggestions"] == []


def test_confirmation_first_report_keeps_the_general_caution(support):
    """学生一次带来好几件事时的首报，也要带那句通用提醒。

    这条路径原先不带 cautions，报告卡片里"要留意的是"整块是空的，
    和普通首报不一致。
    """

    from backend.healing.agent import REPORT_CAUTION

    sid, _, _, _ = support
    data = start(sid, background={"school_stage": "middle", "current_concern": "我考试很紧张，晚上也睡不好"}).json()
    assert data["report"]["suggestions"] == []
    assert data["report"]["question"]
    assert data["report"]["cautions"] == [REPORT_CAUTION]


class SpokenClient:
    """可指定"正文里自报提到了哪些方法"的客户端。"""

    def __init__(self, base, *, knowledge_ids=(), suggestion_ids=(), recommend=()):
        self.base = base
        self.knowledge_ids = list(knowledge_ids)
        self.suggestion_ids = list(suggestion_ids)
        self.recommend = list(recommend)
        self.narrative_payloads = []

    async def generate(self, system, payload, schema, **kwargs):
        if schema is NarrativeCheck:
            self.narrative_payloads.append(payload)
        draft = await self.base.generate(system, payload, schema, **kwargs)
        if schema is AgentDraft and payload["phase"] != "report":
            draft.recommendation_ids = list(self.recommend)
            draft.spoken_knowledge_ids = list(self.knowledge_ids)
            draft.spoken_suggestion_ids = list(self.suggestion_ids)
        return draft


def _start_one_method(sid, fake):
    fake.recommendations = ["name-concern"]
    hid = start(sid).json()["healing_id"]
    fake.recommendations = []
    return hid


def test_prose_claiming_a_method_it_did_not_select_is_rejected(support):
    """正文说了一条候选的做法、却没选中它 → 本轮报错，上一轮状态原样保留。

    没有这一条时，模型说了候选 C、却选中并引用了 A，程序完全看不出来，
    学生看到的是"正文推荐一个做法、下面的浅字是另一条方法"。
    """

    sid, _, _, fake = support
    hid = _start_one_method(sid, fake)
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    claimed = SpokenClient(fake, knowledge_ids=["other"])
    healing.healing_agent.client = claimed

    response = chat(sid, hid, "我还是有点紧张")
    assert response.status_code == 503
    assert healing.healing_store.slot(sid).state == before
    # 重试那一轮必须带上结构化反馈，说明这是可修复的一类问题。
    assert claimed.base.calls[-1]["validation_feedback"]


def test_prose_claiming_a_method_it_selected_is_cited(support):
    """正文提到的做法与浅字对得上时正常出一轮，且浅字是那条方法的原文。"""

    sid, _, _, fake = support
    hid = _start_one_method(sid, fake)
    claimed = SpokenClient(fake, knowledge_ids=["other"], recommend=["other"])
    healing.healing_agent.client = claimed

    response = chat(sid, hid, "我还是有点紧张")
    assert response.status_code == 200, response.text
    references = response.json()["messages"][-1]["references"]
    # 浅字必须就是正文提到的那一条（"other"），不能是另一条方法。
    assert [item["text"] for item in references] == ["梳理考试压力；在成人指导下表达考试担忧。"]
    assert "source_title" not in response.text


def test_repeating_a_presented_method_needs_no_new_citation(support):
    """顺带复述一条以前提过的方法：允许，而且不再重复附浅字。"""

    sid, _, _, fake = support
    hid = _start_one_method(sid, fake)
    target = healing.healing_store.slot(sid).state.suggestions[0]
    claimed = SpokenClient(fake, suggestion_ids=[target.suggestion_id])
    healing.healing_agent.client = claimed

    response = chat(sid, hid, "上次那个方法我还没试")
    assert response.status_code == 200, response.text
    assert response.json()["messages"][-1]["references"] == []


def test_narrative_checker_only_sees_the_method_the_prose_claims(support):
    """复核器只看"选中的 + 正文自报提到的"，不再拿到本轮全部候选。"""

    sid, _, _, fake = support
    hid = _start_one_method(sid, fake)
    claimed = SpokenClient(fake, knowledge_ids=["other"], recommend=["other"])
    healing.healing_agent.client = claimed
    assert chat(sid, hid, "我还是有点紧张").status_code == 200

    seen = claimed.narrative_payloads[-1]["knowledge"]
    assert [item["knowledge_id"] for item in seen] == ["other"]


def test_question_only_rejection_is_structural_not_message_matching(support):
    """只否掉提问的那类拒绝，靠结构化原因走"去掉问题复用正文"。

    以前是 ``str(exc).startswith("陪伴每轮只保留")``：提示词里改一个字，
    这条路径就失效，后果是"只是提问不合格"退化成整轮 503。
    """

    from backend.healing.agent import REASON_QUESTION, HealingDraftInvalid, rejected_question_only
    from test_healing import FakeClient

    # 文案相同但没带原因 → 按正文被否处理；带原因才走只去问题的分支。
    assert not rejected_question_only(HealingDraftInvalid("陪伴每轮只保留一个主要问题"))
    assert rejected_question_only(HealingDraftInvalid("随便什么文案", reason=REASON_QUESTION))

    sid, _, _, fake = support

    class TwoQuestionClient(FakeClient):
        async def generate(self, system, payload, schema, **kwargs):
            draft = await super().generate(system, payload, schema, **kwargs)
            if schema is AgentDraft:
                draft.question = "最近睡得怎么样？平时几点开始准备睡？"
            return draft

    healing.healing_agent.client = TwoQuestionClient()
    data = start(sid).json()
    assert data["status"] == "paused"
    assert data["report"]["question"] is None
    assert healing.healing_store.slot(sid).state.report.understanding
    assert "？" not in data["messages"][-1]["content"] if data["messages"] else True


def test_overlong_corpus_method_is_truncated_instead_of_a_500(support):
    """一条知识的目标 + 6 个长步骤会超过浅字上限，只能截断，不能抛 500。

    上限是 1200 字，而语料允许"目标 300 字 + 6 步各 500 字"（合计约 3300 字）。
    超限时抛的是字段校验错误，绕过"失败即报错、进度保留"的 503 通道、直接变 500。
    """

    from backend.models.healing import REFERENCE_TEXT_MAX

    sid, _, _, fake = support
    healing.healing_agent.retriever = HealingRetriever([
        knowledge(goal="梳理" * 150, steps=["说" * 500 for _ in range(6)])])
    fake.recommendations = ["name-concern"]
    response = start(sid)
    assert response.status_code == 200, response.text
    text = response.json()["report"]["suggestions"][0]["text"]
    assert len(text) <= REFERENCE_TEXT_MAX
    assert text.endswith("…")


def test_blank_knowledge_goal_is_rejected_when_the_corpus_loads():
    """纯空白的 goal 会在加载时就报错，不会等到生成那一轮变成 500。"""

    from pydantic import ValidationError

    from backend.models.healing import KnowledgeItem

    payload = knowledge().model_dump()
    payload["goal"] = "   "
    with pytest.raises(ValidationError):
        KnowledgeItem(**payload)


def test_source_title_never_reaches_the_model_or_the_student(support):
    """知识来源标题只留在后台：既不进发给模型的方法清单，也不进学生可见内容。"""

    import json

    from backend.models.healing import Suggestion

    sid, _, _, fake = support
    hid = _start_one_method(sid, fake)
    assert chat(sid, hid, "这个方法我试了").status_code == 200

    assert "source_title" not in Suggestion.model_fields
    sent = fake.calls[-1]["suggestions"]
    assert sent and all("source_title" not in item for item in sent)
    assert "source_title" not in json.dumps(client.get(f"/api/healing/{sid}").json(), ensure_ascii=False)
