"""咨询预约与 iCBT 数据存储（SQLite，线程安全）。

- appointments：预约记录（含 slot / status，便于排序与筛选）
- icbt_units：iCBT 单元目录（首次启动写入 6 个种子单元）
- icbt_progress：按匿名 student_ref 记录已完成单元

数据落在 backend/data/intervention.sqlite3，刷新/重启不丢。
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from uuid import uuid4

from backend.models.counseling import (
    Appointment,
    AppointmentStatus,
    ICBTProgress,
    ICBTUnit,
    ICBTUnitUpdate,
)
from backend.models.states import _now

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "intervention.sqlite3"

# 与前端学生端 iCBT 目录对应的 6 个单元（内容正文仍由学生端本地渲染）
SEED_ICBT_UNITS: list[ICBTUnit] = [
    ICBTUnit(id="u1", no=1, title="认识情绪", module="情绪觉察", order=1,
             steps=3, est_minutes=8, status="published", audience="全体学生"),
    ICBTUnit(id="u2", no=2, title="想法与情绪", module="认知调整", order=2,
             steps=3, est_minutes=10, status="published", audience="全体学生"),
    ICBTUnit(id="u3", no=3, title="识别思维陷阱", module="认知调整", order=3,
             steps=3, est_minutes=10, status="published", audience="全体学生"),
    ICBTUnit(id="u4", no=4, title="行为激活", module="行为改变", order=4,
             steps=3, est_minutes=12, status="published", audience="全体学生"),
    ICBTUnit(id="u5", no=5, title="应对压力", module="压力管理", order=5,
             steps=3, est_minutes=12, status="published", audience="全体学生"),
    ICBTUnit(id="u6", no=6, title="求助与支持", module="社会支持", order=6,
             steps=3, est_minutes=8, status="published", audience="全体学生"),
]


class CounselingStore:
    """咨询预约 + iCBT 单元/完成度存储。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._lock = RLock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id TEXT PRIMARY KEY,
                    student_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS appointments_student
                ON appointments (student_ref)
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS appointments_slot
                ON appointments (slot)
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS icbt_units (
                    id TEXT PRIMARY KEY,
                    ord INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS icbt_progress (
                    student_ref TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
            """)
        self._seed_units()

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

    def _seed_units(self) -> None:
        """首次启动写入种子单元；已存在则不覆盖（管理端改动会保留）。"""
        with self._lock, self._connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM icbt_units").fetchone()[0]
            if count:
                return
            for unit in SEED_ICBT_UNITS:
                connection.execute(
                    "INSERT INTO icbt_units (id, ord, payload) VALUES (?, ?, ?)",
                    (unit.id, unit.order, unit.model_dump_json()),
                )

    # ---------- 咨询预约 ----------
    def create_appointment(self, appointment: Appointment) -> Appointment:
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO appointments (id, student_ref, status, slot, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (appointment.id, appointment.student_ref, appointment.status,
                 appointment.slot, appointment.model_dump_json()),
            )
        return appointment

    def list_appointments(self, student_ref: str | None = None) -> list[Appointment]:
        sql = "SELECT payload FROM appointments"
        params: tuple = ()
        if student_ref:
            sql += " WHERE student_ref = ?"
            params = (student_ref,)
        sql += " ORDER BY slot DESC"
        with self._lock, self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [Appointment.model_validate_json(r[0]) for r in rows]

    def get_appointment(self, appointment_id: str) -> Appointment | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
        return Appointment.model_validate_json(row[0]) if row else None

    def set_appointment_status(self, appointment_id: str,
                               status: AppointmentStatus) -> Appointment | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
            if row is None:
                return None
            appointment = Appointment.model_validate_json(row[0])
            appointment.status = status
            connection.execute(
                "UPDATE appointments SET status = ?, payload = ? WHERE id = ?",
                (status, appointment.model_dump_json(), appointment_id),
            )
        return appointment

    # ---------- iCBT 单元 ----------
    def list_units(self) -> list[ICBTUnit]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM icbt_units ORDER BY ord"
            ).fetchall()
        return [ICBTUnit.model_validate_json(r[0]) for r in rows]

    def get_unit(self, unit_id: str) -> ICBTUnit | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM icbt_units WHERE id = ?", (unit_id,)
            ).fetchone()
        return ICBTUnit.model_validate_json(row[0]) if row else None

    def update_unit(self, unit_id: str, patch: ICBTUnitUpdate) -> ICBTUnit | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM icbt_units WHERE id = ?", (unit_id,)
            ).fetchone()
            if row is None:
                return None
            unit = ICBTUnit.model_validate_json(row[0])
            for field, value in patch.model_dump(exclude_unset=True).items():
                if value is not None:
                    setattr(unit, field, value)
            unit.updated_at = _now()
            connection.execute(
                "UPDATE icbt_units SET ord = ?, payload = ? WHERE id = ?",
                (unit.order, unit.model_dump_json(), unit_id),
            )
        return unit

    # ---------- iCBT 完成度 ----------
    def get_progress(self, student_ref: str) -> ICBTProgress:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM icbt_progress WHERE student_ref = ?", (student_ref,)
            ).fetchone()
        if row is None:
            return ICBTProgress(student_ref=student_ref)
        return ICBTProgress.model_validate_json(row[0])

    def set_progress(self, student_ref: str,
                     completed_units: list[str]) -> ICBTProgress:
        progress = ICBTProgress(student_ref=student_ref,
                                completed_units=list(dict.fromkeys(completed_units)))
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO icbt_progress (student_ref, payload) VALUES (?, ?) "
                "ON CONFLICT(student_ref) DO UPDATE SET payload = excluded.payload",
                (student_ref, progress.model_dump_json()),
            )
        return progress

    def unit_completion(self) -> tuple[int, dict[str, int]]:
        """返回 (有进度记录的学生数, {unit_id: 完成该单元的学生数})。"""
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT payload FROM icbt_progress").fetchall()
        records = [ICBTProgress.model_validate_json(r[0]) for r in rows]
        counts: dict[str, int] = {}
        for record in records:
            for unit_id in set(record.completed_units):
                counts[unit_id] = counts.get(unit_id, 0) + 1
        return len(records), counts


counseling_store = CounselingStore()
