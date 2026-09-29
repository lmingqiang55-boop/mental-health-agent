"""Evidence candidates and the deterministic local extractor."""
import os
import re
from dataclasses import dataclass
from typing import Protocol

from backend.assessment.bank import BY_ID
from backend.assessment.models import Category


PAST_14_DAYS = re.compile(r"过去两周|最近两周|这两周|近两周|过去14天|最近14天|这14天")
OTHER_TIME = re.compile(r"去年|上个月|几个月前|小时候|以前|过去一年")
DAY_COUNT = re.compile(r"\d+\s*天|[一二三四五六七八九十]+\s*天")
SPLIT = re.compile(r"[，,。；;！!\n]+")
THIRD_PERSON = re.compile(r"^(?:她|他|朋友|同学|我朋友|我同学|我的朋友|我的同学|我妈|我爸|别人)")


@dataclass(frozen=True)
class EvidenceCandidate:
    item_id: str
    quote: str
    period: str
    category: Category | None


class EvidenceExtractor(Protocol):
    version: str

    def extract(self, text: str, target_item_id: str | None) -> list[EvidenceCandidate]: ...


class ExtractionUnavailable(Exception):
    """The configured extraction service could not return valid structured data."""


def explicit_category(text: str) -> Category | None:
    value = text.strip()
    # A numeric count alongside a category can express a conflicting answer.
    if DAY_COUNT.search(value):
        return None
    matches: list[Category] = []
    if "几乎每天" in value or "几乎每一天" in value:
        matches.append("nearly_every_day")
    if "超过一半" in value or "一半以上" in value:
        matches.append("more_than_half_days")
    if "有几天" in value or "好几天" in value:
        matches.append("several_days")
    if ("完全没有" in value or "一点也没有" in value or "一次也没有" in value
            or value in {"没有", "没", "从来没有", "从未"}
            or re.search(r"没有.{0,8}(问题|症状|困扰)", value)):
        matches.append("not_at_all")
    if len(matches) > 1:
        return None
    if matches:
        return matches[0]
    return None


def validate_candidate(
    candidate: EvidenceCandidate, text: str, target_item_id: str | None,
) -> EvidenceCandidate | None:
    """Ground every model field in this turn before it can change an item."""
    quote = candidate.quote
    if candidate.item_id not in BY_ID or not quote.strip() or quote not in text:
        return None
    offset = text.find(quote)
    clause_start = max(text.rfind(mark, 0, offset) for mark in "，,。；;！!\n") + 1
    clause = text[clause_start:offset + len(quote)].strip()
    if THIRD_PERSON.search(clause) or re.match(r"^(?:如果|假如|假设|比如|例如)", clause):
        return None

    matched = [item_id for item_id, item in BY_ID.items()
               if any(clue in quote for clue in item.clues)]
    if matched and candidate.item_id not in matched:
        return None
    if not matched and candidate.item_id != target_item_id:
        return None

    category = explicit_category(quote)
    if len(matched) > 1:
        category = None
    # A conflicting model category must be clarified instead of being scored.
    if candidate.category is not None and candidate.category != category:
        category = None

    if OTHER_TIME.search(clause):
        period = "other"
    elif PAST_14_DAYS.search(clause) or PAST_14_DAYS.search(text):
        period = "past_14_days"
    elif candidate.item_id == target_item_id and not OTHER_TIME.search(text):
        period = "past_14_days"
    else:
        period = "unknown"
    return EvidenceCandidate(candidate.item_id, quote, period, category)


class RuleMockExtractor:
    version = "rule_mock_v1"

    def extract(self, text: str, target_item_id: str | None) -> list[EvidenceCandidate]:
        parts = [part.strip() for part in SPLIT.split(text) if part.strip()]
        whole_period = bool(PAST_14_DAYS.search(text))
        candidates: list[EvidenceCandidate] = []
        for part in parts:
            if THIRD_PERSON.search(part):
                continue
            category = explicit_category(part)
            if OTHER_TIME.search(part):
                period = "other"
            elif PAST_14_DAYS.search(part) or whole_period:
                period = "past_14_days"
            elif target_item_id:
                # The immediately preceding item question explicitly says
                # '过去两周', so a direct reply inherits its time window.
                period = "past_14_days"
            else:
                period = "unknown"

            matched = [item_id for item_id, item in BY_ID.items()
                       if any(clue in part for clue in item.clues)]
            if len(matched) > 1:
                # One clause mentioning several symptoms does not establish
                # the same frequency for each of them.
                category = None
            if not matched and target_item_id and category is not None:
                matched = [target_item_id]
            for item_id in matched:
                # Only the current target inherits the question's time window.
                item_period = period
                if item_id != target_item_id and not whole_period and not PAST_14_DAYS.search(part):
                    item_period = "unknown"
                candidates.append(EvidenceCandidate(item_id, part, item_period, category))
        return candidates


def build_extractor_from_env() -> EvidenceExtractor:
    provider = os.getenv("ASSESSMENT_EXTRACTOR", "mock").strip().lower()
    if provider == "mock":
        return RuleMockExtractor()
    if provider == "openai_compatible":
        from backend.assessment.model_extractor import OpenAICompatibleExtractor

        return OpenAICompatibleExtractor(
            base_url=os.getenv("ASSESSMENT_LLM_BASE_URL", ""),
            model=os.getenv("ASSESSMENT_LLM_MODEL", ""),
            api_key=os.getenv("ASSESSMENT_LLM_API_KEY", ""),
            thinking_mode=os.getenv("ASSESSMENT_LLM_THINKING", "default").strip().lower(),
        )
    raise ValueError(f"Unsupported ASSESSMENT_EXTRACTOR: {provider}")


def safety_signal(text: str) -> str:
    """Demo flag for routing, never a clinical risk classification."""
    value = text.lower()
    terms = ("自杀", "自残", "不想活", "不如死", "伤害自己", "结束生命", "想死", "轻生")
    if not any(term in value for term in terms):
        return "no_signal"
    if re.search(r"我.{0,3}(?:现在|马上|立刻)(?:真的|就)?(?:想|要|准备)(?:去)?(?:自杀|自残|伤害自己|结束生命|轻生)", value):
        return "urgent"
    return "needs_review"
