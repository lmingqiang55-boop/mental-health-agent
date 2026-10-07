"""Validate execution claims against the original answer, including negation."""

import re

from backend.core.text_signals import predicate_is_negated

ATTEMPT = re.compile(r"(?P<action>尝试了|尝试过|(?<!试)试了|(?<!试)试过|做了|做过|用了|用过|练了|练过)")
NOT_ATTEMPTED = re.compile(
    r"(?:还(?:没(?:有)?|未)|尚未|从(?:来)?(?:没(?:有)?|未)|未曾|没(?:有)?|未)"
    r"(?:(?:真正|实际|亲自|开始|去)\s*)*"
    r"(?:尝试(?:过|了)?|试(?:过|了|一下)?|做(?:过|了)?|用(?:过|了)|练(?:过|了)?)")
PREPARATION = re.compile(r"(?:现在|准备|打算|等会|晚点).{0,8}(?P<action>试试|尝试|试一下)")
NEGATED_ACTION = re.compile(
    r"(?:还(?:没|没有)|尚未|从未|不曾|从(?:来)?(?:没|没有)|并未|未|没(?:有)?|"
    r"不(?:想|愿(?:意)?|会|打算|准备|计划|是)?)"
    r"(?:(?:再|去|真正|实际|真的|亲自|已经|现在|今天|明天|今晚|曾经|开始|打算|准备|计划)\s*)*$")
EFFECT = re.compile(
    r"(?P<ineffective>没(?:有)?用|没(?:有)?效果|没(?:有)?帮助|无效)|"
    r"(?P<worse>更\s*(?:(?:加|显得|感到|感觉|觉得|变得|明显|显著|一点|有点|让(?:我|人))\s*){0,3}"
    r"(?:难受|糟|紧张|严重)|加重)|"
    r"(?P<helpful>有用|有帮助|有(?:了)?效果|有效|好多了|好一些|轻松|舒服)")
DECLINE = re.compile(r"不想|不愿(?:意)?|不用|不要|拒绝|不喜欢")
WORDING_SIGNAL = re.compile(
    r"(?P<decline>(?:不用|不必|不需要|无需|不要|不想|不愿意|不愿|别)(?:再|先|现在)?(?:改写|修改|简化|换|改))|"
    r"(?P<understood>看得懂|读得懂|听得懂)|"
    r"(?P<difficulty>太难|复杂|看不懂|读不懂|听不懂|难懂|步骤太多)|"
    r"(?P<request>简单(?:一点|一些|些|点|的(?:话|词|表达))|"
    r"简短(?:一点|一些|些|点|的(?:话|表达))|简化)")
WORDING_DENIAL = re.compile(
    r"(?:不用|不必|不需要|无需|不要|不想|不愿意|不愿|别)"
    r"(?:(?:再|先|现在|更|那么|用|说|讲|写|改成|换成|变得)\s*)*$")


def _last_signal(pattern, text, evidence=None):
    # An evidence substring such as "试过" must keep the preceding "没有" in
    # its original answer. The latest explicit statement wins over an earlier
    # one, e.g. "之前没有试过，但今天试了".
    spans = [(0, len(text))] if evidence is None else [
        (match.start(), match.end()) for match in re.finditer(re.escape(evidence), text)]
    result = None
    for match in pattern.finditer(text):
        if any(start <= match.start("action") and match.end("action") <= end for start, end in spans):
            result = NEGATED_ACTION.search(text[:match.start("action")].rstrip()) is None
    return result


def attempt_signal(text, evidence=None):
    """True/False for an affirmed/denied attempt, None if not stated."""
    return _last_signal(ATTEMPT, text, evidence)


def preparation_signal(text, evidence=None):
    return _last_signal(PREPARATION, text, evidence)


def ordinal_targets(number, reference_suggestions):
    """Use immutable display numbers, including methods that were deactivated."""
    return {item.suggestion_id for index, item in enumerate(reference_suggestions, 1)
            if (getattr(item, "display_number", None) or index) == number}


