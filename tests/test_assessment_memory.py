"""A pseudonymous student keeps only the latest three results across sessions."""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.api import assessment, history, teacher
from backend.core.memory_store import MemoryStore
from backend.main import app
from backend.models.evaluation import EvaluationResult


client = TestClient(app)


def test_session_returns_reusable_anonymous_student_ref():
    first = client.post("/api/session").json()
    second = client.post("/api/session", json={"student_ref": first["student_ref"]}).json()

    assert first["session_id"] != second["session_id"]
    assert first["student_ref"] == second["student_ref"]
    assert client.get(f"/api/session/{second['session_id']}").json()[
        "student_ref"
    ] == first["student_ref"]


def test_last_three_results_survive_restart_and_keep_follow_up_notes(
    tmp_path, monkeypatch, evaluation_stub,
):
    db_path = tmp_path / "evaluation_memory.sqlite3"
    store = MemoryStore(db_path)
    monkeypatch.setattr(assessment, "memory_store", store)
    monkeypatch.setattr(history, "memory_store", store)
    monkeypatch.setattr(teacher, "memory_store", store)
    student_ref = str(uuid4())
    result_ids = []

    for number in range(4):
        session = client.post(
            "/api/session", json={"student_ref": student_ref}
        ).json()
        response = client.post("/api/assessment", json={
            "session_id": session["session_id"],
            "evaluation_input": {"dialogue_history": [
                {"role": "user", "content": f"第 {number + 1} 次评估"}
            ]},
        })
        assert response.status_code == 200, response.json()
        result_ids.append(response.json()["result"]["result_id"])

    records = client.get(f"/api/history/{student_ref}").json()["records"]
    assert [item["result"]["result_id"] for item in records] == result_ids[1:]
    assert store.get_record_by_result_id(result_ids[0]) is None

    latest = EvaluationResult.model_validate(records[-1]["result"])
    assert store.save_result(latest).record_id == records[-1]["record_id"]
    updated = store.add_counselor_note(records[-1]["record_id"], "teacher", "已跟进")
    assert updated.counselor_notes[0].content == "已跟进"

    reopened = MemoryStore(db_path)
    persisted = reopened.list_by_student(student_ref)
    assert [item.result.result_id for item in persisted] == result_ids[1:]
    assert persisted[-1].counselor_notes[0].content == "已跟进"
    assert reopened.latest_for_student(student_ref).result.result_id == result_ids[-1]

    other_ref = str(uuid4())
    other = client.post("/api/session", json={"student_ref": other_ref}).json()
    response = client.post("/api/assessment", json={
        "session_id": other["session_id"],
        "evaluation_input": {"dialogue_history": [
            {"role": "user", "content": "另一个用户的评估"}
        ]},
    })
    assert response.status_code == 200, response.json()
    assert len(store.list_by_student(student_ref)) == 3
    assert len(store.list_by_student(other_ref)) == 1

    stats = client.get("/api/teacher/group-stats").json()
    assert stats["total_students"] == 2
    assert sum(stats["risk_distribution"].values()) == 2
