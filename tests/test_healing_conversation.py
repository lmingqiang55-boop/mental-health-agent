"""Fixed regressions for confirmed conversation failures; no remote models."""

from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from test_healing import FakeClient, chat, start, support
from backend.api import healing
from backend.healing.agent import AgentDraft, NarrativeCheck
from backend.healing.client import HealingUnavailable
from backend.healing.conversation import question_problem
from backend.healing.execution import unresolved_feedback
from backend.healing.interaction import repeated_answer
from backend.healing.knowledge import load_knowledge
from backend.healing.retriever import HealingRetriever
from backend.models.healing import Feedback, HealingBackground, HealingMessage, HealingState


@pytest.mark.parametrize('question', [
    '开始这个方法时，你觉得哪一步最难做到？',
    '开始这个方法时，最让你卡住的是什么？',
    '开始这个方法时，最让你不知道怎么办的是什么？',
])
@pytest.mark.parametrize('text', [
    '第一个方法还没试，最担心的就是停不下来刷手机',
    '第一个方法还没试，最难的是不知道怎么开始',
])
def test_new_live_repetition_wordings_are_blocked(question, text):
    assert question_problem(question, text, SimpleNamespace(messages=[], suggestions=[]))


@pytest.mark.parametrize('question', ['开始第一个方法时，你最担心遇到什么困难？', '这件事让你此刻最在意的是什么？'])
@pytest.mark.parametrize('text', ['第一个方法我并不是不想用，只是还没有时间试', '最难的是不知道怎么开始'])
def test_known_barrier_cannot_be_reasked_as_generic_priority(question, text):
    assert question_problem(question, text, SimpleNamespace(messages=[], suggestions=[]))


def test_denied_time_barrier_and_distinct_detail_are_not_blocked():
    previous = SimpleNamespace(messages=[], suggestions=[])
    assert question_problem('开始之前有什么困难？', '并不是没有时间试', previous) is None
    assert question_problem('哪一段文字没有看明白？', '最难的是不知道怎么开始', previous) is None


def test_known_barrier_fallback_pauses_instead_of_asking_generic_priority(support):
    sid, _, _, _ = support
    hid = start(sid).json()['healing_id']
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    model = QuestionClient()
    model.question = '这件事让你此刻最在意的是什么？'
    healing.healing_agent.client = model
    assert chat(sid, hid, '最难的是不知道怎么开始').status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.status == 'paused' and state.suggestions == before.suggestions
    assert not state.feedback and '？' not in state.messages[-1].content


@pytest.mark.parametrize('text', ['不清楚', '不知道说什么'])
def test_unknown_answer_after_pause_stays_brief_and_model_free(support, text):
    sid, _, _, fake = support
    hid = start(sid).json()['healing_id']
    assert chat(sid, hid, '先暂停').status_code == 200
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.fail = True
    assert chat(sid, hid, text).status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.status == 'paused' and state.suggestions == before.suggestions
    assert state.feedback == before.feedback and '？' not in state.messages[-1].content
    assert '不清楚' in state.messages[-1].content if text == '不清楚' else '怎么说' in state.messages[-1].content


def test_consecutive_unknown_synonyms_pause_but_concrete_answer_does_not():
    messages = [HealingMessage(role='user', content='不清楚')]
    assert repeated_answer('不知道说什么', messages)
    assert not repeated_answer('不知道怎么开始这个方法', messages)
    assert not repeated_answer('不清楚', [HealingMessage(role='user', content='还没有时间试')])


@pytest.mark.parametrize('text', [
    '就是刷手机，已经说过了，我也不知道还能补充什么',
    '之前说清楚了，没有什么可补充',
])
def test_explicitly_exhausted_answer_does_not_prompt_again(text):
    previous = SimpleNamespace(messages=[], suggestions=[])
    assert question_problem('刷手机的时候，有没有哪一刻你想停下来？', text, previous)
    assert question_problem(None, text, previous) is None
    assert question_problem('考试前，你最担心什么？', text, previous, goal_changed=True) is None


@pytest.mark.parametrize('text,question', [
    ('我并不是已经说过了，我也不知道还能补充什么', '手机通常在什么时候吸引你的注意？'),
    ('我已经说过了，但不是不知道还能补充什么', '手机通常在什么时候吸引你的注意？'),
    ('最难的是不知道', '开始之前有什么困难？'),
])
def test_denied_exhaustion_and_unknown_difficulty_remain_open(text, question):
    assert question_problem(question, text, SimpleNamespace(messages=[], suggestions=[])) is None


def test_exhausted_answer_pauses_without_losing_method_or_inventing_feedback(support):
    sid, _, _, _ = support
    hid = start(sid).json()['healing_id']
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    healing.healing_agent.client = QuestionClient()
    response = chat(sid, hid, '就是刷手机，已经说过了，我也不知道还能补充什么')
    assert response.status_code == 200
    current = healing.healing_store.slot(sid).state
    assert current.status == 'paused' and current.suggestions == before.suggestions
    assert not current.feedback and '？' not in current.messages[-1].content