def ordinal_number(value):
    if value.isdigit():
        return int(value)
    return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(value)


def preparation_targets(text, reference_suggestions):
    """Bind positive preparation to the advice visible before this answer.

    Filtering a newly unavailable method must not renumber the student's
    references or turn an ambiguous choice into preparation for its survivor.
    """
    active = [item for item in reference_suggestions if item.active]
    selected = set()
    carried = None
    ordinal = re.compile(r"第([一二三四五六七八九十\d]+)(?:个|条|种)(?:方法|建议)?")
    for clause in re.split(r"[，,。！？!?；;\n]", text):
        clause = clause.strip()
        if not clause:
            continue
        ordinals = list(ordinal.finditer(clause))
        named = [item for item in reference_suggestions if item.title and item.title in clause]
        references = {item.suggestion_id for item in named}
        for match in ordinals:
            number = ordinal_number(match.group(1))
            if number is not None:
                references.update(ordinal_targets(number, reference_suggestions))
        explicit = bool(ordinals or named)
        all_methods = bool(re.search(r"(?:两个|全部|所有)(?:方法|建议)?(?:我)?都", clause))
        preparation = preparation_signal(clause)
        if preparation is not None:
            if all_methods and not explicit:
                targets = {item.suggestion_id for item in active} if len(reference_suggestions) <= 2 else set()
            elif explicit:
                targets = references if len(references) == 1 or "都" in clause else set()
            elif carried is not None:
                targets = carried
            else:
                targets = {active[0].suggestion_id} if len(active) == len(reference_suggestions) == 1 else set()
            if preparation:
                selected.update(targets & {item.suggestion_id for item in active})
            elif explicit or carried is not None or all_methods:
                selected.difference_update(targets)
            else:
                # An unqualified retraction cannot affirm any earlier choice.
                selected.clear()
        # A bare label may precede "我准备试试" after a comma. Other clauses,
        # including refusals, never supply an implicit target to the next one.
        carried = references if ordinal.fullmatch(clause) or any(
            item.title == clause for item in named) else None
    return selected


def _reference_scopes(text, reference_suggestions):
    """Local method references against the unchanged pre-answer snapshot."""
    active = [item for item in reference_suggestions if item.active]
    default = {active[0].suggestion_id} if len(active) == len(reference_suggestions) == 1 else set()
    shared_targets = {item.suggestion_id for item in reference_suggestions} if len(reference_suggestions) <= 2 else set()
    ordinal = re.compile(r"第([一二三四五六七八九十\d]+)(?:个|条|种)(?:方法|建议)?")
    collective = re.compile(r"(?:两个|全部|所有)(?:方法|建议)?(?:我)?都")
    titles = {item.title for item in reference_suggestions if item.title}
    title_pattern = re.compile("|".join(map(re.escape, sorted(titles, key=lambda title: (-len(title), title))))) if titles else None
    scopes, carried, reference_seen = [], default, False
    for clause in re.finditer(r"[^，,。！？!?；;\n]+", text):
        start, end = clause.span()
        if re.search(r"[。！？!?；;\n]", text[scopes[-1][1]:start] if scopes else text[:start]):
            carried = default
            reference_seen = False
        value = clause.group()
        markers = []
        for match in ordinal.finditer(value):
            number = ordinal_number(match.group(1))
            targets = ordinal_targets(number, reference_suggestions) if number is not None else set()
            markers.append({"start": match.start(), "end": match.end(), "targets": targets,
                            "shared": False, "joined": False})
        if title_pattern:
            for match in title_pattern.finditer(value):
                targets = {item.suggestion_id for item in reference_suggestions if item.title == match.group()}
                markers.append({"start": match.start(), "end": match.end(), "targets": targets,
                                "shared": False, "joined": False})
        for match in collective.finditer(value):
            markers.append({"start": match.start(), "end": match.end(),
                            "targets": shared_targets, "shared": True, "joined": False})
        if not markers and not reference_seen and re.match(r"\s*(?:我)?都(?=试了|试过|做了|做过|用了|用过)", value):
            markers.append({"start": 0, "end": 0, "targets": shared_targets,
                            "shared": True, "joined": False})
        groups = []
        for marker in sorted(markers, key=lambda item: (item["start"], item["end"])):
            gap = value[groups[-1]["end"]:marker["start"]].strip() if groups else None
            if groups and (marker["start"] <= groups[-1]["end"] or gap in {"和", "与", "及", "、", "以及", "跟"}):
                group = groups[-1]
                group["end"] = max(group["end"], marker["end"])
                group["targets"] = group["targets"] | marker["targets"] if group["targets"] and marker["targets"] else set()
                group["shared"] |= marker["shared"]
                group["joined"] |= bool(gap) or marker["joined"]
            else:
                groups.append(marker)
        if not groups:
            scopes.append((start, end, frozenset(carried)))
            continue
        reference_seen = True
        for index, group in enumerate(groups):
            boundary = groups[index + 1]["start"] if index + 1 < len(groups) else len(value)
            shared = group["shared"] or group["joined"] and re.match(
                r"(?:\s|我|也|已经|今天|现在|这次|方法|建议)*都", value[group["end"]:boundary])
            targets = group["targets"] if len(group["targets"]) == 1 or shared else set()
            # An action may precede its label: '我试了第二个方法'.
            begin = start if index == 0 else start + group["start"]
            scopes.append((begin, start + boundary, frozenset(targets)))
            carried = targets
    return scopes


