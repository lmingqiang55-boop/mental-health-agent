"""Incremental wording builds preserve verified text and reject unsafe rewrites."""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from backend.healing.knowledge import load_knowledge
from backend.models.healing import Evidence, KnowledgeItem, KnowledgeWording
from scripts import adapt_healing_wording as adapt
from scripts.build_healing_knowledge import SemanticCheck


def wording(style="simple", *, checked=True, steps=None):
    return KnowledgeWording(
        wording_id="old:" + style, style=style, title="说说你的担心", goal="说出让你担心的事",
        steps=steps or ["和成人一起，用5分钟说出你的担心。"], semantic_checked=checked)


@pytest.fixture
def wording_build(tmp_path, monkeypatch):
    text = "适用于儿童青少年。学生在成人陪伴下，用5分钟说出自己的担心。"
    source = {"source_id": "synthetic", "allowed_start": text}
    manifest = tmp_path / "sources.json"
    manifest.write_text(json.dumps({"sources": [source]}), encoding="utf-8")
    monkeypatch.setattr(adapt, "MANIFEST", manifest)
    work = tmp_path / "work"
    work.mkdir()
    (work / "synthetic.txt").write_text(text, encoding="utf-8")
    item = KnowledgeItem(
        knowledge_id="method-1", method_key="say-concern", source_id="synthetic",
        source_url="https://example.org/support", source_title="合成来源", source_version="test:1",
        source_digest=hashlib.sha256(text.encode()).hexdigest(), source_location="paragraph:1",
        title="说出自己的担心", scenes=["study_stress"], audience="children_adolescents",
        executor="adult_guided", purpose="method", goal="说出让你担心的事情",
        steps=["在成人陪伴下，用5分钟说出自己的担心。"], prerequisites=["有成人陪伴。"],
        evidence=[Evidence(field=field, quote=text, start=0, end=len(text))
                  for field in ["audience", "executor", "steps", "prerequisites"]],
        status="usable", semantic_checked=True)

    class Model:
        def __init__(self):
            self.calls = []
            self.issues = []
            self.steps = wording().steps
            self.fail_id = None

        async def generate(self, system, payload, schema, **kwargs):
            self.calls.append((schema, payload))
            original = payload.get("item") or payload["original"]
            if original["knowledge_id"] == self.fail_id:
                raise RuntimeError("private-service-detail")
            if schema is adapt.WordingBatch:
                return adapt.WordingBatch(wordings=[wording(checked=False, steps=self.steps)])
            assert schema is SemanticCheck
            return SemanticCheck(issues=self.issues)

    model = Model()
    monkeypatch.setattr(adapt, "HealingJSONClient", lambda: model)

    def run(items):
        source_path = tmp_path / "input.jsonl"
        output = tmp_path / "output.jsonl"
        source_path.write_text("".join(value.model_dump_json() + "\n" for value in items), encoding="utf-8")
        asyncio.run(adapt.main(SimpleNamespace(
            input=source_path, output=output, work_dir=work, styles=["simple"],
            only_missing=True, only_needs_address=False, use_cache=False)))
        checks = json.loads((work / "wording_checks.json").read_text(encoding="utf-8"))
        return load_knowledge(output), checks

    return item, model, run


def test_missing_only_skips_verified_and_quarantined_items(wording_build):
    item, model, run = wording_build
    verified = item.model_copy(update={"wordings": [wording()]})
    pending = item.model_copy(update={"knowledge_id": "pending", "status": "pending"})
    output, checks = run([verified, pending])
    assert output == [verified, pending]
    assert not model.calls and not checks


def test_simple_fill_preserves_existing_styles_and_method_contract(wording_build):
    item, model, run = wording_build
    item.wordings = [wording("conversational"), wording("autonomous")]
    output, checks = run([item])
    result = output[0]
    assert result.wordings[:2] == item.wordings
    assert result.model_dump(exclude={"wordings"}) == item.model_dump(exclude={"wordings"})
    assert result.wordings[2].style == "simple" and result.wordings[2].semantic_checked
    assert not result.wordings[2].validation_issues
    assert list(model.calls[0][1]["requested_styles"]) == ["simple"]
    assert len(model.calls) == 2 and not any(value["issues"] for value in checks)


def test_rejected_rewrite_retains_existing_text(wording_build):
    item, model, run = wording_build
    item.wordings = [wording("conversational"), wording(checked=False)]
    model.steps = ["自己用5分钟说说担心。"]
    model.issues = ["prerequisite_missing", "executor_changed"]
    output, checks = run([item])
    assert output == [item]
    assert set(checks[0]["issues"]) == set(model.issues)
    assert checks[-1]["missing_styles"] == ["simple"]


def test_numeric_change_is_rejected_even_if_model_approves(wording_build):
    item, model, run = wording_build
    model.steps = ["和成人一起，用2分钟说出你的担心。"]
    output, checks = run([item])
    assert not output[0].wordings
    assert "numeric_values_changed" in checks[0]["issues"]


def test_one_unavailable_check_preserves_partial_results_without_service_details(wording_build, capsys):
    item, model, run = wording_build
    failed = item.model_copy(update={"knowledge_id": "failed", "wordings": [wording("conversational")]})
    model.fail_id = "failed"
    output, checks = run([failed, item])
    assert output[0] == failed and output[1].wordings[0].style == "simple"
    assert sum(payload["item"]["knowledge_id"] == "failed" for schema, payload in model.calls
               if schema is adapt.WordingBatch) == 2
    assert any(value["issues"] == ["wording_check_unavailable"] for value in checks)
    assert "private-service-detail" not in json.dumps(checks) + capsys.readouterr().out


def test_source_digest_mismatch_cannot_generate_wording(wording_build):
    item, model, run = wording_build
    item.source_digest = "invalid"
    output, checks = run([item])
    assert output == [item] and not model.calls
    assert checks[0]["issues"] == ["source_digest_mismatch"]


@pytest.mark.parametrize("style", ["simple", "conversational", "autonomous"])
def test_runtime_knowledge_has_verified_text_for_every_usable_method(style):
    items = load_knowledge()
    usable = [item for item in items if item.status == "usable"]
    assert usable
    for item in usable:
        versions = [value for value in item.wordings if value.style == style and adapt.approved(value)]
        assert len(versions) == 1, (item.knowledge_id, style)
        assert adapt.numeric_values(versions[0].steps) == adapt.numeric_values(item.steps), (item.knowledge_id, style)
    assert not any("editorial_review_pending" in item.validation_issues for item in items)
