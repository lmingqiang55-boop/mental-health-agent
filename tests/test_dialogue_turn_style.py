# -*- coding: utf-8 -*-
"""Dialogue「每轮都要提问」的回归保护。

背景：评审实测时反馈"AI 每一轮都在问问题，像问卷"。根因不在 LangGraph，
而在 System Prompt 把所有轮次都写成了"承接 + 追问"，并且"简短回答 → 直接推进"
这一档会把"我不想说"这种 5 个字的拒绝也当成"简短回答"去催答。

这里锁定三件事：
1. 拒绝必须优先于"简短回答"被识别，本轮不要追问；
2. 提示词明确允许**一个问题都不问**（纯共情 / 回应 / 建议 / 尊重拒绝）；
3. 气泡条数按"表达单元"决定：回应与追问是两个单元就必须拆成 2 条。

注意：这些是**提示词契约**测试，不调用模型；真实模型上的效果由实机验收覆盖。
"""

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
)


def make_request(text: str, *, finish: bool = False) -> DialogueAgentRequest:
    return DialogueAgentRequest(
        conversation_history=[DialogueHistoryMessage(role="assistant", content="你好呀")],
        decision=DialogueDecision(actions=["共情安慰", "睡眠"], topic="睡眠"),
        current_user_input=DialogueCurrentUserInput(text=text),
        finish_screening=finish,
    )


def requirement(text: str, *, finish: bool = False) -> str:
    """取出【本轮表达要求】那一节（避免和其他分区的同名字样混淆）。"""
    prompt = build_dialogue_user_prompt(make_request(text, finish=finish))
    section = prompt.split("【本轮表达要求】\n", 1)[1]
    return section.split("\n\n", 1)[0]


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


def test_refusal_wins_over_the_short_answer_rule() -> None:
    """‘我不想说’只有 5 个字，但必须走拒绝分支，而不是被催着回答。"""
    text = requirement("我不想说")
    assert "不要追问" in text
    assert "先接纳" in text
    # 不能落进"直接推进尚未了解的信息"那一档
    assert "直接推进" not in text


def test_short_answer_still_advances_when_it_is_not_a_refusal() -> None:
    text = requirement("每天")
    assert "直接推进" in text
    assert "不要追问" not in text


def test_short_but_emotional_message_is_not_treated_as_a_terse_answer() -> None:
    """又短又带情绪的自述不能走「直接推进、不套共情前缀」那一档。

    这是实机验收暴露的机制性缺陷：只按字数判断时，"我最近真的好累。"（8 字）
    会被当成"是/每天"一样的短答，模型于是每次只丢回一个问题。
    """
    for text in ("我最近真的好累。", "晚上睡不好，白天没精神。", "有点烦", "我好累",
                 "撑不住了", "心里挺闷的"):
        rendered = requirement(text)
        assert "不套共情前缀" not in rendered, f"情绪自述被判成单纯短答：{text}"


def test_plain_informational_short_answers_still_use_the_terse_branch() -> None:
    """读不出情绪的词条式回答仍然走"直接推进"，保证评估推得动。"""
    for text in ("是", "每天", "一个月", "三次左右", "没有过", "嗯", "不太清楚"):
        assert "直接推进" in requirement(text), f"应当走短答分支：{text}"


def test_finish_screening_still_asks_nothing() -> None:
    """收尾轮优先级最高：不提问，也不被拒绝分支改写。"""
    text = requirement("我不想说", finish=True)
    assert "不提出任何问题" in text


# ---------------------------------------------------------------------------
# 2. 提示词允许"一个问题都不问"
# ---------------------------------------------------------------------------

def test_system_prompt_allows_a_turn_without_any_question() -> None:
    assert "可以一个问题都不提" in DIALOGUE_AGENT_SYSTEM_PROMPT
    # 四种允许的回复类型都在
    for marker in ("纯共情：只接住他的感受，不提问",
                   "回应 / 安慰 / 简单建议：说完就停，不追加问题",
                   "尊重拒绝：他不想说时先接纳，不追问"):
        assert marker in DIALOGUE_AGENT_SYSTEM_PROMPT, f"提示词缺少：{marker}"


def test_system_prompt_no_longer_mandates_a_question_every_turn() -> None:
    """旧的"默认每一轮只提出一个主要问题"正是机械提问的来源，必须已经改掉。"""
    assert "默认每一轮只提出一个主要问题" not in DIALOGUE_AGENT_SYSTEM_PROMPT
    assert "不必每一轮都提问" in DIALOGUE_AGENT_SYSTEM_PROMPT


def test_bubble_rule_is_structural_not_by_sentence_length() -> None:
    """分段按表达单元走：回应 + 追问两个单元必须拆成 2 条。"""
    assert "必须拆成 2 条" in DIALOGUE_AGENT_SYSTEM_PROMPT
    assert "不要用逗号或句号把这两个单元连在同一行" in DIALOGUE_AGENT_SYSTEM_PROMPT
    assert "不按句子长短" in DIALOGUE_AGENT_SYSTEM_PROMPT


def test_refusal_vocabulary_is_not_empty_and_is_documented() -> None:
    assert len(REFUSAL_PHRASES) >= 10
    assert all(phrase == phrase.strip() and phrase for phrase in REFUSAL_PHRASES)
