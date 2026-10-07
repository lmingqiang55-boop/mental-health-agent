"""Live synthetic goal confirmation, grounded simplification and explanations."""

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.api import assessment, healing
from backend.core.memory_store import MemoryStore
from backend.healing.store import HealingStore
from backend.main import app
from scripts.validate_healing_scenarios import DiagnosticAgent


def main(args):
    args.work_dir.mkdir(parents=True, exist_ok=True)
    assessment.memory_store = healing.memory_store = MemoryStore(args.work_dir / "interactions.sqlite3")
    healing.healing_store, healing.healing_agent = HealingStore(), DiagnosticAgent()
    client = TestClient(app)
    cases = [
        ("goal_confirmation", {"age": 12, "school_stage": "middle", "current_concern": "我考试紧张，也总是晚睡"}),
        ("grounded_simplification", {"age": 16, "school_stage": "high", "current_concern": "明天考试，我担心考不好"}),
        ("explanation_context", {"age": 12, "school_stage": "middle", "current_concern": "开学上课时身体难受，我想先聊学习压力"}),
        ("previous_attempt_filter", {"age": 16, "school_stage": "high", "current_concern": "想先聊考试压力，腹式呼吸练习我试过没有帮助",
            "previous_attempts": ["腹式呼吸练习我试过，但没有帮助"], "preferences": ["更愿意和可信成人说清楚困扰"]}),
    ]
    results = []
    for name, background in cases:
        if args.case and name not in args.case:
            continue
        row = {"id": name, "synthetic_data": True, "requests": [], "responses": []}
        def call(path, payload):
            response = client.post(path, json=payload)
            row["requests"].append({"path": path, "payload": payload, "status": response.status_code})
            row["responses"].append(response.json())
            assert response.status_code == 200, response.json()
            return response.json()
        try:
            sid = client.post("/api/session").json()["session_id"]
            grade = {"primary": "四年级", "middle": "初一", "high": "高一"}[background["school_stage"]]
            call("/api/assessment", {"session_id": sid, "evaluation_input": {"dialogue_history": [
                {"role": "user", "content": f"我{background['age']}岁，读{grade}。我平时正常上学吃饭，没有安全危险。"
                 + background["current_concern"]}]}})
            response = call("/api/healing/start", {"session_id": sid, "request_id": str(uuid4()),
                "background": {**{key: value for key, value in background.items() if key not in {"age", "school_stage"}},
                               "adult_support_available": True}})
            before = healing.healing_store.slot(sid).state.model_copy(deep=True)
            assert before.memory.background.age == background["age"]
            assert before.memory.background.school_stage == background["school_stage"] and before.memory.assessment.grade == grade
            if name == "goal_confirmation":
                assert before.goal.needs_confirmation and not before.suggestions
                call("/api/healing/chat", {"session_id": sid, "healing_id": response["healing_id"],
                    "message_id": str(uuid4()), "text": "现在先聊考试压力"})
                current = healing.healing_store.slot(sid).state
                assert current.scene == "study_stress" and not current.goal.needs_confirmation and current.suggestions
            elif name == "grounded_simplification":
                assert before.suggestions
                target = before.suggestions[0]
                call("/api/healing/chat", {"session_id": sid, "healing_id": response["healing_id"],
                    "message_id": str(uuid4()), "text": "第一个方法的这段话太复杂，可以用更简单的话说吗"})
                current = healing.healing_store.slot(sid).state
                changed = current.suggestions[0]
                assert changed.suggestion_id == target.suggestion_id and changed.knowledge_id == target.knowledge_id
                assert changed.prerequisites == target.prerequisites and changed.cautions == target.cautions
                assert changed.revisions and not current.feedback
            elif name == "explanation_context":
                assert any(event.get("explanations") for event in before.audit)
                current = before
            else:
                assert before.suggestions and all(item.method_key != "belly_breathing" for item in before.suggestions)
                assert any(event.get("context_removed") for event in before.audit)
                assert not before.feedback
                current = before
            row.update(passed=True, memory=current.memory.model_dump(mode="json"), audit=current.audit,
                suggestions=[item.model_dump(mode="json") for item in current.suggestions],
                feedback=[item.model_dump(mode="json") for item in current.feedback],
                memory_update_suggestions=current.memory_update_suggestions)
        except Exception as exc:
            row.update(passed=False, error=type(exc).__name__, diagnostic=healing.healing_agent.last_error,
                       invalid_draft=healing.healing_agent.last_draft)
        results.append(row)
        print(json.dumps({"id": name, "passed": row["passed"], "diagnostic": row.get("diagnostic")}, ensure_ascii=False), flush=True)
    (args.work_dir / "interaction_replays.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--case", action="append")
    raise SystemExit(main(parser.parse_args()))
