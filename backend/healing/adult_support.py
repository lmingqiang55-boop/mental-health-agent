"""Conservative, question-scoped adult availability; no family-presence guesses."""

import re

from backend.core.text_signals import predicate_is_negated

ADULT_QUESTION = "你身边有没有一位你信任、愿意也能陪你试试的大人？"
ROLE = re.compile(r"学校心理老师|心理老师|班主任|辅导员|监护人|妈妈|爸爸|我妈|我爸|父母|家长|老师|爷爷|奶奶|外公|外婆|姥姥|姥爷|成人|大人")
ACTION = re.compile(r"陪(?:伴)?|指导|帮助|帮我|帮忙|支持我")
CUE = re.compile(r"可以|愿意|有空|能够|能|会|肯")
UNKNOWN = re.compile(r"不知道|不清楚|不确定|不一定|可能|也许|还没问|没问过|不想说|不愿(?:意)?(?:回答|说)|不方便说|不好说")
UNAVAILABLE = re.compile(r"没(?:有)?(?:时间|空)|无法|不能|不愿意|不愿|不肯|拒绝|不在(?:身边|家)|出差")
UNTRUSTED = re.compile(r"不信任|不相信|害怕|不敢找")


def support_signal(text, *, answering=False):
    """Return (recognized, available). Unsupported or ambiguous text stays unknown.

    Short yes/no answers are meaningful only directly after our own question.
    Explicit current support statements can update a prior caller value later.
    This is bounded Chinese phrase handling, not general semantic extraction.
    """
    canonical = re.sub(r"[\s，,。.!！?？；;]", "", text)
    if answering:
        if canonical in {"有", "有的", "有呀", "有啊", "可以", "可以的", "能", "能的", "是的", "嗯有"}:
            return True, True
        if canonical in {"没有", "没", "没有的", "没有啊", "没有呀", "不行", "不能", "没人", "没有人"}:
            return True, False
        if UNKNOWN.fullmatch(canonical):
            return True, None
    people, trusted = {}, {}
    last_roles = []
    recognized = False
    if answering:
        first = re.split(r"[，,。！？!?；;\n]|但是|不过|可是|但", text)[0].strip()
        if first in {"有", "有的", "可以", "没有", "不行"}:
            people["answer"] = first not in {"没有", "不行"}
            last_roles, recognized = ["answer"], True
    for clause in re.split(r"[，,。！？!?；;\n]|但是|不过|可是|但", text):
        if re.search(r"第[一二三四五六七八九十\d]+(?:个|条|种)|这个方法|那个方法|刚才的方法", clause):
            continue  # Method-specific feasibility is handled by its bound context.
        roles = [match.group(0) for match in ROLE.finditer(clause)]
        actions = list(ACTION.finditer(clause))
        if roles:
            people.pop("answer", None)
            last_roles = roles
        targets = roles or last_roles
        if not targets:
            if re.search(r"(?:没人|无人|没有人).{0,8}(?:陪|指导|帮助)", clause):
                people["unspecified"] = False
                recognized = True
            continue
        distrust = UNTRUSTED.search(clause)
        if distrust and not predicate_is_negated(clause, distrust.start()):
            for person in targets:
                trusted[person] = False
                people[person] = False
            recognized = True
            continue
        if not roles and re.match(r"\s*(?:我|我们|自己)", clause) and not actions:
            continue  # The student's time limit is not the adult's availability.
        if (UNKNOWN.search(clause) or re.search(r"如果|假如|要是|(?:吗|么)$|有没有|是否", clause)) and (
                roles or answering) and (actions or CUE.search(clause)):
            for person in targets:
                people[person] = None
            recognized = True
            continue
        absence = re.search(r"(?:没有|没|找不到)(?:(?:任何|一个|一位|愿意|能够|能|可以|肯|"
            r"我|陪伴|陪|指导|帮助|信任|可信任|的|身边|在|来|给|一起)){0,12}(?:" + ROLE.pattern + r")", clause)
        if absence and (actions or answering):
            value = predicate_is_negated(clause, absence.start())
        elif UNAVAILABLE.search(clause) and (actions or
                re.search(r"没(?:有)?(?:时间|空)|不在(?:身边|家)|出差", clause) or
                answering and roles and len(canonical) <= 12):
            negative = UNAVAILABLE.search(clause)
            if predicate_is_negated(clause, negative.start()):
                continue  # A denial of unavailability does not prove all conditions.
            value = False
        elif actions and not re.search(r"以前|曾经|上次|昨天|去年", clause):
            action = actions[-1]
            cues = list(CUE.finditer(clause, 0, action.start()))
            if not cues:
                continue
            cue = cues[-1]
            value = not (predicate_is_negated(clause, cue.start()) or
                         predicate_is_negated(clause, action.start()))
        elif answering and roles and CUE.search(clause) and len(canonical) <= 12:
            cue = CUE.search(clause)
            value = not predicate_is_negated(clause, cue.start())
        else:
            continue
        recognized = True
        for person in targets:
            people[person] = value if trusted.get(person) is not False else False
    if any(value is True for value in people.values()):
        return True, True
    if any(value is None for value in people.values()):
        return True, None
    if recognized:
        return True, False
    # A non-answer closes this question without guessing or asking it repeatedly.
    return (True, None) if answering else (False, None)


def effective_background(state):
    condition = state.adult_support
    available = condition.available
    if available is None and condition.asked:
        available = False  # Eligibility restriction, not a recorded negative fact.
    return state.memory.background.model_copy(update={"adult_support_available": available})


def current_memory(state):
    return state.memory.model_copy(update={"background": state.memory.background.model_copy(
            update={"adult_support_available": state.adult_support.available}),
        "provenance": {**state.memory.provenance, "background.adult_support_available":
            "current_round_adult_support:" + (state.adult_support.source or "unknown")}})


def support_question(question):
    return bool(question and ROLE.search(question) and re.search(
        r"有没有|是否|谁|哪.{0,4}(?:位|个)|能.{0,8}陪|愿意.{0,8}陪", question))