@pytest.mark.parametrize('text,prepared', [('第一个方法我准备试试', True), ('先暂停', False)])
def test_pause_copy_distinguishes_readiness_from_plain_pause(support, text, prepared):
    sid, _, _, _ = support
    hid = start(sid).json()['healing_id']
    response = chat(sid, hid, text)
    assert response.status_code == 200
    state = healing.healing_store.slot(sid).state
    assert state.status == 'paused'
    assert ('你准备试试了' in state.messages[-1].content) == prepared
    assert all(item.execution != 'attempted' for item in state.suggestions)
    assert all(item.effect == 'unknown' for item in state.suggestions)


@pytest.mark.parametrize('failure', ['question_only', 'final_check', 'transport'])
def test_program_added_clarification_uses_checked_pause_or_rolls_back(support, failure):
    sid, _, _, fake = support
    fake.recommendations = ['name-concern', 'other']
    hid = start(sid).json()['healing_id']
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)

    class RejectClarification(QuestionClient):
        async def generate(self, system, payload, schema, **kwargs):
            if schema is NarrativeCheck and payload['question'] == '你说的是刚才哪一个方法？':
                if failure == 'transport':
                    raise HealingUnavailable('synthetic transport failure')
                return NarrativeCheck(valid=False, issues=['unnecessary_clarification'])
            if schema is NarrativeCheck and payload['question'] is None and failure == 'final_check':
                return NarrativeCheck(valid=False, issues=['unsupported_fact'])
            return await super().generate(system, payload, schema, **kwargs)

    model = RejectClarification()
    model.feedback = [Feedback(suggestion_id=before.suggestions[0].suggestion_id,
                              execution='attempted', evidence='我试了')]
    healing.healing_agent.client = model
    response = chat(sid, hid, '我试了')
    current = healing.healing_store.slot(sid).state
    if failure == 'question_only':
        assert response.status_code == 200 and current.status == 'paused'
        assert current.suggestions == before.suggestions and not current.feedback
        assert '？' not in current.messages[-1].content
    else:
        assert response.status_code == 503 and current == before


@pytest.mark.parametrize("question", [
    "开始这个方法时，最担心遇到什么困难？", "开始之前，你最担心遇到什么困难？",
    "准备尝试的时候，有什么顾虑？",
])
@pytest.mark.parametrize("text", ["最担心的就是停不下来刷手机", "我已经说过了，停不下来刷手机"])
def test_answered_difficulty_cannot_be_reasked(question, text):
    previous = SimpleNamespace(messages=[], suggestions=[])
    assert question_problem(question, text, previous)


@pytest.mark.parametrize("text,question", [
    ("不知道", "开始前有什么困难？"),
    ("最担心的是不知道", "开始前有什么困难？"),
    ("并不是最担心刷手机", "开始前有什么困难？"),
    ("最担心停不下来刷手机", "这次尝试中哪一步最难？"),
    ("最担心停不下来刷手机", "手机通常在什么时候吸引你的注意？"),
])
def test_unknown_denial_and_new_detail_remain_allowed(text, question):
    assert question_problem(question, text, SimpleNamespace(messages=[], suggestions=[])) is None


def test_answered_slot_survives_wording_change_but_new_goal_is_allowed():
    previous = SimpleNamespace(suggestions=[], messages=[
        HealingMessage(role="assistant", content="开始前有什么困难？"),
        HealingMessage(role="user", content="最担心停不下来刷手机"),
    ])
    assert question_problem("开始之前有什么顾虑？", "我已经说过了", previous)
    assert question_problem("开始之前有什么顾虑？", "想换成考试压力", previous, goal_changed=True) is None


class QuestionClient(FakeClient):
    question = "开始之前，你最担心遇到什么困难？"
    checked = []

    async def generate(self, system, payload, schema, **kwargs):
        if schema is NarrativeCheck:
            self.checked.append(payload)
        result = await super().generate(system, payload, schema, **kwargs)
        if schema is AgentDraft and payload['phase'] == 'follow_up':
            result.question = self.question
        return result


def test_repeated_semantic_question_is_repaired_or_safely_paused(support):
    sid, _, _, _ = support
    hid = start(sid).json()['healing_id']
    model = QuestionClient()
    healing.healing_agent.client = model
    response = chat(sid, hid, "最担心的就是停不下来刷手机")
    assert response.status_code == 200
    state = healing.healing_store.slot(sid).state
    assert model.question not in state.messages[-1].content
    assert not state.feedback and state.suggestions[0].execution == 'unconfirmed'


