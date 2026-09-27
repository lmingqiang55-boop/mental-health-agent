"""Session 生命周期管理（C 模块）。

修复点：
- ``modify_session`` 把读-改-写放进同一把锁，消除 chat 与 vision/audio 之间的
  lost-update 竞态。
- TTL 过期与最大数量，避免内存无限增长。

当前仍为进程内存储，重启清空；持久化是后续任务。
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from backend.models.states import SessionState

SESSION_TTL = timedelta(hours=2)
MAX_SESSIONS = 1000


class SessionManager:
    def __init__(self, ttl: timedelta = SESSION_TTL,
                 max_sessions: int = MAX_SESSIONS) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = RLock()
        self._ttl = ttl
        self._max = max_sessions

    def create_session(self, student_ref: str | None = None) -> SessionState:
        with self._lock:
            self._purge_expired_locked()
            if len(self._sessions) >= self._max:
                self._evict_oldest_locked()
            session = SessionState(
                session_id=str(uuid4()), student_ref=student_ref)
            self._sessions[session.session_id] = session
            return session.model_copy(deep=True)

    def get_session(self, session_id: str) -> SessionState | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session and self._is_expired(session):
                self._sessions.pop(session_id, None)
                return None
            return session.model_copy(deep=True) if session else None

    def modify_session(
        self, session_id: str,
        mutator: Callable[[SessionState], None],
    ) -> SessionState | None:
        """原子地取出 session、执行 mutator、写回。

        所有需要「读-改-写」的流程（chat / vision merge / 评估）都必须走这里，
        不得在路由层 get → 改 → update 分三步操作。
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or self._is_expired(session):
                self._sessions.pop(session_id, None)
                return None
            mutator(session)
            session.updated_at = datetime.now(timezone.utc)
            return session.model_copy(deep=True)

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # -- 内部清理 --------------------------------------------------------

    def _is_expired(self, session: SessionState) -> bool:
        return datetime.now(timezone.utc) - session.updated_at > self._ttl

    def _purge_expired_locked(self) -> None:
        expired = [sid for sid, s in self._sessions.items()
                   if self._is_expired(s)]
        for sid in expired:
            self._sessions.pop(sid, None)

    def _evict_oldest_locked(self) -> None:
        if not self._sessions:
            return
        oldest = min(self._sessions.values(), key=lambda s: s.updated_at)
        self._sessions.pop(oldest.session_id, None)


session_manager = SessionManager()
