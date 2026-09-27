from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from backend.models.states import SessionState


class SessionManager:
    """Process-local sessions. Restarting the server clears all sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = RLock()

    def create_session(self) -> SessionState:
        session = SessionState(session_id=str(uuid4()))
        with self._lock:
            self._sessions[session.session_id] = session
        return session.model_copy(deep=True)

    def get_session(self, session_id: str) -> SessionState | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.model_copy(deep=True) if session else None

    def update_session(self, session_id: str, **changes: object) -> SessionState | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            changes.pop("session_id", None)
            changes.pop("created_at", None)
            updated = session.model_copy(update={**changes, "updated_at": datetime.now(timezone.utc)})
            self._sessions[session_id] = updated
            return updated.model_copy(deep=True)

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None


session_manager = SessionManager()
