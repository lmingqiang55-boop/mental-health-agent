"""Live synthetic three-stage/four-scene API acceptance and replayable evidence.

Each case uses the actual evaluation API and an isolated MemoryStore. No normal
student records are modified. Passing checks do not establish clinical efficacy.
"""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.api import assessment, healing
from backend.core.memory_store import MemoryStore
from backend.core.session_manager import session_manager
from backend.healing.agent import HealingAgent
from backend.healing.client import HealingUnavailable
from backend.healing.store import HealingStore
from backend.main import app


class DiagnosticAgent(HealingAgent):
    """Keep safe failure reasons in local acceptance diagnostics only."""
    last_error = None
    last_draft = None

    async def start(self, *args, **kwargs):
        try:
            return await super().start(*args, **kwargs)
        except HealingUnavailable as exc:
            self.last_error = str(exc)
            self.last_draft = getattr(exc, "draft", None)
            raise

    async def reply(self, *args, **kwargs):
        try:
            return await super().reply(*args, **kwargs)
        except HealingUnavailable as exc:
            self.last_error = str(exc)
            self.last_draft = getattr(exc, "draft", None)
            raise


def main(args):
    args.work_dir.mkdir(parents=True, exist_ok=True)
    assessment.memory_store = healing.memory_store = MemoryStore(args.work_dir / "scenarios.sqlite3")
    healing.healing_store = HealingStore()
    healing.healing_agent = DiagnosticAgent()
    client = TestClient(app)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        if args.case and case["id"] not in args.case:
            continue
        row = {"case": case, "synthetic_data": True, "requests": [], "responses": [], "checks": {}}
        healing.healing_agent.last_error = None
        healing.healing_agent.last_draft = None
        def call(path, payload):
            started = perf_counter()
            response = client.post(path, json=payload)
            row["requests"].append({"path": path, "payload": payload, "status": response.status_code,
                                     "elapsed_ms": (perf_counter()-started)*1000})
            row["responses"].append(response.json())
            if response.status_code != 200:
                raise RuntimeError(response.json().get("error", {}).get("code", "request_failed"))
            return response.json()
        try:
            sid = client.post("/api/session").json()["session_id"]
            grade = {"primary": "四年级", "middle": "初一", "high": "高一"}[case["school_stage"]]
            evaluation = call("/api/assessment", {"session_id": sid, "evaluation_input": {
                "dialogue_history": [{"role": "user", "content": f"我{case['age']}岁，读{grade}。{case['concern']}。平时正常上学和吃饭。"}]}})["result"]
            before = session_manager.get_session(sid)
            stored_before = assessment.memory_store.list_by_student(before.student_ref)
            request = {"session_id": sid, "request_id": str(uuid4()), "background": {
                "current_concern": case["concern"],
                "adult_support_available": True}}
            initial = call("/api/healing/start", request)
            state = healing.healing_store.slot(sid).state
            assert state.scene == case["scene"]
            assert state.memory.background.age == case["age"]
            assert state.memory.background.school_stage == case["school_stage"] and state.memory.assessment.grade == grade
            assert initial["assessment_result_id"] == evaluation["result_id"]
            assert 1 <= len(initial["report"]["suggestions"]) <= 2
            assert initial["report"]["question"] and initial["report"]["question"].count("？") <= 1
            assert call("/api/healing/start", request) == initial
            for suggestion in state.suggestions:
                hit = HealingAgent.prior_hits(state)[suggestion.knowledge_id]
                valid_steps = [hit.item.steps, *[wording.steps for wording in hit.item.wordings
                               if wording.semantic_checked and not wording.validation_issues]]
                assert suggestion.steps in valid_steps
                assert set(hit.item.prerequisites) <= set(suggestion.prerequisites)
            for text in ["第一个方法还没试", "第一个方法我试了，但是没有帮助"]:
                payload = {"session_id": sid, "healing_id": initial["healing_id"], "message_id": str(uuid4()), "text": text}
                response = call("/api/healing/chat", payload)
                assert call("/api/healing/chat", payload) == response
            state = healing.healing_store.slot(sid).state
            assert state.suggestions[0].execution == "attempted" and state.suggestions[0].effect == "ineffective"
            assert not state.suggestions[0].active
            assert len([suggestion for suggestion in state.suggestions if suggestion.active]) <= 2
            pause = call("/api/healing/chat", {"session_id": sid, "healing_id": initial["healing_id"],
                "message_id": str(uuid4()), "text": "先暂停"})
            assert pause["status"] == "paused" and pause["report"]["question"] is None
            assert session_manager.get_session(sid) == before
            assert assessment.memory_store.list_by_student(before.student_ref) == stored_before
            student_json = json.dumps(row["responses"], ensure_ascii=False)
            assert "knowledge_id" not in student_json and "source_url" not in student_json
            row["checks"] = {"assessment_binding": True, "expected_scene": True, "grounded_steps": True,
                "conditions_preserved": True, "retry_idempotency": True, "explicit_feedback": True,
                "pause": True, "screening_unchanged": True, "sources_hidden": True, "demographics_from_memory": True}
            row["memory"] = state.memory.model_dump(mode="json")
            row["suggestions"] = [item.model_dump(mode="json") for item in state.suggestions]
            row["feedback"] = [item.model_dump(mode="json") for item in state.feedback]
            row["audit"] = state.audit
            row["memory_update_suggestions"] = state.memory_update_suggestions
            row["passed"] = True
        except Exception as exc:
            row["passed"] = False
            row["error"] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            row["diagnostic"] = healing.healing_agent.last_error
            row["invalid_draft"] = healing.healing_agent.last_draft
        results.append(row)
        (args.work_dir / (case["id"] + ".json")).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"id": case["id"], "passed": row["passed"], "error": row.get("error"),
                          "checks": row["checks"]}, ensure_ascii=False), flush=True)
    summary = {"passed": sum(row["passed"] for row in results), "total": len(results)}
    (args.work_dir / "scenario_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path("tests/fixtures/healing_support_cases.json"))
    parser.add_argument("--case", action="append")
    raise SystemExit(main(parser.parse_args()))
