"""评估记忆库（C 模块，目标图「评估记忆库」）。

- 保存 EvaluationRecord（评估结果快照）
- 按 student_ref 管理历史记录
- 提供历史趋势数据
- 历史筛查结果可回流到对话闭环，支持个性化对话

框架阶段为进程内存储；接入数据库时保持本接口。
"""

from threading import RLock
from uuid import uuid4

from backend.models.assessment import (
    CounselorNote,
)
from backend.models.evaluation import EvaluationRecord, EvaluationResult
from backend.models.enums import FollowUpStatus


class MemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, EvaluationRecord] = {}
        self._by_student: dict[str, list[str]] = {}
        self._lock = RLock()

    def save_result(self, result: EvaluationResult) -> EvaluationRecord:
        record = EvaluationRecord(
            record_id=str(uuid4()),
            student_ref=result.student_ref or result.session_id,
            result=result,
            follow_up_status=(
                FollowUpStatus.PENDING
                if result.risk.requires_intervention else FollowUpStatus.NONE),
        )
        with self._lock:
            self._records[record.record_id] = record
            self._by_student.setdefault(record.student_ref, []).append(
                record.record_id)
        return record

    def get_record(self, record_id: str) -> EvaluationRecord | None:
        with self._lock:
            record = self._records.get(record_id)
            return record.model_copy(deep=True) if record else None

    def list_by_student(self, student_ref: str) -> list[EvaluationRecord]:
        with self._lock:
            ids = self._by_student.get(student_ref, [])
            records = [self._records[i] for i in ids if i in self._records]
            return [r.model_copy(deep=True) for r in records]

    def latest_for_student(self, student_ref: str) -> EvaluationRecord | None:
        """返回最近一次评估记录，用于历史回流到对话闭环。"""
        records = self.list_by_student(student_ref)
        return records[-1] if records else None

    def add_counselor_note(self, record_id: str, counselor_ref: str,
                       content: str) -> EvaluationRecord | None:
        with self._lock:
            record = self._records.get(record_id)
            if record is None:
                return None
            record.counselor_notes.append(CounselorNote(
                note_id=str(uuid4()),
                counselor_ref=counselor_ref,
                content=content,
            ))
            record.follow_up_status = FollowUpStatus.IN_PROGRESS
            return record.model_copy(deep=True)

    # -- 老师端：群体概览（框架占位） -----------------------------------

    def list_all_records(self) -> list[EvaluationRecord]:
        with self._lock:
            return [r.model_copy(deep=True) for r in self._records.values()]


memory_store = MemoryStore()