@pytest.mark.parametrize("text", [
    "第一个方法我并不是不想用，只是还没有时间试",
    "第一个方法太复杂，换简单一点；第二个方法看得懂，不用改",
    "说出考试困扰我并不是不想用，只是还没有时间试",
])
def test_rejected_model_feedback_does_not_force_resolved_method_clarification(support, text):
    sid, _, _, fake = support
    fake.recommendations = ['name-concern', 'other']
    hid = start(sid).json()['healing_id']
    state = healing.healing_store.slot(sid).state
    fake.recommendations = []
    fake.feedback = [Feedback(suggestion_id=state.suggestions[0].suggestion_id,
                             execution='declined', evidence='不想用' if '不想用' in text else '不用')]
    if '太复杂' in text:
        # The synthetic method has no simple wording; the association alone
        # must still prevent a spurious request to identify the method.
        fake.simplify_id = state.suggestions[0].suggestion_id
    response = chat(sid, hid, text)
    assert response.status_code == 200
    current = healing.healing_store.slot(sid).state
    assert '你说的是刚才哪一个方法' not in current.messages[-1].content
    assert current.suggestions[0].execution != 'declined'


def test_generated_unnecessary_clarification_is_also_checked(support):
    sid, _, _, fake = support
    fake.recommendations = ['name-concern', 'other']
    hid = start(sid).json()['healing_id']
    model = QuestionClient()
    model.question = '你说的是刚才哪一个方法？'
    healing.healing_agent.client = model
    response = chat(sid, hid, '第一个方法我并不是不想用，只是还没时间试')
    assert response.status_code == 200
    assert model.question not in healing.healing_store.slot(sid).state.messages[-1].content


def test_truly_ambiguous_feedback_is_clarified_and_final_text_rechecked(support):
    sid, _, _, fake = support
    fake.recommendations = ['name-concern', 'other']
    hid = start(sid).json()['healing_id']
    state = healing.healing_store.slot(sid).state
    model = QuestionClient()
    model.checked = []
    model.feedback = [Feedback(suggestion_id=state.suggestions[0].suggestion_id, execution='attempted', evidence='我试了')]
    healing.healing_agent.client = model
    response = chat(sid, hid, '我试了')
    assert response.status_code == 200
    current = healing.healing_store.slot(sid).state
    assert '你说的是刚才哪一个方法？' in current.messages[-1].content
    assert model.checked[-1]['question'] == '你说的是刚才哪一个方法？'
    assert not current.feedback


def test_program_added_clarification_replaces_second_focus_question(support):
    sid, _, _, fake = support
    fake.recommendations = ['name-concern', 'other']
    hid = start(sid).json()['healing_id']
    state = healing.healing_store.slot(sid).state

    class HiddenQuestionClient(QuestionClient):
        async def generate(self, system, payload, schema, **kwargs):
            result = await super().generate(system, payload, schema, **kwargs)
            if schema is AgentDraft:
                result.focus = '心里有什么顾虑或难处'
            return result

    model = HiddenQuestionClient()
    model.feedback = [Feedback(suggestion_id=state.suggestions[0].suggestion_id, execution='attempted', evidence='我试了')]
    healing.healing_agent.client = model
    assert chat(sid, hid, '我试了').status_code == 200
    content = healing.healing_store.slot(sid).state.messages[-1].content
    assert '你说的是刚才哪一个方法？' in content and '心里有什么顾虑或难处' not in content


@pytest.mark.parametrize('text,unresolved', [
    ('第一个方法我试了，第二个方法我试了', False),
    ('我试了', True), ('第3个方法我试了', True),
])
def test_local_references_determine_ambiguity(text, unresolved):
    references = [SimpleNamespace(active=True, suggestion_id=f's{i}', title=f'标题{i}') for i in [1, 2]]
    assert unresolved_feedback(text, references) is unresolved


def test_rejected_question_can_fall_back_to_checked_questionless_pause(support):
    sid, _, _, fake = support
    fake.recommendations = ['name-concern', 'other']
    hid = start(sid).json()['healing_id']
    class RejectQuestions(QuestionClient):
        async def generate(self, system, payload, schema, **kwargs):
            if schema is NarrativeCheck:
                return NarrativeCheck(valid=payload['question'] is None,
                    issues=['multiple_questions'] if payload['question'] else [])
            result = await super().generate(system, payload, schema, **kwargs)
            if schema is AgentDraft:
                result.question = '这两个方法里，你想先从哪一个开始试试？'
            return result
    healing.healing_agent.client = RejectQuestions()
    response = chat(sid, hid, '第一个方法看得懂，不用改；第二个方法也看得懂')
    assert response.status_code == 200
    current = healing.healing_store.slot(sid).state
    assert current.status == 'paused' and len(current.suggestions) == 2
    assert '？' not in current.messages[-1].content and not current.feedback