def _span_targets(scopes, start, end):
    bindings = {targets for left, right, targets in scopes if max(left, start) < min(right, end)}
    return set(next(iter(bindings))) if len(bindings) == 1 else set()


def has_affirmed_attempt(text, reference_suggestions):
    """Do not let another method's absence hide a real attempt before pausing.

    Later corrections replace only the same method's signal. An unresolved
    attempt also needs the normal feedback/clarification path, not a shortcut
    that silently discards it. This check never records an attempt itself.
    """
    scopes = _reference_scopes(text, reference_suggestions)
    latest = {}
    for match in ATTEMPT.finditer(text):
        targets = _span_targets(scopes, match.start("action"), match.end("action"))
        affirmed = NEGATED_ACTION.search(text[:match.start("action")].rstrip()) is None
        for target in targets or {None}:
            latest[target] = affirmed
    return any(latest.values())


def has_effect_or_decline(text):
    """These claims need feedback validation even without a new attempt verb."""
    return any(not predicate_is_negated(text, match.start())
               for pattern in (EFFECT, DECLINE) for match in pattern.finditer(text))


def decline_signal(text, evidence):
    """Check quoted refusal words at their original positions, not in isolation."""
    spans = [match.span() for match in re.finditer(re.escape(evidence), text)]
    latest = None
    for match in DECLINE.finditer(text):
        if any(left <= match.start() and match.end() <= right for left, right in spans):
            latest = not predicate_is_negated(text, match.start())
    return latest is True


def feedback_targets(text, evidence, reference_suggestions):
    """Bind quotes locally; repeated or cross-method quotes stay ambiguous."""
    scopes = _reference_scopes(text, reference_suggestions)
    bindings = set()
    for match in re.finditer(re.escape(evidence), text):
        for start, end, targets in scopes:
            if max(start, match.start()) < min(end, match.end()):
                bindings.add(targets)
    return set(next(iter(bindings))) if len(bindings) == 1 else set()


def unresolved_feedback(text, reference_suggestions):
    """Clarify only a locally unbound claim, not a rejected model proposal.

    Each occurrence uses its own original span, including identical signals
    on two explicitly named methods. This does not record any feedback.
    """
    scopes = _reference_scopes(text, reference_suggestions)
    for pattern in (ATTEMPT, NOT_ATTEMPTED, PREPARATION, EFFECT, DECLINE, WORDING_SIGNAL):
        for match in pattern.finditer(text):
            if not _span_targets(scopes, *match.span()):
                return True
    return False


