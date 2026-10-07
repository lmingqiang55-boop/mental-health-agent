"""Fresh synthetic live API cases for saved demographics and interaction edges.

Uses the real assessment and healing model clients, the full current knowledge
base and isolated SQLite. No model output or knowledge selection is stubbed.
"""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.healing_validation_runtime import ValidationRuntime

CASES = [
    {"id": "no-background", "assessment": "最近有一点考试压力，平时正常上学吃饭。", "age": None, "stage": None, "background": None, "methods": False},
    {"id": "unknown-age-no-adult", "assessment": "最近有一点考试压力，平时正常上学吃饭。", "age": None, "stage": None, "concern": "想聊考试压力", "methods": False},
    {"id": "grade-only-middle-sleep", "assessment": "我读初二，最近晚睡，平时正常上学吃饭。", "age": None, "stage": "middle", "concern": "想聊睡眠，最近睡得晚", "methods": False},
    {"id": "grade-only-primary-sleep", "assessment": "我读四年级，最近晚睡，平时正常上学吃饭。", "age": None, "stage": "primary", "concern": "想聊睡眠，睡前一直看屏幕", "methods": True},
    {"id": "age-only-thirteen", "assessment": "我13岁，最近有一点考试压力，平时正常上学吃饭。", "age": 13, "stage": None, "concern": "想聊考试压力，想安排好学习时间", "methods": True},
    {"id": "lower-age-six", "assessment": "我6岁，读一年级，最近有点难过，平时正常上学吃饭。", "age": 6, "stage": "primary", "concern": "想聊心情，最近有点难过", "methods": True},
    {"id": "upper-age-eighteen", "assessment": "我18岁，读高三，最近晚睡，平时正常上学吃饭。", "age": 18, "stage": "high", "concern": "想聊睡眠，最近睡得晚", "methods": True},
    {"id": "latest-age-missing", "older": "我16岁，读高一，最近晚睡，平时正常上学吃饭。", "assessment": "我读初二，最近晚睡，平时正常上学吃饭。", "age": None, "stage": "middle", "concern": "想聊睡眠，最近睡得晚", "methods": False},
    {"id": "reopened-record-new-session", "assessment": "我16岁，读高一，最近与同学意见不一致，平时正常上学吃饭。", "age": 16, "stage": "high", "concern": "想聊人际关系，和同学意见不一致", "methods": True, "action": "reopen"},
    {"id": "topic-refusal-then-end", "assessment": "我16岁，读高一，最近有一点考试压力，平时正常上学吃饭。", "age": 16, "stage": "high", "concern": "想聊考试压力", "methods": True, "action": "topic"},
    {"id": "two-method-local-simplification", "assessment": "我13岁，读初二，最近有一点考试压力，平时正常上学吃饭。", "age": 13, "stage": "middle", "concern": "想聊考试压力，请给我两个不同的方法", "methods": True, "action": "simplify"},
    {"id": "two-method-negated-simplification", "assessment": "我16岁，读高一，最近晚睡，平时正常上学吃饭。", "age": 16, "stage": "high", "concern": "想聊睡眠，请给我两个不同的方法", "methods": True, "action": "no_simplify"},
    {"id": "two-method-different-feedback", "assessment": "我16岁，读高一，最近与同学意见不一致，平时正常上学吃饭。", "age": 16, "stage": "high", "concern": "想聊人际关系，请给我两个不同的方法", "methods": True, "action": "feedback"},
    {"id": "prepare-pause-resume", "assessment": "我13岁，读初二，最近有一点考试压力，平时正常上学吃饭。", "age": 13, "stage": "middle", "concern": "想聊考试压力，请给我两个不同的方法", "methods": True, "action": "resume"},
    {"id": "regenerate-latest-record", "assessment": "我14岁，读高一，最近有点难过，平时正常上学吃饭。", "age": 14, "stage": "high", "concern": "想聊心情，最近有点难过", "methods": True, "action": "regenerate"},
    {"id": "unknown-age-new-risk", "assessment": "最近有一点考试压力，平时正常上学吃饭。", "age": None, "stage": None, "concern": "想聊考试压力", "methods": False, "action": "risk"},
    # Synonym recall now provides verified student methods without adult support.
    # Keep the historical case ID for comparison with saved replays.
    {"id": "child-conflict-no-adult-fallback", "assessment": "我10岁，读四年级，最近和同学意见不一致，平时正常上学吃饭。", "age": 10, "stage": "primary", "concern": "想聊人际关系，和同学意见不一致", "methods": True},
    {"id": "specific-context-local-simplification", "assessment": "我13岁，读初二，快考试了，复习时担心成绩不好，学习压力很大，平时正常上学吃饭。", "age": 13, "stage": "middle", "concern": "快考试了，复习时担心成绩不好，学习压力很大", "methods": True, "action": "simplify"},
    {"id": "specific-context-negated-simplification", "assessment": "我16岁，读高一，晚上在床上看手机，经常晚睡，平时正常上学吃饭。", "age": 16, "stage": "high", "concern": "晚上在床上看手机，经常晚睡，我想先聊睡眠习惯", "methods": True, "action": "no_simplify"},
    {"id": "specific-context-prepare-pause-resume", "assessment": "我13岁，读初二，快考试了，复习时担心成绩不好，学习压力很大，平时正常上学吃饭。", "age": 13, "stage": "middle", "concern": "快考试了，复习时担心成绩不好，学习压力很大", "methods": True, "action": "resume"},
]


