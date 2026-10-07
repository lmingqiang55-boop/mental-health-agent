"""Feedback evidence must retain its own method reference within a mixed answer."""

from types import SimpleNamespace

import pytest

from backend.healing.agent import HealingAgent
from backend.models.healing import Feedback, Suggestion


@pytest.fixture
def feedback_state():
    suggestions = [Suggestion(
        suggestion_id=f"s{index}", knowledge_id=f"k{index}", method_key=f"m{index}",
        title=title, goal="合成目标", steps=["合成步骤"], prerequisites=[], cautions=[],
        proposed_turn=0,
    ) for index, title in enumerate(["记录感受", "拆分任务"], 1)]
    return SimpleNamespace(suggestions=suggestions, turn_count=1, feedback=[],
                           memory_update_suggestions=[])


@pytest.mark.parametrize("first,second", [
    ("第一个方法我试了，有帮助", "第二个方法我试了，没有帮助"),
    ("第1条建议我试了，有帮助", "第2条建议我试了，没有帮助"),
    ("记录感受我试了，有帮助", "拆分任务我试了，没有帮助"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_two_method_effects_bind_each_quote_independently(feedback_state, first, second, reverse):
    text = "；".join([second, first] if reverse else [first, second])
    proposals = [
        Feedback(suggestion_id="s1", execution="attempted", effect="helpful", evidence=first),
        Feedback(suggestion_id="s2", execution="attempted", effect="ineffective", evidence=second),
    ]
    accepted = HealingAgent.apply_feedback(feedback_state, proposals, text)
    assert [item.suggestion_id for item in accepted] == ["s1", "s2"]
    assert [(item.execution, item.effect, item.active) for item in feedback_state.suggestions] == [
        ("attempted", "helpful", True), ("attempted", "ineffective", False)]
    assert len(feedback_state.memory_update_suggestions) == 2


@pytest.mark.parametrize("target,evidence", [
    ("s1", "第二个方法我试了，没有帮助"),
    ("s2", "第一个方法我试了，有帮助"),
    ("s1", "拆分任务我试了，没有帮助"),
    ("s2", "记录感受我试了，有帮助"),
])
def test_another_methods_quote_cannot_update_target(feedback_state, target, evidence):
    text = evidence + "；" + ("记录感受我试了，有帮助" if target == "s1"
                             else "拆分任务我试了，没有帮助")
    proposal = Feedback(suggestion_id=target, execution="attempted", evidence=evidence)
    assert HealingAgent.apply_feedback(feedback_state, [proposal], text) == []
    assert all(item.execution == "unconfirmed" and item.active for item in feedback_state.suggestions)
    assert not feedback_state.feedback and not feedback_state.memory_update_suggestions


def test_two_attempts_with_distinct_execution_states(feedback_state):
    text = "第一个方法我试过了，第二个方法我还没有试过"
    proposals = [
        Feedback(suggestion_id="s1", execution="attempted", evidence="第一个方法我试过了"),
        Feedback(suggestion_id="s2", execution="not_attempted", evidence="第二个方法我还没有试过"),
    ]
    assert len(HealingAgent.apply_feedback(feedback_state, proposals, text)) == 2
    assert [item.execution for item in feedback_state.suggestions] == ["attempted", "not_attempted"]


@pytest.mark.parametrize("evidence", ["我试了，有帮助", "有帮助"])
def test_short_quote_uses_its_original_local_reference(feedback_state, evidence):
    text = "第一个方法还没试，第二个方法，我试了，有帮助"
    feedback_state.suggestions[1].execution = "attempted"
    proposal = Feedback(suggestion_id="s2", execution="attempted", effect="helpful", evidence=evidence)
    assert HealingAgent.apply_feedback(feedback_state, [proposal], text)
    assert feedback_state.suggestions[0].execution == "unconfirmed"
    assert feedback_state.suggestions[1].effect == "helpful"


@pytest.mark.parametrize("target", ["s1", "s2"])
@pytest.mark.parametrize("evidence", ["我试了", "第一个方法我试了，有帮助；第二个方法我试了，没有帮助"])
def test_ambiguous_or_cross_method_quote_is_not_assigned(feedback_state, target, evidence):
    text = "第一个方法我试了，有帮助；第二个方法我试了，没有帮助"
    proposal = Feedback(suggestion_id=target, execution="attempted", evidence=evidence)
    assert HealingAgent.apply_feedback(feedback_state, [proposal], text) == []
    assert not feedback_state.feedback


@pytest.mark.parametrize("text", [
    "两个方法我都试了，没有帮助",
    "全部方法都试了，没有帮助",
    "第一个和第二个方法都试了，没有帮助",
])
def test_explicit_shared_feedback_can_update_both_methods(feedback_state, text):
    proposals = [Feedback(suggestion_id=f"s{index}", execution="attempted",
                          effect="ineffective", evidence=text) for index in [1, 2]]
    assert len(HealingAgent.apply_feedback(feedback_state, proposals, text)) == 2
    assert all(item.effect == "ineffective" and not item.active for item in feedback_state.suggestions)


def test_earlier_collective_attempt_does_not_spread_later_individual_effect(feedback_state):
    text = "两个方法都试了；第一个方法有帮助，第二个方法没有帮助"
    for item in feedback_state.suggestions:
        item.execution = "attempted"
    wrong = Feedback(suggestion_id="s1", execution="attempted", effect="ineffective",
                     evidence="第二个方法没有帮助")
    assert HealingAgent.apply_feedback(feedback_state, [wrong], text) == []
    right = wrong.model_copy(update={"suggestion_id": "s2"})
    assert HealingAgent.apply_feedback(feedback_state, [right], text)
    assert feedback_state.suggestions[0].effect == "unknown"


def test_single_survivor_keeps_original_same_turn_ordinals(feedback_state):
    references = [item.model_copy(deep=True) for item in feedback_state.suggestions]
    feedback_state.suggestions[0].active = False
    text = "第一个方法我还没有试过；第二个方法我试了，有帮助"
    proposal = Feedback(suggestion_id="s2", execution="attempted", effect="helpful",
                        evidence="第二个方法我试了，有帮助")
    assert HealingAgent.apply_feedback(feedback_state, [proposal], text, references)
    assert feedback_state.suggestions[0].execution == "unconfirmed"
    assert feedback_state.suggestions[1].effect == "helpful"


@pytest.mark.parametrize("text", ["第三个方法我试了", "第一个和第二个方法我试了", "我试了"])
def test_unresolved_reference_does_not_default_to_first_method(feedback_state, text):
    proposal = Feedback(suggestion_id="s1", execution="attempted", evidence=text)
    assert HealingAgent.apply_feedback(feedback_state, [proposal], text) == []


def test_first_feedback_deactivation_does_not_renumber_second(feedback_state):
    text = "第一个方法我不想用了，第二个方法我试了，有帮助"
    proposals = [
        Feedback(suggestion_id="s1", execution="declined", evidence="第一个方法我不想用了"),
        Feedback(suggestion_id="s2", execution="attempted", effect="helpful", evidence="第二个方法我试了，有帮助"),
    ]
    assert len(HealingAgent.apply_feedback(feedback_state, proposals, text)) == 2
    assert [(item.execution, item.active) for item in feedback_state.suggestions] == [
        ("declined", False), ("attempted", True)]


def test_local_all_word_does_not_override_an_individual_reference(feedback_state):
    text = "第一个方法，我都试了"
    wrong = Feedback(suggestion_id="s2", execution="attempted", evidence="我都试了")
    assert HealingAgent.apply_feedback(feedback_state, [wrong], text) == []
    right = wrong.model_copy(update={"suggestion_id": "s1"})
    assert HealingAgent.apply_feedback(feedback_state, [right], text)


@pytest.mark.parametrize("text,evidence", [
    ("第一个方法我试了，有帮助第二个方法我试了，没有帮助", "第二个方法我试了，没有帮助"),
    ("我试了第二个方法，没有帮助", "我试了第二个方法，没有帮助"),
])
def test_reference_before_or_after_action_stays_local(feedback_state, text, evidence):
    proposal = Feedback(suggestion_id="s2", execution="attempted", effect="ineffective", evidence=evidence)
    assert HealingAgent.apply_feedback(feedback_state, [proposal], text)
    assert feedback_state.suggestions[0].execution == "unconfirmed"
    assert not feedback_state.suggestions[1].active


@pytest.mark.parametrize("model_execution", [None, "prepared", "not_attempted"])
def test_prepared_intention_keeps_new_not_attempted_feedback(feedback_state, model_execution):
    feedback_state.suggestions[1].execution = "prepared"
    text = "我们继续聊考试压力，第二个方法还没试"
    proposals = [] if model_execution is None else [Feedback(
        suggestion_id="s2", execution=model_execution, evidence="第二个方法还没试")]
    accepted = HealingAgent.apply_feedback(feedback_state, proposals, text)
    assert [(item.suggestion_id, item.execution, item.effect, item.turn) for item in accepted] == [
        ("s2", "not_attempted", "unknown", 1)]
    assert [item.execution for item in feedback_state.suggestions] == ["unconfirmed", "prepared"]
    assert accepted[0].evidence in text
    assert len(feedback_state.feedback) == len(feedback_state.memory_update_suggestions) == 1
    assert feedback_state.memory_update_suggestions[0]["value"] == accepted[0].model_dump(mode="json")
    assert feedback_state.memory_update_suggestions[0]["persisted"] is False


@pytest.mark.parametrize("text,targets", [
    ("第一个方法还没试，第二个方法已经试了", ["s1"]),
    ("第一个方法已经试了，第二个方法还没试", ["s2"]),
    ("记录感受我还没有试过", ["s1"]),
    ("两个方法都还没试", ["s1", "s2"]),
    ("第一个方法，还没试；第二个方法，还没试", ["s1", "s2"]),
    ("第二个方法之前没试，但今天试了", []),
    ("第二个方法还没试，但刚才说错了，并不是还没试", []),
    ("第二个方法不是没有试过", []),
    ("第二个方法没有用", []),
    ("第三个方法还没试", []),
    ("第一个和第二个方法还没试", []),
    ("还没试", []),
])
def test_prepared_absence_uses_local_references_and_latest_polarity(feedback_state, text, targets):
    for item in feedback_state.suggestions:
        item.execution = "prepared"
    accepted = HealingAgent.apply_feedback(feedback_state, [], text)
    assert [item.suggestion_id for item in accepted] == targets
    assert all(item.execution == "not_attempted" and item.evidence in text for item in accepted)
    assert all(item.execution == "prepared" and item.effect == "unknown" for item in feedback_state.suggestions)


@pytest.mark.parametrize("execution,effect,text", [
    ("attempted", "helpful", "第二个方法我试了，有帮助"),
    ("declined", "unknown", "第二个方法我不想用了"),
])
def test_prepared_intention_yields_to_real_attempt_or_decline(feedback_state, execution, effect, text):
    feedback_state.suggestions[1].execution = "prepared"
    proposal = Feedback(suggestion_id="s2", execution=execution, effect=effect, evidence=text)
    assert len(HealingAgent.apply_feedback(feedback_state, [proposal], text)) == 1
    target = feedback_state.suggestions[1]
    assert (target.execution, target.effect, target.active) == (execution, effect, execution != "declined")


def test_not_attempted_quote_cannot_override_later_affirmed_attempt(feedback_state):
    feedback_state.suggestions[1].execution = "prepared"
    text = "第二个方法之前还没试，但今天试了"
    proposal = Feedback(suggestion_id="s2", execution="not_attempted", evidence="第二个方法之前还没试")
    assert HealingAgent.apply_feedback(feedback_state, [proposal], text) == []
    assert not feedback_state.feedback


def test_prepared_feedback_keeps_pre_filter_method_ordinals(feedback_state):
    feedback_state.suggestions[1].execution = "prepared"
    references = [item.model_copy(deep=True) for item in feedback_state.suggestions]
    feedback_state.suggestions[0].active = False
    accepted = HealingAgent.apply_feedback(feedback_state, [], "第二个方法还没试", references)
    assert [(item.suggestion_id, item.execution) for item in accepted] == [("s2", "not_attempted")]
    assert feedback_state.suggestions[1].execution == "prepared"


def test_single_prepared_method_accepts_unqualified_not_attempted(feedback_state):
    feedback_state.suggestions = feedback_state.suggestions[:1]
    feedback_state.suggestions[0].execution = "prepared"
    accepted = HealingAgent.apply_feedback(feedback_state, [], "还没试")
    assert [(item.suggestion_id, item.execution) for item in accepted] == [("s1", "not_attempted")]
    assert feedback_state.suggestions[0].execution == "prepared"


def test_short_absence_quote_retains_original_polarity(feedback_state):
    text = "第二个方法还没试"
    proposal = Feedback(suggestion_id="s2", execution="not_attempted", evidence="没试")
    accepted = HealingAgent.apply_feedback(feedback_state, [proposal], text)
    assert len(accepted) == 1 and feedback_state.suggestions[1].execution == "not_attempted"


@pytest.mark.parametrize("text,evidence,accepted", [
    ("第一个方法我并不是不想用，只是还没时间试", "不想用", False),
    ("第一个方法我不是不愿意用", "不愿意", False),
    ("第一个方法我并非不喜欢", "不喜欢", False),
    ("第一个方法我没有拒绝", "拒绝", False),
    ("第一个方法我不想用了", "不想用", True),
    ("第一个方法我不愿意用", "不愿意", True),
    ("第一个方法我不喜欢", "不喜欢", True),
    ("第一个方法我拒绝", "拒绝", True),
    ("第一个方法我不想用，但刚才说错了，并不是不想用", "第一个方法我不想用，但刚才说错了，并不是不想用", False),
    ("第一个方法我不是不想用，但现在不想用了", "第一个方法我不是不想用，但现在不想用了", True),
])
def test_decline_quote_preserves_original_negation_and_correction(feedback_state, text, evidence, accepted):
    proposal = Feedback(suggestion_id="s1", execution="declined", evidence=evidence)
    result = HealingAgent.apply_feedback(feedback_state, [proposal], text)
    assert bool(result) is accepted
    assert feedback_state.suggestions[0].active is (not accepted)
    assert feedback_state.suggestions[0].execution == ("declined" if accepted else "unconfirmed")
    assert feedback_state.suggestions[1].active


def test_negated_decline_for_first_method_does_not_block_second(feedback_state):
    text = "第一个方法我不是不想用；第二个方法我不想用了"
    proposals = [
        Feedback(suggestion_id="s1", execution="declined", evidence="第一个方法我不是不想用"),
        Feedback(suggestion_id="s2", execution="declined", evidence="第二个方法我不想用了"),
    ]
    result = HealingAgent.apply_feedback(feedback_state, proposals, text)
    assert [item.suggestion_id for item in result] == ["s2"]
    assert [item.active for item in feedback_state.suggestions] == [True, False]
