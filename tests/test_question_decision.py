"""Decision/phrasing split for the screening turn graph (自适应提问第一步).

What this file locks down:

1. the decision model chooses the topic *and* the intent; the program validates
   legality only and never re-ranks topics on the model's behalf;
2. the same state, driven by two different injected model actions, produces two
   different legal next questions;
3. an unknown topic, a closed topic or an invented quote is rejected — the turn
   is not committed and no substitute topic is chosen;
4. the nine topics cannot be completed until each one was explicitly asked;
5. every selected action is logged for later training or a replacement decider.

``QueueDecider`` stands in for the model so the same session state can be driven
two ways; the offline ``LocalQuestionDecider`` stays the default fallback.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import assessment as assessment_api
from backend.assessment.bank import ITEMS
from backend.assessment.engine import AssessmentEngine
from backend.assessment.extractor import RuleMockExtractor
from backend.assessment.models import (
    AssessmentSession, EvidenceEvent, build_report, can_complete, pending_item_ids,
)
from backend.assessment.question_generator import (
    DecisionContext, LocalQuestionDecider, LocalQuestionGenerator,
    OpenAICompatibleQuestionDecider, OpenAICompatibleQuestionGenerator,
    QuestionAction, QuestionActionRejected, QuestionGenerationUnavailable,
    build_question_pipeline_from_env, validate_question_action,
)
from backend.main import app

client = TestClient(app)

#: item_01 is confirmed by the student's own words; item_03 is only mentioned.
MENTION_TURN = "这两周几乎每天心情低落，睡眠也不好。"
ALL_ITEMS = tuple(item.item_id for item in ITEMS)


class QueueDecider:
    """Injects chosen actions; falls back to the offline decider when empty."""

    version = "queue_decider_test"

    def __init__(self, actions: list[QuestionAction] | None = None) -> None:
        self.actions = list(actions or [])
        self.contexts: list[DecisionContext] = []
        self._fallback = LocalQuestionDecider()

    def push(self, action: QuestionAction) -> None:
        self.actions.append(action)

    def decide(self, context: DecisionContext) -> QuestionAction:
        self.contexts.append(context)
        if self.actions:
            return self.actions.pop(0)
        return self._fallback.decide(context)


class RecordingGenerator:
    """Records the action it was handed and answers with fixed wording."""

    version = "recording_generator_test"

    def __init__(self, text: str = "这两周你有多少天胃口不好？") -> None:
        self.text = text
        self.calls: list[tuple[DecisionContext, QuestionAction]] = []

    def generate(self, context: DecisionContext, action: QuestionAction) -> str:
        self.calls.append((context, action))
        return self.text


def _engine(**kwargs) -> AssessmentEngine:
    kwargs.setdefault("extractor", RuleMockExtractor())
    return AssessmentEngine(**kwargs)


def _mentioned_state(action: QuestionAction) -> tuple[AssessmentSession, str]:
    """Answer the opening question, then let the injected action pick the next one."""
    decider = QueueDecider()
    engine = _engine(question_decider=decider)
    state, _ = engine.start()
    assert state.current_item_id == "item_01"
    decider.push(action)
    return engine.process(state, MENTION_TURN)


def _confirmed_state(*, never_asked: str | None = None) -> AssessmentSession:
    """All nine confirmed; optionally one of them was never explicitly asked."""
    state = AssessmentSession(current_item_id=None)
    for index, item in enumerate(ITEMS, start=1):
        entry = state.items[item.item_id]
        entry.status = "confirmed"
        entry.asked_once = item.item_id != never_asked
        entry.category = "not_at_all"
        entry.score = 0
        entry.evidence_quote = "完全没有"
        entry.evidence_turn_id = index
        entry.period = "past_14_days"
        entry.confirmed_by_user = True
        entry.evidence_history.append(EvidenceEvent(
            turn_id=index, quote="完全没有", period="past_14_days",
            proposed_category="not_at_all", accepted=True,
        ))
    return state


# ===========================================================================
# 1. The model's action decides the next question
# ===========================================================================


def test_same_state_with_different_model_actions_gives_different_legal_questions() -> None:
    to_mention = QuestionAction(target_item_id="item_03", intent="confirm_mention",
                                anchor_quote="睡眠也不好")
    to_open = QuestionAction(target_item_id="item_04", intent="open_topic")

    state_a, reply_a = _mentioned_state(to_mention)
    state_b, reply_b = _mentioned_state(to_open)

    # Same state before the decision: identical evidence and confirmations.
    assert state_a.items["item_01"].score == state_b.items["item_01"].score == 3
    assert state_a.items["item_03"].status == state_b.items["item_03"].status == "mentioned"
    assert (state_a.items["item_03"].evidence_history[0].quote
            == state_b.items["item_03"].evidence_history[0].quote == "睡眠也不好")

    assert state_a.current_item_id == "item_03"
    assert state_b.current_item_id == "item_04"
    assert reply_a != reply_b
    assert "睡眠也不好" in reply_a
    assert "食欲" in reply_b
    # The injected action is honoured, not replaced by a program-side priority.
    assert state_a.items["item_04"].asked_once is False
    assert state_b.items["item_03"].asked_once is False


def test_generator_only_phrases_the_selected_action() -> None:
    chosen = QuestionAction(target_item_id="item_04", intent="open_topic", reason="模型选择")
    generator = RecordingGenerator()
    decider = QueueDecider()
    engine = _engine(question_decider=decider, question_generator=generator)
    state, _ = engine.start()
    decider.push(chosen)
    state, reply = engine.process(state, "有几天")

    assert reply == generator.text
    context, handed = generator.calls[-1]
    assert handed == chosen, "生成器拿到的动作被程序改写了"
    assert handed.intent == "open_topic"
    assert context.latest_text == "有几天"
    assert "item_04" in context.allowed_item_ids
    assert state.current_item_id == "item_04"
    assert state.items["item_04"].asked_once is True
    assert state.action_log[-1].item_id == "item_04"
    assert state.action_log[-1].intent == "open_topic"


# ===========================================================================
# 2. Illegal actions are rejected, never worked around
# ===========================================================================


def test_unknown_topic_is_rejected() -> None:
    decider = QueueDecider()
    engine = _engine(question_decider=decider)
    state, _ = engine.start()
    decider.push(QuestionAction(target_item_id="item_10", intent="open_topic"))
    with pytest.raises(QuestionActionRejected) as excinfo:
        engine.process(state, "有几天")
    assert excinfo.value.code == "unknown_item"


def test_invented_quote_is_rejected() -> None:
    decider = QueueDecider()
    engine = _engine(question_decider=decider)
    state, _ = engine.start()
    decider.push(QuestionAction(target_item_id="item_03", intent="confirm_mention",
                                anchor_quote="我每天晚上都躲起来哭"))
    with pytest.raises(QuestionActionRejected) as excinfo:
        engine.process(state, MENTION_TURN)
    assert excinfo.value.code == "ungrounded_quote"


def test_repeating_a_completed_topic_is_rejected() -> None:
    decider = QueueDecider()
    engine = _engine(question_decider=decider)
    state, _ = engine.start()
    state, _ = engine.process(state, "这两周几乎每天心情低落")
    assert state.items["item_01"].status == "confirmed"
    assert state.items["item_01"].asked_once is True

    decider.push(QuestionAction(target_item_id="item_01", intent="clarify_frequency",
                                anchor_quote="这两周几乎每天心情低落"))
    with pytest.raises(QuestionActionRejected) as excinfo:
        engine.process(state, "有几天")
    assert excinfo.value.code == "topic_not_open"


def test_clarifying_a_topic_that_was_never_asked_is_rejected() -> None:
    decider = QueueDecider()
    engine = _engine(question_decider=decider)
    state, _ = engine.start()
    decider.push(QuestionAction(target_item_id="item_05", intent="clarify_frequency"))
    with pytest.raises(QuestionActionRejected) as excinfo:
        engine.process(state, "有几天")
    assert excinfo.value.code == "intent_mismatch"


def test_open_topic_requires_an_unasked_topic() -> None:
    session = AssessmentSession()
    session.items["item_01"].asked_once = True
    context = DecisionContext(session=session, allowed_item_ids=ALL_ITEMS)
    with pytest.raises(QuestionActionRejected) as excinfo:
        validate_question_action(
            QuestionAction(target_item_id="item_01", intent="open_topic"), context)
    assert excinfo.value.code == "intent_mismatch"


def test_resolve_conflict_requires_a_recorded_conflict() -> None:
    session = AssessmentSession()
    entry = session.items["item_03"]
    entry.asked_once = True
    entry.evidence_history.append(EvidenceEvent(
        turn_id=1, quote="睡不好", period="past_14_days", accepted=True))
    context = DecisionContext(session=session, allowed_item_ids=("item_03",),
                              latest_text="这两周睡不好")
    with pytest.raises(QuestionActionRejected) as excinfo:
        validate_question_action(QuestionAction(
            target_item_id="item_03", intent="resolve_conflict", anchor_quote="睡不好"), context)
    assert excinfo.value.code == "intent_mismatch"


def test_confirm_mention_requires_the_students_own_words() -> None:
    context = DecisionContext(session=AssessmentSession(), allowed_item_ids=("item_03",),
                              latest_text="反正就是不太舒服")
    with pytest.raises(QuestionActionRejected) as excinfo:
        validate_question_action(
            QuestionAction(target_item_id="item_03", intent="confirm_mention"), context)
    assert excinfo.value.code == "missing_anchor"


def test_legal_action_is_returned_normalised() -> None:
    session = AssessmentSession()
    session.items["item_03"].evidence_history.append(EvidenceEvent(
        turn_id=1, quote="睡不好", period="past_14_days"))
    context = DecisionContext(session=session, allowed_item_ids=("item_03",),
                              latest_text="这两周睡不好")
    action = validate_question_action(QuestionAction(
        target_item_id=" item_03 ", intent="confirm_mention", anchor_quote=" 睡不好 "), context)
    assert action.target_item_id == "item_03"
    assert action.anchor_quote == "睡不好"


def test_api_reports_a_rejected_action_without_committing_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decider = QueueDecider()
    monkeypatch.setattr(assessment_api, "engine", _engine(question_decider=decider))
    created = client.post("/api/assessment").json()
    session_id = created["session_id"]

    decider.push(QuestionAction(target_item_id="item_12", intent="open_topic"))
    rejected = client.post(f"/api/assessment/{session_id}/turn", json={"text": "有几天"})
    assert rejected.status_code == 503
    assert rejected.json()["error"]["code"] == "QUESTION_ACTION_REJECTED"

    unchanged = client.get(f"/api/assessment/{session_id}").json()
    assert unchanged["turns"] == []
    assert unchanged["items"]["item_01"]["score"] is None
    assert unchanged["action_log"][-1]["item_id"] == "item_01"
    client.delete(f"/api/assessment/{session_id}")


# ===========================================================================
# 3. Nine topics must all be explicitly asked before the assessment can end
# ===========================================================================


def test_topic_that_was_never_asked_blocks_completion() -> None:
    state = _confirmed_state(never_asked="item_05")
    assert can_complete(state) is False
    assert pending_item_ids(state) == ["item_05"]

    result = _engine().graph.invoke({"session": state, "user_text": "", "initial": True})
    updated = result["session"]
    assert updated.status == "in_progress", "九项未明确问完却结束了测评"
    assert updated.current_item_id == "item_05"
    assert updated.items["item_05"].asked_once is True
    assert build_report(updated).mapped_total is None


def test_completion_requires_all_nine_confirmed_and_asked() -> None:
    state = _confirmed_state()
    assert can_complete(state) is True

    result = _engine().graph.invoke({"session": state, "user_text": "", "initial": True})
    updated = result["session"]
    assert updated.status == "complete"
    assert "九项" in result["reply"]
    assert build_report(updated).mapped_total == 0


def test_turn_graph_exposes_the_decision_chain() -> None:
    nodes = set(_engine().graph.get_graph().nodes)
    assert {"guard", "extract", "apply", "decide", "phrase", "record"} <= nodes


# ===========================================================================
# 4. Each selected action is recorded for later training / replacement
# ===========================================================================


def test_action_log_records_each_selected_action() -> None:
    engine = _engine()
    state, first_question = engine.start()
    assert len(state.action_log) == 1
    opening = state.action_log[0]
    assert (opening.turn_id, opening.item_id, opening.intent) == (0, "item_01", "open_topic")
    assert opening.question == first_question
    assert opening.decider_version == LocalQuestionDecider.version

    state, reply = engine.process(state, MENTION_TURN)
    assert len(state.action_log) == 2
    entry = state.action_log[1]
    assert entry.turn_id == 1
    assert entry.item_id == "item_03"
    assert entry.intent == "confirm_mention"
    assert entry.anchor_quote == "睡眠也不好"
    assert entry.question == reply


# ===========================================================================
# 5. The model endpoint keeps the existing configuration
# ===========================================================================


def test_pipeline_factory_defaults_to_the_offline_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSESSMENT_QUESTION_GENERATOR", raising=False)
    decider, generator = build_question_pipeline_from_env()
    assert isinstance(decider, LocalQuestionDecider)
    assert isinstance(generator, LocalQuestionGenerator)


def test_pipeline_factory_reuses_the_existing_model_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for role in ("DECIDER", "GENERATOR"):
        for field in ("BASE_URL", "MODEL", "API_KEY", "THINKING"):
            monkeypatch.delenv(f"ASSESSMENT_{role}_{field}", raising=False)
    monkeypatch.setenv("ASSESSMENT_QUESTION_GENERATOR", "openai_compatible")
    monkeypatch.setenv("ASSESSMENT_LLM_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("ASSESSMENT_LLM_MODEL", "local-model")
    monkeypatch.setenv("ASSESSMENT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("ASSESSMENT_LLM_THINKING", "disabled")

    decider, generator = build_question_pipeline_from_env()
    assert isinstance(decider, OpenAICompatibleQuestionDecider)
    assert isinstance(generator, OpenAICompatibleQuestionGenerator)
    assert decider.base_url == generator.base_url == "http://127.0.0.1:8001/v1"
    assert decider.model == generator.model == "local-model"
    assert decider.thinking_mode == generator.thinking_mode == "disabled"


def test_pipeline_factory_uses_distinct_decision_and_generation_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASSESSMENT_QUESTION_GENERATOR", "openai_compatible")
    monkeypatch.setenv("ASSESSMENT_LLM_BASE_URL", "http://extractor.test/v1")
    monkeypatch.setenv("ASSESSMENT_LLM_MODEL", "extractor-model")
    monkeypatch.setenv("ASSESSMENT_LLM_API_KEY", "extractor-key")
    monkeypatch.setenv("ASSESSMENT_DECIDER_BASE_URL", "http://decider.test/v1")
    monkeypatch.setenv("ASSESSMENT_DECIDER_MODEL", "decision-model")
    monkeypatch.setenv("ASSESSMENT_DECIDER_API_KEY", "decision-key")
    monkeypatch.setenv("ASSESSMENT_DECIDER_THINKING", "enabled")
    monkeypatch.setenv("ASSESSMENT_GENERATOR_BASE_URL", "http://generator.test/v1")
    monkeypatch.setenv("ASSESSMENT_GENERATOR_MODEL", "phrasing-model")
    monkeypatch.setenv("ASSESSMENT_GENERATOR_API_KEY", "phrasing-key")
    monkeypatch.setenv("ASSESSMENT_GENERATOR_THINKING", "disabled")

    decider, generator = build_question_pipeline_from_env()

    assert decider.base_url == "http://decider.test/v1"
    assert decider.model == "decision-model"
    assert decider.api_key == "decision-key"
    assert decider.thinking_mode == "enabled"
    assert generator.base_url == "http://generator.test/v1"
    assert generator.model == "phrasing-model"
    assert generator.api_key == "phrasing-key"
    assert generator.thinking_mode == "disabled"


def _model_response(payload: dict, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{
        "finish_reason": finish_reason,
        "message": {"content": json.dumps(payload)},
    }]})


def _decider_from_queue(actions: list[dict], captured: list[dict] | None = None):
    queue = list(actions)

    def handle(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(json.loads(request.content))
        return _model_response(queue.pop(0))

    return OpenAICompatibleQuestionDecider(
        "http://local.test/v1", "test-model",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )


def test_model_chosen_action_drives_the_next_question_and_sees_the_full_state() -> None:
    captured: list[dict] = []
    decider = _decider_from_queue([
        {"target_item_id": "item_01", "intent": "open_topic", "anchor_quote": "", "reason": "开场"},
        {"target_item_id": "item_04", "intent": "open_topic", "anchor_quote": "", "reason": "学生说到吃不下"},
    ], captured)
    engine = _engine(question_decider=decider)

    state, _ = engine.start()
    assert state.current_item_id == "item_01"
    state, reply = engine.process(state, "有几天")
    assert state.current_item_id == "item_04"
    assert "食欲" in reply
    assert state.action_log[-1].intent == "open_topic"
    assert state.action_log[-1].decider_version.startswith("openai_compatible_decider_v1")

    # The decider read this turn's answer, the extracted evidence, the current
    # topic and all nine topics' asked_once / confirmed state.
    sent = json.loads(captured[1]["messages"][1]["content"])
    assert sent["current_item_id"] == "item_01"
    assert sent["latest_student_answer"] == "有几天"
    assert len(sent["topics"]) == 9
    assert sent["topics"][0]["asked_once"] is True
    assert sent["topics"][0]["confirmed"] is True
    assert "item_02" in sent["allowed_item_ids"]
    assert sent["extracted_evidence"][0]["item_id"] == "item_01"
    assert sent["extracted_evidence"][0]["quote"] == "有几天"
    assert captured[1]["response_format"] == {"type": "json_object"}


def test_model_action_on_a_closed_topic_is_rejected_end_to_end() -> None:
    decider = _decider_from_queue([
        {"target_item_id": "item_01", "intent": "open_topic", "anchor_quote": "", "reason": "开场"},
        {"target_item_id": "item_01", "intent": "open_topic", "anchor_quote": "", "reason": "重复"},
    ])
    engine = _engine(question_decider=decider)
    state, _ = engine.start()
    with pytest.raises(QuestionActionRejected) as excinfo:
        engine.process(state, "有几天")
    assert excinfo.value.code == "topic_not_open"


def test_truncated_decision_output_is_rejected() -> None:
    client_ = httpx.Client(transport=httpx.MockTransport(
        lambda request: _model_response({}, "length")))
    decider = OpenAICompatibleQuestionDecider("http://local.test/v1", "m", client=client_)
    context = DecisionContext(session=AssessmentSession(), allowed_item_ids=ALL_ITEMS)
    with pytest.raises(QuestionGenerationUnavailable):
        decider.decide(context)


def test_generator_rejects_wording_that_asks_two_questions() -> None:
    client_ = httpx.Client(transport=httpx.MockTransport(
        lambda request: _model_response({"question": "这两周睡得好吗？吃得好吗？"})))
    generator = OpenAICompatibleQuestionGenerator("http://local.test/v1", "m", client=client_)
    context = DecisionContext(session=AssessmentSession(), allowed_item_ids=ALL_ITEMS)
    with pytest.raises(QuestionGenerationUnavailable):
        generator.generate(context, QuestionAction(target_item_id="item_01", intent="open_topic"))