def main(args):
    runtime = ValidationRuntime(args.work_dir)
    from fastapi.testclient import TestClient
    from backend.api import assessment, healing
    from backend.core.memory_store import MemoryStore
    from backend.core.session_manager import session_manager
    from backend.healing.knowledge import load_knowledge
    from backend.healing.retriever import age_match
    from backend.healing.store import HealingStore
    from backend.main import app
    from scripts.validate_healing_scenarios import DiagnosticAgent

    db = runtime.work / "current.sqlite3"
    assessment.memory_store = healing.memory_store = MemoryStore(db)
    healing.healing_store, healing.healing_agent = HealingStore(), DiagnosticAgent()
    client = TestClient(app)
    knowledge = {item.knowledge_id: item for item in load_knowledge()}
    results = []
    try:
        for case in CASES:
            if args.case and case["id"] not in args.case:
                continue
            runtime.case_id = case["id"]
            row = {"case": case, "synthetic_data": True, "assessment_stubbed": False,
                   "knowledge_items": len(knowledge), "requests": [], "checks": {}}
            sid = None
            healing.healing_agent.last_error = None
            healing.healing_agent.last_draft = None

            def check(name, condition):
                row["checks"][name] = bool(condition)
                if not condition:
                    raise AssertionError(name)

            def call(path, payload=None, *, get=False, expected=200):
                started = perf_counter()
                response = client.get(path) if get else client.post(path, json=payload)
                row["requests"].append({"path": path, "method": "GET" if get else "POST",
                    "payload": payload, "status": response.status_code, "response": response.json(),
                    "elapsed_ms": (perf_counter() - started) * 1000})
                check("http:" + str(len(row["requests"])), response.status_code == expected)
                return response.json()

            def evaluate(text):
                return call("/api/assessment", {"session_id": sid, "evaluation_input": {
                    "dialogue_history": [{"role": "user", "content": text}]}})["result"]

            def chat(text, expected=200):
                payload = {"session_id": sid, "healing_id": initial["healing_id"],
                           "message_id": str(uuid4()), "text": text}
                response = call("/api/healing/chat", payload, expected=expected)
                calls_before_retry = len(runtime.calls)
                retry = call("/api/healing/chat", payload, expected=expected)
                check("chat_retry:" + text, retry == response and len(runtime.calls) == calls_before_retry)
                return response

            try:
                sid = call("/api/session")["session_id"]
                if "older" in case:
                    evaluate(case["older"])
                evaluation = evaluate(case["assessment"])
                if case.get("action") == "reopen":
                    sid = call("/api/session", {"student_ref": evaluation["student_ref"]})["session_id"]
                    healing.memory_store = MemoryStore(db)
                session_before = session_manager.get_session(sid)
                stored_before = healing.memory_store.list_by_student(evaluation["student_ref"])
                request = {"session_id": sid, "request_id": str(uuid4())}
                if case.get("background", "present") is not None:
                    request["background"] = {"current_concern": case.get("concern"), "adult_support_available": False}
                initial = call("/api/healing/start", request)
                start_calls = len(runtime.calls)
                check("start_retry", call("/api/healing/start", request) == initial and len(runtime.calls) == start_calls)
                before = healing.healing_store.slot(sid).state.model_copy(deep=True)
                check("saved_demographics", before.memory.background.age == case["age"] and before.memory.background.school_stage == case["stage"])
                check("assessment_binding", initial["assessment_result_id"] == evaluation["result_id"])
                check("method_availability", bool(before.suggestions) == case["methods"])
                check("missing_other_background", all(not getattr(before.memory.background, key)
                    for key in ("preferences", "constraints", "important_events", "previous_attempts")))
                if case.get("action") == "reopen":
                    check("no_invented_session_history", before.memory.current_session_messages == [])

                action = case.get("action")
                if action in {"simplify", "no_simplify", "feedback", "resume"}:
                    check("two_methods_exercised", len(before.suggestions) == 2)
                if action == "topic":
                    response = chat("我不想聊睡眠，只想聊考试压力")
                    check("topic_refusal_continues", response["status"] == "active" and healing.healing_store.slot(sid).state.scene == "study_stress")
                    count = len(runtime.calls)
                    response = chat("我不想聊了，结束吧")
                    check("end_without_model", response["status"] == "ended" and len(runtime.calls) == count)
                elif action == "simplify":
                    response = chat("第一个方法的这段话太复杂，能用简单的话说吗；第二个方法我看得懂，不用改")
                    after = healing.healing_store.slot(sid).state
                    first, second = after.suggestions[:2]
                    check("only_first_reworded", first.revisions != before.suggestions[0].revisions and second == before.suggestions[1])
                    check("simplification_identity", first.suggestion_id == before.suggestions[0].suggestion_id and first.knowledge_id == before.suggestions[0].knowledge_id
                        and first.prerequisites == before.suggestions[0].prerequisites and first.cautions == before.suggestions[0].cautions)
                    check("simplification_not_feedback", after.feedback == before.feedback)
                elif action == "no_simplify":
                    chat("第一个方法并不复杂，先别改；第二个方法也看得懂，不用改")
                    after = healing.healing_store.slot(sid).state
                    check("negated_requests_keep_methods", after.suggestions[:2] == before.suggestions)
                elif action == "feedback":
                    chat("第一个方法我试了，有帮助；第二个方法我试了，没有帮助")
                    after = healing.healing_store.slot(sid).state
                    check("separate_feedback", [(item.effect, item.active) for item in after.suggestions[:2]] == [("helpful", True), ("ineffective", False)])
                    check("both_feedback_saved_once", len(after.feedback) == 2 and {item.suggestion_id for item in after.feedback} == {item.suggestion_id for item in before.suggestions})
                elif action == "resume":
                    chat("第二个方法我准备试试")
                    prepared = healing.healing_store.slot(sid).state.model_copy(deep=True)
                    check("second_only_prepared", [item.execution for item in prepared.suggestions[:2]] == ["unconfirmed", "prepared"])
                    count = len(runtime.calls)
                    paused = chat("先暂停")
                    check("pause_without_model", paused["status"] == "paused" and len(runtime.calls) == count)
                    resumed = chat("我们继续聊考试压力，第二个方法还没试")
                    after = healing.healing_store.slot(sid).state
                    check("resume_keeps_identity", resumed["status"] == "active" and after.suggestions[1].suggestion_id == before.suggestions[1].suggestion_id)
                    check("resume_keeps_prepared", after.suggestions[1].execution == "prepared" and after.suggestions[1].effect == "unknown")
                    new_feedback = [item for item in after.feedback if item.turn == after.turn_count]
                    check("resume_saves_not_attempted_once", len(new_feedback) == 1
                        and new_feedback[0].suggestion_id == after.suggestions[1].suggestion_id
                        and new_feedback[0].execution == "not_attempted"
                        and new_feedback[0].evidence in "我们继续聊考试压力，第二个方法还没试")
                    updates = [entry for entry in after.memory_update_suggestions
                               if entry["kind"] == "support_feedback" and entry["value"]["turn"] == after.turn_count]
                    check("resume_feedback_update_once", len(updates) == 1 and updates[0]["persisted"] is False)
                    check("resume_no_false_reference_question", "你说的是刚才哪一个方法" not in after.messages[-1].content)
                elif action == "regenerate":
                    latest = evaluate("我18岁，读高三，最近晚睡，平时正常上学吃饭。")
                    current = call("/api/healing/" + sid, get=True)
                    check("old_binding_until_regenerate", current["assessment_result_id"] == evaluation["result_id"])
                    regenerated = call("/api/healing/start", {"session_id": sid, "request_id": str(uuid4()),
                        "regenerate": True, "expected_healing_id": initial["healing_id"],
                        "background": {"current_concern": "想聊睡眠，最近睡得晚", "adult_support_available": False}})
                    after = healing.healing_store.slot(sid).state
                    check("regenerate_latest_demographics", regenerated["assessment_result_id"] == latest["result_id"] and after.memory.background.age == 18 and after.memory.background.school_stage == "high")
                    check("stale_chat_rejected", call("/api/healing/chat", {"session_id": sid, "healing_id": initial["healing_id"], "message_id": str(uuid4()), "text": "还没试"}, expected=409)["error"]["code"] == "HEALING_STATE_CHANGED")
                    session_before = session_manager.get_session(sid)
                    stored_before = healing.memory_store.list_by_student(evaluation["student_ref"])
                elif action == "risk":
                    count = len(runtime.calls)
                    response = chat("我想伤害自己，而且已经准备好了")
                    check("unknown_age_risk_without_model", response["status"] == "referred" and not response["report"]["suggestions"] and len(runtime.calls) == count)
                else:
                    chat("先暂停")

                state = healing.healing_store.slot(sid).state
                check("screening_and_records_unchanged", session_manager.get_session(sid) == session_before and healing.memory_store.list_by_student(evaluation["student_ref"]) == stored_before)
                check("active_method_limit", sum(item.active for item in state.suggestions) <= 2)
                for suggestion in state.suggestions:
                    item = knowledge[suggestion.knowledge_id]
                    check("hard_conditions:" + suggestion.suggestion_id, item.status == "usable" and item.semantic_checked
                        and not item.validation_issues and item.executor == "student" and age_match(item, state.memory.background) is not None)
                    check("grounding:" + suggestion.suggestion_id, suggestion.steps in [item.steps, *[value.steps for value in item.wordings if value.semantic_checked and not value.validation_issues]]
                        and set(item.prerequisites) <= set(suggestion.prerequisites))
                check("internal_sources_hidden", not any(key in json.dumps([item["response"] for item in row["requests"] if "/healing" in item["path"]])
                    for key in ("knowledge_id", "source_url", "method_key")))
                row.update(passed=True, outcome="passed", final_state=state.model_dump(mode="json"))
            except Exception as exc:
                state = healing.healing_store.slot(sid).state if sid is not None else None
                row.update(passed=False, error_type=type(exc).__name__, failed_check=str(exc) if isinstance(exc, AssertionError) else None,
                    outcome="not_exercised" if isinstance(exc, AssertionError) and str(exc) == "two_methods_exercised" else "failed",
                    diagnostic=healing.healing_agent.last_error, invalid_draft=healing.healing_agent.last_draft,
                    final_state=state.model_dump(mode="json") if state else None)
            results.append(row)
            (runtime.work / (case["id"] + ".json")).write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"id": case["id"], "passed": row["passed"], "failed_check": row.get("failed_check"), "diagnostic": row.get("diagnostic")}, ensure_ascii=False), flush=True)
        summary = {"passed": sum(row["passed"] for row in results), "total": len(results),
                   "assessment_stubbed": False, "knowledge_items": len(knowledge)}
        (runtime.work / "current_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    finally:
        print(json.dumps(runtime.finish(), ensure_ascii=False), flush=True)
    return 0 if results and all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--case", action="append")
    raise SystemExit(main(parser.parse_args()))
