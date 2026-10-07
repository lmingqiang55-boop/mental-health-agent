"""Live assessment -> actual MemoryStore -> support -> feedback, using synthetic data.

Requires the local model configuration. All results and the isolated SQLite DB
are written under --work-dir; the normal assessment database is not modified.
"""

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.api import assessment, healing
from backend.core.memory_store import MemoryStore
from backend.core.session_manager import session_manager
from backend.healing.store import HealingStore
from backend.healing.agent import HealingAgent
from backend.healing.client import HealingJSONClient
from backend.main import app


def main(work: Path):
    work.mkdir(parents=True, exist_ok=True)
    assessment.memory_store = healing.memory_store = MemoryStore(work / "smoke_memory.sqlite3")
    healing.healing_store = HealingStore()
    client = TestClient(app)
    output = {"synthetic_data": True, "requests": [], "checks": {}}

    class RecordedClient(HealingJSONClient):
        async def generate(self, system, payload, schema, **kwargs):
            result = await super().generate(system, payload, schema, **kwargs)
            output.setdefault("generation_checks", []).append({"schema": schema.__name__, "result": result.model_dump(mode="json")})
            return result

    healing.healing_agent = HealingAgent(client=RecordedClient())

    def call(path, payload):
        started = perf_counter()
        response = client.post(path, json=payload)
        output["requests"].append({"path": path, "status": response.status_code,
                                   "elapsed_ms": (perf_counter()-started)*1000})
        if response.status_code != 200:
            raise RuntimeError(response.json().get("error", {}).get("code", "request_failed"))
        return response.json()

    try:
        session = client.post("/api/session").json()
        sid = session["session_id"]
        assessment_result = call("/api/assessment", {"session_id": sid, "evaluation_input": {
            "dialogue_history": [{"role": "user", "content":
                "我16岁，是高一学生，明天考试，今天有点紧张，担心成绩不好。平时可以上学，吃饭睡觉也正常。"}]}})["result"]
        before = session_manager.get_session(sid)
        records = assessment.memory_store.list_by_student(before.student_ref)
        request = {"session_id": sid, "request_id": str(uuid4()), "background": {
            "current_concern": "明天考试，想到考不好就很紧张",
            "adult_support_available": True}}
        initial = call("/api/healing/start", request)
        output["initial"] = initial
        assert initial["assessment_result_id"] == assessment_result["result_id"]
        initial_memory = healing.healing_store.slot(sid).state.memory
        assert initial_memory.background.age == 16 and initial_memory.background.school_stage == "high"
        assert initial["report"]["suggestions"], "没有命中具体方法"
        assert call("/api/healing/start", request) == initial
        hid = initial["healing_id"]
        for text in ["第一个方法还没试", "第一个方法我试了，但没有帮助"]:
            turn = {"session_id": sid, "healing_id": hid, "message_id": str(uuid4()), "text": text}
            result = call("/api/healing/chat", turn)
            assert call("/api/healing/chat", turn) == result
        state = healing.healing_store.slot(sid).state
        assert any(item.execution == "attempted" and item.effect == "ineffective" for item in state.feedback)
        assert state.suggestions[0].active is False
        before_pause = [item.model_dump(mode="json") for item in state.feedback]
        call("/api/healing/chat", {"session_id": sid, "healing_id": hid,
                                   "message_id": str(uuid4()), "text": "先暂停"})
        state = healing.healing_store.slot(sid).state
        assert state.status == "paused"
        assert [item.model_dump(mode="json") for item in state.feedback] == before_pause
        assert session_manager.get_session(sid) == before
        assert assessment.memory_store.list_by_student(before.student_ref) == records
        assert "knowledge_id" not in json.dumps(initial) and "source_url" not in json.dumps(initial)
        output["checks"] = {"assessment_binding": True, "grounded_methods": True, "retry_idempotency": True,
                            "explicit_feedback": True, "pause": True, "screening_unchanged": True,
                            "persistent_records_unchanged": True, "student_sources_hidden": True,
                            "demographics_from_memory": True}
        output["memory"] = state.memory.model_dump(mode="json")
        output["suggestions"] = [item.model_dump(mode="json") for item in state.suggestions]
        output["feedback"] = [item.model_dump(mode="json") for item in state.feedback]
        output["audit"] = state.audit
        output["memory_update_suggestions"] = state.memory_update_suggestions
        output["final"] = client.get(f"/api/healing/{sid}").json()
        other = client.post("/api/session").json()["session_id"]
        call("/api/assessment", {"session_id": other, "evaluation_input": {
            "dialogue_history": [{"role": "user", "content": "最近有点考试压力，平时上学吃饭睡觉正常。"}]}})
        unknown = call("/api/healing/start", {"session_id": other, "request_id": str(uuid4()), "background": {}})
        assert unknown["report"]["suggestions"] == []
        unknown_memory = healing.healing_store.slot(other).state.memory
        assert unknown_memory.background.age is None and unknown_memory.background.school_stage is None
        output["unknown_background"] = unknown
        output["checks"]["missing_background_fallback"] = True
        output["success"] = True
    except Exception as exc:
        output["success"] = False
        output["error"] = str(exc) if type(exc) is RuntimeError else type(exc).__name__
    (work / "live_smoke.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: output[key] for key in ["success", "requests", "checks"]}, ensure_ascii=False))
    return 0 if output["success"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    raise SystemExit(main(parser.parse_args().work_dir))
