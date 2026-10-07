"""Live semantic counterexamples; deterministic offline contract tests are separate."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.healing.client import HealingJSONClient
from backend.healing.knowledge import load_knowledge, validate_item
from backend.models.healing import Evidence, KnowledgeItem
from scripts.build_healing_knowledge import MANIFEST, allowed_section, check_semantics


def precise_cases():
    fixture = json.loads((MANIFEST.parents[3] / "tests/fixtures/healing_grounding_counterexamples.json").read_text(encoding="utf-8"))
    text = fixture["source_text"]
    def item(name):
        values = dict(fixture[name])
        proofs = values.pop("proofs")
        evidence = [Evidence(field=field, quote=quote, start=text.index(quote), end=text.index(quote)+len(quote))
                    for field, quote in proofs.items()]
        return KnowledgeItem(**values, knowledge_id=name, method_key=name, source_id="synthetic-counterexample",
            source_url="https://example.org/synthetic-extraction-fixture", source_title=fixture["provenance"],
            source_version="synthetic:1", source_digest=hashlib.sha256(text.encode()).hexdigest(),
            source_location="synthetic-paragraphs:1-2", scenes=["relationships"], evidence=evidence)
    original, adult = item("student_method"), item("adult_task")
    cases = [
        ("precise_correct", original, None, "usable"),
        ("explicit_age_expanded", original.model_copy(update={"age_min": 6, "age_max": 18}), "age_expanded", "pending"),
        ("explicit_age_removed", original.model_copy(update={"age_min": None, "age_max": None}), "age_expanded", "pending"),
        ("school_stage_expanded", original.model_copy(update={"school_stages": ["primary", "high"]}), "age_expanded", "pending"),
        ("only_adult_condition_omitted", original.model_copy(update={"prerequisites": ["必须在安静的空间里进行。"],
            "steps": ["在安静的空间里说出一次同伴矛盾。"]}), "prerequisite_missing", "pending"),
        ("only_other_condition_omitted", original.model_copy(update={"prerequisites": ["需要成人指导。"],
            "steps": ["在成人指导下说出一次同伴矛盾。"]}), "prerequisite_missing", "pending"),
        ("adult_task_correct", adult, None, "explanation_only"),
        ("adult_own_task_to_student", adult.model_copy(update={"purpose": "method", "executor": "student",
            "steps": ["你：独自向老师调查其他孩子在学校的情况。"]}), "executor_changed", "pending"),
    ]
    return text, cases


async def main(args):
    source = next(item for item in json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"]
                  if item["source_id"] == "unicef-stress")
    text = (args.work_dir / "unicef-stress.txt").read_text(encoding="utf-8")
    scope = allowed_section(text, source)
    original = next(item for item in load_knowledge() if item.source_id == source["source_id"] and item.status == "usable")
    cases = [
        ("correct", original, None),
        ("age_expanded", original.model_copy(update={"age_min": 6, "age_max": 18}), "age_expanded"),
        ("executor_changed", original.model_copy(update={"executor": "student", "prerequisites": []}), "executor_changed"),
        ("prerequisite_missing", original.model_copy(update={"prerequisites": [],
             "steps": [step.replace("成人", "学生").replace("家长", "自己") for step in original.steps]}), "prerequisite_missing"),
        ("unsupported_step", original.model_copy(update={"steps": [*original.steps, "每天独自做二十分钟憋气练习。"]}), "unsupported_step"),
    ]
    result = []
    for name, item, expected in cases:
        started = perf_counter()
        issues = await check_semantics(HealingJSONClient(), item, text, scope, source,
                                       "Stress in children and adolescents")
        checked = validate_item(item, text, [(0, len(text))], issues)
        row = {"case": name, "issues": checked.validation_issues, "status": checked.status,
               "passed": checked.status == "usable" if expected is None else expected in checked.validation_issues and checked.status == "pending",
               "elapsed_ms": (perf_counter()-started)*1000}
        result.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    text, cases = precise_cases()
    source = {"allowed_topics": "合成资料中明示的原始方法和成人任务，严格保留年龄、学段、执行者及前提",
              "excluded_topics": "新增动作、诊断、治疗、扩大范围"}
    for name, item, expected, status in cases:
        started = perf_counter()
        issues = await check_semantics(HealingJSONClient(), item, text, (0, len(text)), source, "合成校验资料，非临床来源")
        checked = validate_item(item, text, [(0, len(text))], issues)
        # Stage expansion may be classified as age or audience expansion.
        issue_passed = expected in checked.validation_issues if expected else not checked.validation_issues
        if name == "school_stage_expanded":
            issue_passed = bool({"age_expanded", "audience_expanded"}.intersection(checked.validation_issues))
        row = {"case": name, "issues": checked.validation_issues, "status": checked.status,
               "passed": checked.status == status and issue_passed,
               "elapsed_ms": (perf_counter()-started)*1000, "provenance": "synthetic_fixture"}
        result.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (args.work_dir / "semantic_counterexamples.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(row["passed"] for row in result):
        raise RuntimeError("语义校验反例未全部通过，请检查诊断记录")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