def test_transport_failure_still_rolls_back_instead_of_bypassing_validation(support):
    sid, _, _, fake = support
    hid = start(sid).json()['healing_id']
    before = healing.healing_store.slot(sid).state.model_copy(deep=True)
    fake.fail = True
    assert chat(sid, hid, '第一个方法看得懂，不用改').status_code == 503
    assert healing.healing_store.slot(sid).state == before


@pytest.mark.parametrize('query', ['和同学意见不一致', '我和朋友意见不同', '与同学观点不一致'])
@pytest.mark.parametrize('age', [6, 10, 12])
def test_child_disagreement_recalls_verified_student_methods(query, age):
    hits = HealingRetriever(load_knowledge()).retrieve(query, 'relationships',
        HealingBackground(age=age, school_stage='primary', adult_support_available=False))
    assert hits and any(hit.item.knowledge_id == 'heal-5299f7fdbfe2' for hit in hits)
    assert all(hit.item.executor == 'student' and hit.item.status == 'usable' for hit in hits)


def test_synonym_bridge_keeps_unknown_age_exclusion_and_method_filters():
    retriever = HealingRetriever(load_knowledge())
    assert not retriever.retrieve('和同学意见不一致', 'relationships', HealingBackground())
    background = HealingBackground(age=10, adult_support_available=False)
    first = retriever.retrieve('和同学意见不一致', 'relationships', background)
    excluded = {hit.item.method_key for hit in first}
    second = retriever.retrieve('和同学意见不一致', 'relationships', background, excluded)
    assert all(hit.item.method_key not in excluded for hit in second)


@pytest.mark.parametrize('action', ['local_simplification', 'negated_simplification', 'different_feedback', 'prepare_pause_resume'])
def test_four_boundaries_with_stable_real_two_method_precondition(support, action):
    sid, _, store, fake = support
    records_before = store.list_by_student(healing.session_manager.get_session(sid).student_ref)
    replay = json.loads((Path(__file__).parents[1] / 'docs/examples/healing_feedback_acceptance_20261006.json').read_text(encoding='utf-8'))
    original = next(case for case in replay['current_first_run'] if case['case']['id'] == 'specific-context-negated-simplification')
    state = HealingState.model_validate(original['final_state'])
    state.memory.session_id = sid
    assert len(state.suggestions) == 2 and all(item.active for item in state.suggestions)
    healing.healing_store.slot(sid).state = state
    healing.healing_agent.retriever = HealingRetriever(load_knowledge())
    fake.recommendations = []
    first, second = state.suggestions
    if action == 'local_simplification':
        fake.simplify_id = first.suggestion_id
        text = '第一个方法太复杂，换简单一点；第二个方法看得懂，不用改'
    elif action == 'negated_simplification':
        fake.simplify_id = first.suggestion_id  # Incorrect model request must be blocked.
        text = '第一个方法并不复杂，先别改；第二个方法也看得懂，不用改'
    elif action == 'different_feedback':
        text = '第一个方法我试了，没有帮助；第二个方法我试了，有帮助'
        fake.feedback = [Feedback(suggestion_id=first.suggestion_id, execution='attempted', effect='ineffective', evidence='第一个方法我试了，没有帮助'),
                         Feedback(suggestion_id=second.suggestion_id, execution='attempted', effect='helpful', evidence='第二个方法我试了，有帮助')]
    else:
        assert chat(sid, state.healing_id, '第二个方法我准备试试，先暂停').status_code == 200
        text = '第二个方法还没试'
        fake.feedback = [Feedback(suggestion_id=second.suggestion_id, execution='prepared', evidence=text)]
    response = chat(sid, state.healing_id, text, 'stable-boundary')
    assert response.status_code == 200
    current = healing.healing_store.slot(sid).state
    assert len(current.suggestions) == 2
    assert [item.suggestion_id for item in current.suggestions] == [first.suggestion_id, second.suggestion_id]
    assert current.suggestions[1].steps == second.steps
    if action == 'local_simplification':
        assert current.suggestions[0].revisions and not current.suggestions[1].revisions
        assert '你说的是刚才哪一个方法' not in current.messages[-1].content
    elif action == 'negated_simplification':
        assert not any(item.revisions for item in current.suggestions) and not current.feedback
    elif action == 'different_feedback':
        assert [item.effect for item in current.suggestions] == ['ineffective', 'helpful']
        assert [item.active for item in current.suggestions] == [False, True]
    else:
        assert current.suggestions[1].execution == 'prepared'
        assert any(item.execution == 'not_attempted' and item.suggestion_id == second.suggestion_id for item in current.feedback)
    assert chat(sid, state.healing_id, text, 'stable-boundary').json() == response.json()
    assert store.list_by_student(healing.session_manager.get_session(sid).student_ref) == records_before