def _not_attempted_signals(text):
    """Explicit absence, its denial, and later actual attempts in text order.

    Bare '没用' describes an effect ambiguously, so it is not an absence claim.
    Attempts embedded in '没有试过' must not undo that same absence claim.
    """
    absence = list(NOT_ATTEMPTED.finditer(text))
    signals = [(match.start(), match.end(), not predicate_is_negated(text, match.start()))
               for match in absence]
    signals.extend((match.start(), match.end(), False) for match in ATTEMPT.finditer(text)
                   if not any(max(match.start(), item.start()) < min(match.end(), item.end()) for item in absence)
                   and not predicate_is_negated(text, match.start("action")))
    return sorted(signals)


def not_attempted_signal(text, evidence):
    spans = [match.span() for match in re.finditer(re.escape(evidence), text)]
    latest = None
    for start, end, absent in _not_attempted_signals(text):
        if any(end <= right and (left <= start or start < left < end
                and NOT_ATTEMPTED.fullmatch(text[left:end])) for left, right in spans):
            latest = absent
    return latest is True


def not_attempted_evidence(text, reference_suggestions):
    """Return unambiguous local quotes for each latest explicit absence claim."""
    scopes = _reference_scopes(text, reference_suggestions)
    latest = {}
    for start, end, absent in _not_attempted_signals(text):
        for target in _span_targets(scopes, start, end):
            latest[target] = (start, end) if absent else None
    result = {}
    for target, signal in latest.items():
        if signal is None:
            continue
        start, end = signal
        index = next(i for i, (left, right, _) in enumerate(scopes) if left <= start and end <= right)
        left, right, targets = scopes[index]
        # Keep the preceding bare label in '第二个方法，还没试'. This also
        # disambiguates identical absence words quoted for two separate methods.
        while index > 0 and scopes[index - 1][2] == targets and not re.search(
                r"[。！？!?；;\n]", text[scopes[index - 1][1]:left]):
            index -= 1
            left = scopes[index][0]
        left = max(left, end - 1000)
        evidence = text[left:min(right, left + 1000)].strip()
        if target in feedback_targets(text, evidence, reference_suggestions):
            result[target] = evidence
    return result


def simplification_targets(text, reference_suggestions):
    """Require affirmed wording difficulty/request for each original method.

    Check occurrences separately so identical words used for different methods
    do not cross-bind. Later explicit comprehension or refusal retracts a
    request for that same method; it does not retract another method's request.
    """
    scopes = _reference_scopes(text, reference_suggestions)
    selected = set()
    for signal in WORDING_SIGNAL.finditer(text):
        targets = _span_targets(scopes, signal.start(), signal.end())
        negated = predicate_is_negated(text, signal.start())
        additional_denial = WORDING_DENIAL.search(text[:signal.start()].rstrip())
        if additional_denial and not predicate_is_negated(text, additional_denial.start()):
            negated = True
        if signal.lastgroup in {"decline", "understood"}:
            if not negated:
                if signal.lastgroup == "decline" and not targets:
                    # An unqualified "先别改" must not leave an earlier
                    # request affirmed merely because a sentence ended.
                    selected.clear()
                else:
                    selected.difference_update(targets)
        elif negated:
            selected.difference_update(targets)
        else:
            selected.update(targets)
    return selected


def effect_signal(text, effect, evidence):
    """Require an affirmed effect in the quote, preserving original negation.

    Match ineffective phrases before their embedded positive words (没有帮助
    contains 有帮助). A denied phrase does not imply a different effect. When
    the quote includes an explicit correction, its latest effect wins.
    """
    spans = [(match.start(), match.end()) for match in re.finditer(re.escape(evidence), text)]
    latest = None
    for match in EFFECT.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in spans):
            latest = None if predicate_is_negated(text, match.start()) else match.lastgroup
    return latest == effect
