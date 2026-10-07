"""Recheck a built knowledge file against cached sources; preserve all diagnostics."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.healing.client import HealingJSONClient
from backend.healing.knowledge import load_knowledge, validate_item
from scripts.build_healing_knowledge import MANIFEST, allowed_section, check_semantics


async def main(args):
    sources = {source["source_id"]: source for source in json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"]}
    items = load_knowledge(args.input)
    semaphore = asyncio.Semaphore(2)
    diagnostics = []
    async def check(item):
        async with semaphore:
            source = sources[item.source_id]
            text = (args.work_dir / (item.source_id + ".txt")).read_text(encoding="utf-8")
            scope = allowed_section(text, source)
            contexts = []
            for anchor in [source["audience_context"], *source.get("extra_context", [])]:
                at = text.find(anchor)
                if at >= 0:
                    contexts.append((max(0, at-80), min(len(text), at+300)))
            details = []
            issues = await check_semantics(HealingJSONClient(), item, text, scope, source,
                                           "\n".join(text[low:high] for low, high in contexts), details)
            result = validate_item(item, text, [scope, *contexts], issues)
            # Wording checks are valid only while their underlying method is valid.
            if result.status != "usable":
                result.wordings = []
            diagnostics.append({"knowledge_id": result.knowledge_id, "source_id": result.source_id,
                "previous_status": item.status, "status": result.status, "issues": result.validation_issues, "details": details})
            print(json.dumps(diagnostics[-1], ensure_ascii=False), flush=True)
            return result
    checked = await asyncio.gather(*(check(item) for item in items))
    args.output.write_text("".join(item.model_dump_json()+"\n" for item in checked), encoding="utf-8")
    (args.work_dir / "revalidation.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": len(checked), "usable": sum(item.status == "usable" for item in checked)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
