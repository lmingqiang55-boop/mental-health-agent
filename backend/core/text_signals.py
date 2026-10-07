"""Small predicate-scoped polarity checks against the original text."""

import re

# Only grammatical modifiers may connect a denial to its predicate. A noun or
# another predicate (e.g. 没有朋友 / 不开心 before 想自杀) ends that scope.
CHINESE_DENIAL = re.compile(
    r"(?:并不是|并没有|并不|并非|不是|没有|并未|未曾|不曾|从来没|从未|"
    r"不会|不要|不愿意|不想|别|未|没|不)"
    r"(?:(?:真的|真正|实际|亲自|曾经|已经|现在|今天|今晚|明天|一直|完全|"
    r"再|还|又|也|都|太|很|那么|特别|任何|明显|显著|稍微|一点|变得|"
    r"比(?:之前|以前|原来|刚才|昨天|过去|原先)|感到|觉得|感觉|想要|想|要|会|"
    r"愿意|准备|打算|计划|去|正在)\s*)*$")
ENGLISH_DENIAL = re.compile(
    r"\b(?:do not|don't|did not|didn't|will not|won't|never|not|no)"
    r"(?:\s+(?:really|ever|actually|want|intend|plan|to|going|would|will))*\s*$",
    re.IGNORECASE)


def predicate_is_negated(text: str, start: int) -> bool:
    """Count attached denials without losing the original preceding words.

    Adjacent double denial is not a single denial. Punctuation, unrelated
    nouns, and other predicates stop the scan; this is a bounded language rule,
    not a claim of general semantic understanding.
    """
    prefix = text[:start].rstrip()
    count = 0
    while prefix:
        match = CHINESE_DENIAL.search(prefix) or ENGLISH_DENIAL.search(prefix)
        if match is None:
            break
        count += 1
        prefix = prefix[:match.start()].rstrip()
    return count % 2 == 1
