"""Grounded extraction checks inspired by LangExtract's source intervals.

Semantic verification is separate from interval matching: valid offsets alone do
not prove that an age, executor, prerequisite or translated step is supported.
"""

import hashlib
import re
from pathlib import Path

from backend.models.healing import KnowledgeItem

KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "rag" / "knowledge" / "healing.jsonl"


def validate_item(item: KnowledgeItem, source_text: str, allowed_ranges: list[tuple[int, int]],
                  semantic_issues: list[str] | None) -> KnowledgeItem:
    result = item.model_copy(deep=True)
    issues = []
    if hashlib.sha256(source_text.encode("utf-8")).hexdigest() != item.source_digest:
        issues.append("source_digest_mismatch")
    if not item.source_url.startswith("https://") or not item.source_version:
        issues.append("source_missing")
    for evidence in item.evidence:
        if source_text[evidence.start:evidence.end] != evidence.quote:
            issues.append("source_interval_mismatch")
        if not any(start <= evidence.start < evidence.end <= end for start, end in allowed_ranges):
            issues.append("outside_allowed_scope")
    fields = {evidence.field for evidence in item.evidence}
    audience_quotes = " ".join(evidence.quote.lower() for evidence in item.evidence if evidence.field == "audience")
    if item.audience == "children_adolescents" and not re.search(
            r"(?:children|kids).{0,25}(adolescents|teenagers|teens)|儿童.{0,4}青少年", audience_quotes):
        issues.append("audience_declaration_missing")
    if item.audience == "adolescents" and not re.search(r"adolescents|teenagers|teens|青少年|青春期", audience_quotes):
        issues.append("audience_declaration_missing")
    if item.purpose == "method":
        if not item.steps or item.executor == "unspecified" or item.audience == "unspecified":
            issues.append("method_scope_unknown")
        required = {"audience", "executor", "steps"}
        age_quotes = " ".join(proof.quote for proof in item.evidence if proof.field == "age")
        if item.age_min is not None or item.age_max is not None or age_quotes:
            required.add("age")
            pairs = [(int(low), int(high)) for low, high in re.findall(
                r"(\d{1,2})\s*(?:岁|years?)?\s*(?:[-–—~]\s*(?:to\s*)?|to|至|到)\s*(\d{1,2})", age_quotes, re.I)]
            if not age_quotes or (pairs and (item.age_min, item.age_max) not in pairs):
                issues.append("age_expanded")
        if item.school_stages:
            required.add("school_stages")
        if item.prerequisites:
            required.add("prerequisites")
        if not required.issubset(fields):
            issues.append("field_evidence_missing")
        if ("prerequisites" in fields and not item.prerequisites):
            issues.append("prerequisite_missing")
        if item.executor == "adult_guided" and not any(
                re.search(r"成人|家长|监护|adult|parent", condition, re.I)
                for condition in item.prerequisites):
            issues.append("prerequisite_missing")
        executor_quotes = " ".join(evidence.quote for evidence in item.evidence if evidence.field == "executor")
        if item.executor == "student" and (any(step.startswith("成人：") for step in item.steps) or
                re.search(r"help your child|ask your child|encourage your child|家长|成人指导|成人陪伴", executor_quotes, re.I)):
            issues.append("executor_changed")
        if any(re.search(r"医学评估|医疗评估|医生评估|medical assessment", condition, re.I)
               for condition in item.prerequisites):
            # The current memory contract cannot establish this prerequisite.
            issues.append("medical_prerequisite_unconfirmed")
    if semantic_issues is None:
        issues.append("semantic_check_unavailable")
    else:
        issues.extend(semantic_issues)
    result.semantic_checked = semantic_issues is not None
    result.validation_issues = sorted(set(issues))
    result.status = ("pending" if issues else
                     "usable" if item.purpose == "method" and item.executor != "adult" else
                     "explanation_only")
    return result


def attach_source_help(items: list[KnowledgeItem]) -> list[KnowledgeItem]:
    """Retain independently checked source help conditions as method cautions.

    Do not inherit across sources, audiences or scopes, and never turn the help
    paragraph into an extra treatment step. This is an offline build operation.
    """
    result = [item.model_copy(deep=True) for item in items]
    def scope_key(item):
        return (item.source_id, item.source_digest, item.source_location, item.audience,
                item.age_min, item.age_max, tuple(item.school_stages), tuple(item.scenes))
    helpers = [item for item in items if item.purpose == "help" and item.status == "explanation_only"
               and item.semantic_checked and not item.validation_issues
               and item.executor in {"student", "adult_guided"}]
    for item in result:
        if item.status != "usable" or item.purpose != "method":
            continue
        for helper in helpers:
            if scope_key(item) != scope_key(helper) or helper.goal in item.referral_conditions:
                continue
            if len(item.referral_conditions) >= 8:
                break
            item.referral_conditions.append(helper.goal)
            item.evidence.extend(proof.model_copy(update={"field": "referral_conditions"})
                for proof in helper.evidence if proof.field == "steps")
    return result


def load_knowledge(path: Path = KNOWLEDGE_PATH) -> list[KnowledgeItem]:
    items = [KnowledgeItem.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    seen = set()
    for item in items:
        if item.knowledge_id in seen:
            raise ValueError("知识编号重复")
        seen.add(item.knowledge_id)
    return items
