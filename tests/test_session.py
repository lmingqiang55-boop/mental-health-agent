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


def test_locked_read_uses_a_copy_without_writing_or_extending_ttl():
    from backend.core.session_manager import SessionManager
    manager = SessionManager()
    original = manager.create_session()

    def reader(snapshot):
        snapshot.crisis_mode = True
        snapshot.conversation_history.clear()
        return snapshot.session_id

    assert manager.read_session(original.session_id, reader) == original.session_id
    assert manager.get_session(original.session_id) == original


def test_locked_read_does_not_consume_missing_or_expired_session():
    from datetime import timedelta
    from backend.core.session_manager import SessionManager
    manager = SessionManager(ttl=timedelta(seconds=-1))
    expired = manager.create_session()
    consumed = []
    assert manager.read_session("missing", consumed.append) is None
    assert manager.read_session(expired.session_id, consumed.append) is None
    assert consumed == []


def test_locked_read_commit_serializes_with_screening_worker_update():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from backend.core.session_manager import SessionManager
    manager = SessionManager()
    session = manager.create_session()
    entered, release, attempted, written = Event(), Event(), Event(), Event()

    def reader(snapshot):
        entered.set()
        assert release.wait(timeout=3)
        return snapshot.crisis_mode

    def write():
        attempted.set()
        manager.modify_session(session.session_id, lambda state: setattr(state, "crisis_mode", True))
        written.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reading = executor.submit(manager.read_session, session.session_id, reader)
        assert entered.wait(timeout=3)
        writing = executor.submit(write)
        try:
            assert attempted.wait(timeout=3)
            assert not written.wait(timeout=.05)
        finally:
            release.set()
        assert reading.result(timeout=3) is False
        writing.result(timeout=3)
    assert manager.read_session(session.session_id, lambda state: state.crisis_mode) is True
