"""Persist assessment results until the anonymous student deletes them."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from uuid import uuid4

from backend.models.assessment import CounselorNote
from backend.models.evaluation import EvaluationRecord, EvaluationResult
from backend.models.enums import FollowUpStatus


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "evaluation_memory.sqlite3"


class MemoryStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._lock = RLock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS assessment_records (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL UNIQUE,
                    result_id TEXT NOT NULL UNIQUE,
                    student_ref TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS assessment_records_student
                ON assessment_records (student_ref, sequence)
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

    @staticmethod
    def _record(row) -> EvaluationRecord | None:
        return EvaluationRecord.model_validate_json(row[0]) if row else None

    def save_result(self, result: EvaluationResult) -> EvaluationRecord:
        student_ref = result.student_ref or result.session_id
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._record(connection.execute(
                "SELECT payload FROM assessment_records WHERE result_id = ?",
                (result.result_id,),
            ).fetchone())
            if existing is not None:
                if existing.result != result:
                    raise ValueError("同一评估 ID 对应不同结果")
                return existing

            record = EvaluationRecord(
                record_id=str(uuid4()),
                student_ref=student_ref,
                result=result,
                risk_input_fields=sorted(result.risk.model_fields_set),
                follow_up_status=(
                    FollowUpStatus.PENDING
                    if result.risk.requires_intervention else FollowUpStatus.NONE
                ),
            )
            connection.execute("""
                INSERT INTO assessment_records (record_id, result_id, student_ref, payload)
                VALUES (?, ?, ?, ?)
            """, (record.record_id, result.result_id, student_ref, record.model_dump_json()))
            return record.model_copy(deep=True)

    def get_record(self, record_id: str) -> EvaluationRecord | None:
        with self._lock, self._connection() as connection:
            return self._record(connection.execute(
                "SELECT payload FROM assessment_records WHERE record_id = ?",
                (record_id,),
            ).fetchone())

    def get_record_by_result_id(self, result_id: str) -> EvaluationRecord | None:
        with self._lock, self._connection() as connection:
            return self._record(connection.execute(
                "SELECT payload FROM assessment_records WHERE result_id = ?",
                (result_id,),
            ).fetchone())

    def list_by_student(self, student_ref: str) -> list[EvaluationRecord]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("""
                SELECT payload FROM assessment_records
                WHERE student_ref = ? ORDER BY sequence
            """, (student_ref,)).fetchall()
            return [self._record(row) for row in rows]

    def list_payloads_by_student(self, student_ref: str) -> list[dict]:
        """Read serialized records before defaults hide missing input fields.

        Adapters may inspect provenance/completeness without changing records.
        """
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM assessment_records WHERE student_ref = ? ORDER BY sequence",
                (student_ref,),
            ).fetchall()
            return [json.loads(row[0]) for row in rows]

    def latest_for_student(self, student_ref: str) -> EvaluationRecord | None:
        with self._lock, self._connection() as connection:
            return self._record(connection.execute("""
                SELECT payload FROM assessment_records
                WHERE student_ref = ? ORDER BY sequence DESC LIMIT 1
            """, (student_ref,)).fetchone())

    def delete_by_student(self, student_ref: str) -> int:
        """永久删除匿名学生的全部测评结果与其中的教师备注。"""
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM assessment_records WHERE student_ref = ?",
                (student_ref,),
            )
            return max(cursor.rowcount, 0)

    def delete_record(self, student_ref: str, record_id: str) -> bool:
        """只删除属于该匿名身份的一条评估结果。"""
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM assessment_records WHERE student_ref = ? AND record_id = ?",
                (student_ref, record_id),
            )
            return cursor.rowcount > 0

    def add_counselor_note(self, record_id: str, counselor_ref: str,
                           content: str) -> EvaluationRecord | None:
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = self._record(connection.execute(
                "SELECT payload FROM assessment_records WHERE record_id = ?",
                (record_id,),
            ).fetchone())
            if record is None:
                return None
            record.counselor_notes.append(CounselorNote(
                note_id=str(uuid4()), counselor_ref=counselor_ref, content=content,
            ))
            record.follow_up_status = FollowUpStatus.IN_PROGRESS
            connection.execute(
                "UPDATE assessment_records SET payload = ? WHERE record_id = ?",
                (record.model_dump_json(), record_id),
            )
            return record.model_copy(deep=True)

    def list_all_records(self) -> list[EvaluationRecord]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM assessment_records ORDER BY sequence"
            ).fetchall()
            return [self._record(row) for row in rows]


memory_store = MemoryStore()
