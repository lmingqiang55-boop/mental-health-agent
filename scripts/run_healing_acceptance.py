"""Run the live assessment-to-healing cases with isolated data and usage evidence."""

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.healing_validation_runtime import ValidationRuntime


def main(args):
    # Isolation must precede API imports, which create the default MemoryStore.
    runtime = ValidationRuntime(args.work_dir)
    from scripts import validate_healing_scenarios as scenarios

    results = []
    try:
        for case in json.loads(args.cases.read_text(encoding="utf-8")):
            if args.case and case["id"] not in args.case:
                continue
            runtime.case_id = case["id"]
            scenarios.main(SimpleNamespace(work_dir=runtime.work, cases=args.cases, case=[case["id"]]))
            results.append(json.loads((runtime.work / (case["id"] + ".json")).read_text(encoding="utf-8")))
        summary = {"total": len(results), "passed": sum(row["passed"] for row in results)}
        (runtime.work / "scenario_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary), flush=True)
    finally:
        print(json.dumps(runtime.finish(), ensure_ascii=False), flush=True)
    return 0 if results and all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=PROJECT / "tests/fixtures/healing_support_cases.json")
    parser.add_argument("--case", action="append")
    raise SystemExit(main(parser.parse_args()))
