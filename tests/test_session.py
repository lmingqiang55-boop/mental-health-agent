from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_create_get_and_delete_session() -> None:
    created = client.post("/api/session")
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    assert created.json()["status"] == "created"

    fetched = client.get(f"/api/session/{session_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["turn_count"] == 0
    assert body["current_stage"] == "exploration"
    # 六维固定提问状态机删除后，公共状态里不再有这两个字段
    assert "assessment_state" not in body
    assert "clarify_count" not in body

    assert client.delete(f"/api/session/{session_id}").status_code == 200
    missing = client.get(f"/api/session/{session_id}")
    assert missing.status_code == 404
    assert missing.json() == {"error": {
        "code": "SESSION_NOT_FOUND", "message": "Session does not exist."
    }}


def test_unknown_session() -> None:
    response = client.get("/api/session/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"
