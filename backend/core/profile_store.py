"""学生档案与紧急联系人存储（SQLite，线程安全）。

按匿名 student_ref 落库，持久化在 backend/data/student_profile.sqlite3，
刷新 / 重启 / 重新打开页面后仍可读回。
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from uuid import uuid4

from backend.models.profile import EmergencyContact, StudentProfile


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "student_profile.sqlite3"


class ProfileStore:
    """学生档案（每个 student_ref 一行）与紧急联系人（一对多）存储。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._lock = RLock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS student_profiles (
                    student_ref TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS emergency_contacts (
                    contact_id TEXT PRIMARY KEY,
                    student_ref TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS emergency_contacts_student
                ON emergency_contacts (student_ref)
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self._db_path, timeout=10)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # ---------- 学生档案 ----------
    def get_profile(self, student_ref: str) -> StudentProfile:
        """取档案；从未填写过时返回一份以该 student_ref 为空的默认档案。"""
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM student_profiles WHERE student_ref = ?",
                (student_ref,),
            ).fetchone()
        if row is None:
            return StudentProfile(student_ref=student_ref)
        return StudentProfile.model_validate_json(row[0])

    def save_profile(self, student_ref: str, nickname: str,
                     school_stage: str | None, class_name: str) -> StudentProfile:
        profile = StudentProfile(
            student_ref=student_ref,
            nickname=nickname,
            school_stage=school_stage,
            class_name=class_name,
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO student_profiles (student_ref, payload) VALUES (?, ?) "
                "ON CONFLICT(student_ref) DO UPDATE SET payload = excluded.payload",
                (student_ref, profile.model_dump_json()),
            )
        return profile

    # ---------- 紧急联系人 ----------
    def list_contacts(self, student_ref: str) -> list[EmergencyContact]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM emergency_contacts WHERE student_ref = ? ORDER BY rowid",
                (student_ref,),
            ).fetchall()
        return [EmergencyContact.model_validate_json(r[0]) for r in rows]

    def add_contact(self, student_ref: str, name: str, relation: str,
                    phone: str) -> EmergencyContact:
        contact = EmergencyContact(id=str(uuid4()), name=name, relation=relation, phone=phone)
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO emergency_contacts (contact_id, student_ref, payload) "
                "VALUES (?, ?, ?)",
                (contact.id, student_ref, contact.model_dump_json()),
            )
        return contact

    def remove_contact(self, student_ref: str, contact_id: str) -> bool:
        """按 student_ref + contact_id 删除；命中返回 True，否则 False。"""
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM emergency_contacts WHERE contact_id = ? AND student_ref = ?",
                (contact_id, student_ref),
            )
            deleted = cursor.rowcount > 0
        return deleted


profile_store = ProfileStore()
