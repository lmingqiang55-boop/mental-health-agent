"""Companionship survives idle expiry/restart without losing safety or receipts."""

from datetime import timedelta

import pytest

from backend.core.conversation_archive import ConversationArchive
from backend.core.session_manager import SessionManager, session_manager
from backend.healing.store import HealingStore
from test_healing import chat, client, healing, start, support


@pytest.fixture
def durable(support, tmp_path, monkeypatch):
    sid = support[0]
    archive = ConversationArchive(tmp_path / "conversations.sqlite3")
    archive.save_session(session_manager.get_session(sid))
    monkeypatch.setattr(healing, "conversation_archive", archive)
    manager = SessionManager(archive=archive)
    monkeypatch.setattr(healing, "session_manager", manager)
    monkeypatch.setattr(healing, "healing_store", HealingStore(archive=archive))
    return sid, archive


def test_restart_restores_messages_and_can_continue(durable, monkeypatch):
    sid, archive = durable
    first = start(sid)
    assert first.status_code == 200, first.text
    hid = first.json()["healing_id"]
    answer = chat(sid, hid, "我最担心考不好", message_id="before-restart")
    assert answer.status_code == 200, answer.text

    # Fresh objects with only SQLite state, as after a backend restart.
    monkeypatch.setattr(healing, "session_manager", SessionManager(archive=archive))
    monkeypatch.setattr(healing, "healing_store", HealingStore(archive=archive))
    restored = client.get(f"/api/healing/{sid}")
    assert restored.status_code == 200, restored.text
    assert restored.json() == answer.json()
    retry = chat(sid, hid, "我最担心考不好", message_id="before-restart")
    assert retry.json() == answer.json()
    continued = chat(sid, hid, "我想先聊聊数学考试")
    assert continued.status_code == 200, continued.text
    assert continued.json()["turn_count"] == answer.json()["turn_count"] + 1


def test_idle_cache_expiry_preserves_companionship(durable):
    sid, _ = durable
    original = start(sid).json()
    healing.session_manager._sessions[sid].updated_at -= timedelta(hours=3)
    healing.healing_store.slots[sid].touched_at -= timedelta(hours=3)
    restored = client.get(f"/api/healing/{sid}")
    assert restored.status_code == 200, restored.text
    assert restored.json() == original


def test_restored_safety_stop_cannot_be_bypassed(durable, monkeypatch):
    sid, archive = durable
    original = start(sid).json()
    from test_healing import make_verdict
    verdict = make_verdict("high")
    def halt(session):
        session.latest_safety = verdict
        session.safety_halted = True
        session.safety_stage = "stopped"
    healing.session_manager.modify_session(sid, halt)
    monkeypatch.setattr(healing, "session_manager", SessionManager(archive=archive))
    monkeypatch.setattr(healing, "healing_store", HealingStore(archive=archive))
    response = chat(sid, original["healing_id"], "继续聊聊")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "referred"
    assert response.json()["risk"]["risk_level"] == "high"


def test_legacy_assessment_starts_without_rescreening(durable, monkeypatch):
    sid, archive = durable
    with archive.connect() as db:
        db.execute("DELETE FROM conversations WHERE session_id=?", (sid,))
    monkeypatch.setattr(healing, "session_manager", SessionManager(archive=archive))
    response = start(sid)
    assert response.status_code == 200, response.text
    continued = chat(sid, response.json()["healing_id"], "最近数学考试让我紧张")
    assert continued.status_code == 200, continued.text
    assert continued.json()["turn_count"] == 1


def test_deleted_session_is_not_resurrected_from_report(durable):
    sid, _ = durable
    start(sid)
    assert healing.session_manager.delete_session(sid)
    response = client.get(f"/api/healing/{sid}")
    assert response.status_code == 404


def test_healing_turn_safety_survives_restart(durable, monkeypatch, safety_stub):
    from backend.safety.schemas import SafetyLevel
    sid, archive = durable
    original = start(sid).json()
    safety_stub.force(SafetyLevel.HIGH)
    stopped = chat(sid, original["healing_id"], "需要帮助")
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["risk"]["risk_level"] == "high"
    monkeypatch.setattr(healing, "session_manager", SessionManager(archive=archive))
    monkeypatch.setattr(healing, "healing_store", HealingStore(archive=archive))
    restored = client.get(f"/api/healing/{sid}")
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "referred"
    assert restored.json()["risk"]["risk_level"] == "high"


def test_delete_by_student_includes_archived_sessions(tmp_path):
    archive = ConversationArchive(tmp_path / "conversations.sqlite3")
    manager = SessionManager(archive=archive)
    session = manager.create_session("student-a")
    restarted = SessionManager(archive=archive)
    assert restarted.delete_by_student("student-a") == [session.session_id]
    assert archive.load_session(session.session_id) is None


def test_report_link_uses_assessment_session_not_companionship_session(support):
    from backend.models.healing import student_view
    sid, result, _, _ = support
    response = start(sid)
    assert response.status_code == 200, response.text
    state = healing.healing_store.slot(sid).state.model_copy(deep=True)
    state.memory.session_id = "another-companionship-session"
    view = student_view(state)
    assert view.session_id != view.assessment_session_id
    report = client.get(f"/api/assessment/result/{view.assessment_result_id}",
                        params={"session_id": view.assessment_session_id})
    assert report.status_code == 200, report.text
    assert report.json()["result"]["result_id"] == result["result_id"]
    wrong = client.get(f"/api/assessment/result/{view.assessment_result_id}",
                       params={"session_id": view.session_id})
    assert wrong.status_code == 404


def test_safety_support_accepts_messages_without_resuming_coaching(durable, safety_stub, monkeypatch):
    from backend.safety.schemas import SafetyLevel
    sid, archive = durable
    safety_stub.force(SafetyLevel.HIGH, message="我在听，我们先确保你此刻安全。")
    first = start(sid).json()
    fake = healing.healing_agent.client
    calls_before = len(fake.calls)
    safety_stub.force(SafetyLevel.UNCERTAIN, message="谢谢你继续告诉我，你现在身边有人陪着吗？")
    response = chat(sid, first["healing_id"], "我现在想继续说说", message_id="support-turn")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "referred"
    assert data["risk"]["risk_level"] == "high"
    assert data["messages"][-2]["content"] == "我现在想继续说说"
    assert data["messages"][-1]["content"] == "谢谢你继续告诉我，你现在身边有人陪着吗？"
    assert data["turn_count"] == first["turn_count"] + 1
    assert not any(item["active"] for item in data["report"]["suggestions"])
    assert len(fake.calls) == calls_before
    retried = chat(sid, first["healing_id"], "我现在想继续说说", message_id="support-turn")
    assert retried.json() == data
    monkeypatch.setattr(healing, "session_manager", SessionManager(archive=archive))
    monkeypatch.setattr(healing, "healing_store", HealingStore(archive=archive))
    assert client.get(f"/api/healing/{sid}").json() == data
