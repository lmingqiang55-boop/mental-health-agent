# -*- coding: utf-8 -*-
"""检查新版提示词的数据分区、信息传递、收尾及表达约定，不调用模型。"""

from backend.prompts.dialogue_prompt import (
    DIALOGUE_AGENT_SYSTEM_PROMPT,
    REFUSAL_PHRASES,
    build_dialogue_user_prompt,
    is_refusal,
)
from backend.models.dialogue import (
    DialogueAgentRequest,
    DialogueCurrentUserInput,
    DialogueDecision,
    DialogueHistoryMessage,
    DialogueUserMemory,
    DialogueVisual,
)


def make_request(text: str, *, finish: bool = False) -> DialogueAgentRequest:
    return DialogueAgentRequest(
        conversation_history=[DialogueHistoryMessage(role="assistant", content="你好呀")],
        decision=DialogueDecision(target_item='sleep_disturbance', question_goal='了解过去两周该项表现及尚缺的信息'),
        current_user_input=DialogueCurrentUserInput(text=text),
        finish_screening=finish,
    )


def requirement(text: str, *, finish: bool = False) -> str:
    """取出新版动态提示词的任务区。"""
    prompt = build_dialogue_user_prompt(make_request(text, finish=finish))
    return prompt.split("【任务】\n", 1)[1]


# ---------------------------------------------------------------------------
# 1. 拒绝识别
# ---------------------------------------------------------------------------

def test_obvious_refusals_are_detected() -> None:
    for text in ("我不想说", "我不愿意说", "我不想聊这个了", "别问了",
                 "这个不方便说", "我们换个话题吧", "没什么可说的"):
        assert is_refusal(text), f"没识别出拒绝：{text}"


def test_ordinary_short_answers_are_not_refusals() -> None:
    """普通短答不能被误判成拒绝，否则评估会推不动。"""
    for text in ("是", "没有", "每天", "一个月", "还好", "有时候", "三次左右"):
        assert not is_refusal(text), f"误判为拒绝：{text}"


def test_refusal_instruction_does_not_depend_on_answer_length() -> None:
    text = requirement("我不想说")
    assert "明确拒绝时只接纳，不追问" in text
    assert "这句较短" not in text


def test_short_answer_still_advances_when_it_is_not_a_refusal() -> None:
    text = requirement("每天")
    assert "正常回答可以直接追问" in text
    assert "不添加机械共情" in text


def test_task_is_not_reclassified_by_short_text_or_emotion_words() -> None:
    expected = requirement("每天")
    for text in ("我最近真的好累。", "你觉得呢？", "我该怎么办？", "我不想说", "不太清楚"):
        assert requirement(text) == expected


def test_new_template_passes_history_memory_goal_and_current_text_once() -> None:
    request = make_request("一周三四晚")
    request.conversation_history.insert(0, DialogueHistoryMessage(
        role="user", content="最近两周睡不好", visual=DialogueVisual(valence=-0.8)))
    request.current_user_input.visual = DialogueVisual(valence=-0.6)
    request.user_memory = DialogueUserMemory(facts=["学生读初中"])
    request.decision.question_goal = "了解入睡困难时大概多久才能睡着"
    prompt = build_dialogue_user_prompt(request)
    headings = ("【历史对话】", "【用户记忆】", "【学生最新回复】", "【本轮评估目标】",
                "【本轮视觉观察】", "【结束状态】", "【任务】")
    positions = [prompt.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert prompt.count("一周三四晚") == 1
    assert "最近两周睡不好" in prompt and "学生读初中" in prompt
    assert "question_goal: 了解入睡困难时大概多久才能睡着" in prompt
    assert "finish_screening: false" in prompt
    assert "valence=" not in prompt
    assert "本轮没有可口头提及的视觉观察" in prompt


def test_finish_screening_still_asks_nothing() -> None:
    """收尾轮优先级最高：不提问，也不被拒绝分支改写。"""
    text = requirement("我不想说", finish=True)
    assert "不提出任何问题" in text


# ---------------------------------------------------------------------------
# 2. 提示词允许"一个问题都不问"
# ---------------------------------------------------------------------------

def test_system_prompt_allows_a_turn_without_any_question() -> None:
    assert "可以不提问" in DIALOGUE_AGENT_SYSTEM_PROMPT
    assert "明确拒绝时，本轮不再追问" in DIALOGUE_AGENT_SYSTEM_PROMPT


def test_system_prompt_no_longer_mandates_a_question_every_turn() -> None:
    """旧的"默认每一轮只提出一个主要问题"正是机械提问的来源，必须已经改掉。"""
    assert "默认每一轮只提出一个主要问题" not in DIALOGUE_AGENT_SYSTEM_PROMPT
    assert "每轮最多提出一个主要问题" in DIALOGUE_AGENT_SYSTEM_PROMPT


def test_bubble_rule_is_structural_not_by_sentence_length() -> None:
    """分段按表达单元走：回应 + 追问两个单元必须拆成 2 条。"""
    assert "同时需要回应和追问时，拆成两条" in DIALOGUE_AGENT_SYSTEM_PROMPT
    assert "“一个问题”限制的是询问目标，不是聊天气泡的数量" in DIALOGUE_AGENT_SYSTEM_PROMPT
    assert "视觉观察后追问也拆成两条" in DIALOGUE_AGENT_SYSTEM_PROMPT
    assert "不为凑条数添加安慰、复述或过渡" in DIALOGUE_AGENT_SYSTEM_PROMPT


def test_refusal_vocabulary_is_not_empty_and_is_documented() -> None:
    assert len(REFUSAL_PHRASES) >= 10
    assert all(phrase == phrase.strip() and phrase for phrase in REFUSAL_PHRASES)
