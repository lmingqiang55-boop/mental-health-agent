"""Compare an EmoLLM-window adapter and LangExtract on the same source sections.

The optional upstream loader is read from a pinned, separately downloaded file.
Only its get_txt_content function is evaluated; module initialization and file
cleanup helpers are never run. Original QA/Qwen code is not a support KB schema.
"""

import argparse
import ast
import asyncio
from datetime import date
from importlib.metadata import version
import json
from pathlib import Path
import re
import sys
from time import perf_counter
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.healing.client import HealingJSONClient
from backend.healing.knowledge import validate_item
from backend.llm.config import load_deepseek_config
from scripts.build_healing_knowledge import (
    EXTRACT_PROMPT, MANIFEST, Extracted, Extraction, Proof, allowed_section, check_semantics, grounded_item,
)


def load_emollm_window(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_txt_content")
    # The caller explicitly provides the pinned local upstream file.
    module = ast.Module(body=[definition], type_ignores=[])
    namespace = {"re": re, "List": list, "logger": SimpleNamespace(warning=lambda *args: None, error=lambda *args: None)}
    exec(compile(module, str(path.name), "exec"), namespace)
    return namespace["get_txt_content"]


async def main(args):
    sys.path.insert(0, str(args.research_deps))
    import langextract as lx
    from langextract.factory import ModelConfig
    args.work_dir.mkdir(parents=True, exist_ok=True)
    sources = json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"]
    selected = [source for source in sources if source["source_id"] in args.source]
    config = load_deepseek_config()
    emollm_window = load_emollm_window(args.emollm_loader)
    result = {"model": config.model, "langextract_version": version("langextract"),
        "emollm_scope": "pinned get_txt_content + project DeepSeek/schema adapter; not original Qwen QA application",
        "cases": []}
    example_text = "本节适用于儿童。在成人指导下说出困扰。"
    example_attrs = {"title": "说出困扰", "goal": "说明困扰", "method_key": "name_concern", "audience": "children",
        "executor": "adult_guided", "steps_json": '["在成人指导下说出困扰。"]',
        "prerequisites_json": '["成人指导"]', "audience_quote": "本节适用于儿童", "executor_quote": "在成人指导下",
        "prerequisites_quote": "在成人指导下"}
    examples = [lx.data.ExampleData(text=example_text, extractions=[lx.data.Extraction(
        extraction_class="support_method", extraction_text="在成人指导下说出困扰。", attributes=example_attrs)])]
    for source in selected:
        text = (args.work_dir / (source["source_id"] + ".txt")).read_text(encoding="utf-8")
        scope = allowed_section(text, source)
        contexts = []
        for anchor in [source["audience_context"], *source.get("extra_context", [])]:
            at = text.find(anchor)
            if at >= 0:
                contexts.append((max(0, at-80), min(len(text), at+300)))
        context = "\n".join(text[low:high] for low, high in contexts)
        section = text[scope[0]:scope[1]]
        source_file = args.work_dir / (source["source_id"] + ".comparison-section.txt")
        source_file.write_text(section, encoding="utf-8")
        started = perf_counter()
        windows = emollm_window(str(source_file))
        row = {"source_id": source["source_id"], "section_chars": len(section), "emollm": {
            "window_count": len(windows), "window_ms": (perf_counter()-started)*1000,
            "whitespace_removed": windows[0] != section if windows else True}, "langextract": {}}
        for mode in ["emollm", "langextract"]:
            started = perf_counter()
            entries = []
            try:
                if mode == "emollm":
                    for window in windows[:2]:
                        extracted = await HealingJSONClient().generate(EXTRACT_PROMPT + "本次最多抽2条完整方法。", {
                            "source_text": window, "context": context,
                            "supplied_scenes": source.get("scenes", ["sleep"] if source["source_id"] == "pku-sleep" else ["study_stress"]),
                            "allowed_topics": source["allowed_topics"], "excluded_topics": source["excluded_topics"],
                            "output_schema": Extraction.model_json_schema()}, Extraction, max_tokens=3500)
                        entries.extend(extracted.items)
                else:
                    extracted = await asyncio.to_thread(lx.extract, text_or_documents=context + "\n" + section,
                        prompt_description="提取最多2条完整的日常心理支持方法，逐字引用原文活动作为extraction_text。"
                        "attributes含title/goal中文、method_key英文、audience(children/children_adolescents/adolescents/unspecified)、"
                        "executor(student/adult_guided/adult/unspecified)、steps_json与prerequisites_json（中文字符串数组的JSON字符串）、"
                        "audience_quote/executor_quote/prerequisites_quote（短的逐字原文）。年龄未明不补数字。"
                        "保留原文全部必要前提，成人任务不转给学生。不把背景声明当作方法正文。允许主题：" + source["allowed_topics"] +
                        "；排除主题：" + source["excluded_topics"], examples=examples,
                        config=ModelConfig(model_id=config.model, provider="openai", provider_kwargs={"api_key": config.api_key, "base_url": config.base_url}),
                        use_schema_constraints=False, max_char_buffer=7000, show_progress=False,
                        language_model_params={"max_output_tokens": 3500})
                    row[mode]["located_intervals"] = sum(value.char_interval is not None for value in extracted.extractions)
                    row[mode]["attribute_checks"] = []
                    for value in extracted.extractions:
                        if value.char_interval is None:
                            continue
                        attrs = value.attributes or {}
                        missing = {"title", "goal", "steps_json"} - attrs.keys()
                        row[mode]["attribute_checks"].append({"class": value.extraction_class,
                            "keys": sorted(attrs), "missing": sorted(missing)})
                        if missing:
                            continue
                        proofs = [Proof(field="steps", quote=value.extraction_text[:300])]
                        for field in ["audience", "executor", "prerequisites"]:
                            if attrs.get(field + "_quote"):
                                proofs.append(Proof(field=field, quote=attrs[field + "_quote"][:300]))
                        entries.append(Extracted(method_key=attrs.get("method_key", "unspecified"), title=attrs["title"],
                            goal=attrs["goal"], audience=attrs.get("audience", "unspecified"), executor=attrs.get("executor", "unspecified"),
                            purpose="method", scenes=source.get("scenes", ["sleep"] if source["source_id"] == "pku-sleep" else ["study_stress"]),
                            steps=json.loads(attrs["steps_json"]), prerequisites=json.loads(attrs.get("prerequisites_json", "[]")), evidence=proofs))
                checks = []
                for entry in entries:
                    try:
                        item = grounded_item(entry, source, text, scope, f"comparison:{date.today().isoformat()}", contexts)
                        issues = await check_semantics(HealingJSONClient(), item, text, scope, source, context)
                        checked = validate_item(item, text, [scope, *contexts], issues)
                        checks.append({"title": item.title, "status": checked.status, "issues": checked.validation_issues,
                                       "executor": item.executor, "age_min": item.age_min, "age_max": item.age_max})
                    except (ValueError, KeyError, TypeError) as exc:
                        checks.append({"status": "pending", "error": type(exc).__name__})
                row[mode].update({"extracted": len(entries), "usable": sum(check["status"] == "usable" for check in checks), "checks": checks})
            except Exception as exc:
                row[mode]["error"] = type(exc).__name__
            row[mode]["elapsed_ms"] = (perf_counter()-started)*1000
        result["cases"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (args.work_dir / "extraction_comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--research-deps", type=Path, required=True)
    parser.add_argument("--emollm-loader", type=Path, required=True)
    parser.add_argument("--source", action="append", default=[])
    args = parser.parse_args()
    if not args.source:
        args.source = ["unicef-anxiety", "pku-sleep", "nemours-kids-sleep"]
    asyncio.run(main(args))
