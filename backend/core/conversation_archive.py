"""Durable snapshots used to resume companionship after cache expiry/restarts."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ConversationArchive:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT PRIMARY KEY, student_ref TEXT NOT NULL,
                session TEXT NOT NULL, healing TEXT)""")
            db.execute("CREATE TABLE IF NOT EXISTS deleted_conversations (session_id TEXT PRIMARY KEY)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_session(self, session):
        payload = session.model_dump(mode="json")
        payload["dialogue_engine"] = session.dialogue_engine
        payload["chat_receipts"] = {key: value.model_dump(mode="json")
                                    for key, value in session.chat_receipts.items()}
        with self.connect() as db:
            db.execute("""INSERT INTO conversations(session_id, student_ref, session)
                VALUES (?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET
                student_ref=excluded.student_ref, session=excluded.session""",
                (session.session_id, session.student_ref or session.session_id,
                 json.dumps(payload, ensure_ascii=False)))

    def load_session(self, session_id):
        from backend.models.states import SessionState
        with self.connect() as db:
            row = db.execute("SELECT session FROM conversations WHERE session_id=?",
                             (session_id,)).fetchone()
        return SessionState.model_validate_json(row[0]) if row else None

    def save_healing(self, session_id, state, receipts):
        with self.connect() as db:
            db.execute("UPDATE conversations SET healing=? WHERE session_id=?",
                       (json.dumps({"state": state.model_dump(mode="json"),
                                    "receipts": receipts}, ensure_ascii=False), session_id))

    def load_healing(self, session_id):
        with self.connect() as db:
            row = db.execute("SELECT healing FROM conversations WHERE session_id=?",
                             (session_id,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def student_sessions(self, student_ref):
        with self.connect() as db:
            return [row[0] for row in db.execute(
                "SELECT session_id FROM conversations WHERE student_ref=?", (student_ref,))]

    def delete(self, session_id):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO deleted_conversations VALUES (?)", (session_id,))
            return db.execute("DELETE FROM conversations WHERE session_id=?",
                              (session_id,)).rowcount > 0

    def is_deleted(self, session_id):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM deleted_conversations WHERE session_id=?",
                              (session_id,)).fetchone() is not None


conversation_archive = ConversationArchive(
    Path(__file__).resolve().parents[2] / "data" / "conversations.sqlite3")
