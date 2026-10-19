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

# 6 个 iCBT 单元：元信息 + 正文 + 循证出处（学生端渲染正文，管理端只维护元信息）
SEED_ICBT_UNITS: list[ICBTUnit] = [
    ICBTUnit(
        id="u1", no=1, title="认识情绪", module="情绪觉察", order=1,
        steps=3, est_minutes=8, status="published", audience="全体学生",
        goal="学会给情绪命名，理解情绪没有对错。",
        content_steps=[
            "回想今天最明显的一种情绪，试着用一个词说出它",
            "给这种情绪的强烈程度打个分（0—10）",
            "注意它出现时身体有什么感觉（胸口、肩膀、胃…）",
        ],
        source="情绪命名（Affect Labeling）",
        source_note="Lieberman 等 2007 年研究发现，用词语标记情绪能降低杏仁核激活，是情绪调节的第一步。",
    ),
    ICBTUnit(
        id="u2", no=2, title="想法与情绪", module="认知调整", order=2,
        steps=3, est_minutes=10, status="published", audience="全体学生",
        goal="看见「想法」如何影响「感受」。",
        content_steps=[
            "写下让你难受的一个瞬间",
            "写下当时脑子里冒出的第一句话",
            "问自己：这个想法一定是事实吗？有没有别的解释？",
        ],
        source="CBT 认知模型",
        source_note="Beck 认知疗法认为「事件 → 想法 → 情绪」，改变想法可以改变情绪体验。",
    ),
    ICBTUnit(
        id="u3", no=3, title="识别思维陷阱", module="认知调整", order=3,
        steps=3, est_minutes=10, status="published", audience="全体学生",
        goal="认识常见的思维偏差，例如「非黑即白」「以偏概全」。",
        content_steps=[
            "回想一句你常对自己说的话",
            "对照：是不是「全或无」「贴标签」「灾难化」？",
            "把这句话改写得更有弹性一点",
        ],
        source="认知偏差清单",
        source_note="Burns《Feeling Good》(1980) 归纳了「全或无」「贴标签」「灾难化」等常见思维陷阱。",
    ),
    ICBTUnit(
        id="u4", no=4, title="行为激活", module="行为改变", order=4,
        steps=3, est_minutes=12, status="published", audience="全体学生",
        goal="通过小小的行动，慢慢把状态带起来。",
        content_steps=[
            "列出 3 件以前让你感到一点点愉快的事",
            "选最简单的一件，今天就做（哪怕只有 5 分钟）",
            "做完后记录：做之前 / 之后的心情各是多少",
        ],
        source="行为激活（Behavioral Activation）",
        source_note="Martell 等 2010 年的行为激活疗法证明，先行动再改善情绪，对抑郁症状有效。",
    ),
    ICBTUnit(
        id="u5", no=5, title="应对压力", module="压力管理", order=5,
        steps=3, est_minutes=12, status="published", audience="全体学生",
        goal="在压力来临时，有一套可以自救的小方法。",
        content_steps=[
            "深呼吸 4-7-8：吸气 4 秒、屏住 7 秒、呼气 8 秒，重复 4 次",
            "把「必须做完」拆成三步，只做第一步",
            "允许自己休息，休息不是偷懒",
        ],
        source="放松训练 · 4-7-8 呼吸法",
        source_note="延长呼气能激活副交感神经、降低心率，是临床常用的即刻减压方法。",
    ),
    ICBTUnit(
        id="u6", no=6, title="求助与支持", module="社会支持", order=6,
        steps=3, est_minutes=8, status="published", audience="全体学生",
        goal="知道什么时候、向谁求助是可以的。",
        content_steps=[
            "写下 2 个你信任的人的名字",
            "想一句可以开口的话：「我最近有点难受，能陪我说说话吗？」",
            "把 12356 和心理老师联系方式存进手机",
        ],
        source="社会支持与求助",
        source_note="WHO《2022 世界精神卫生报告》强调，主动求助与稳定的社会支持是心理复原力的重要来源。",
    ),
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
        """写入种子单元；对已存在但缺少正文的单元做内容回填。

        首次启动：全量插入 6 个单元。
        已有数据：保留管理端改过的元信息，仅当正文为空时补齐 goal/正文/来源。
        """
        with self._lock, self._connection() as connection:
            existing = {
                row[0]: row[1]
                for row in connection.execute("SELECT id, payload FROM icbt_units").fetchall()
            }
            if not existing:
                for unit in SEED_ICBT_UNITS:
                    connection.execute(
                        "INSERT INTO icbt_units (id, ord, payload) VALUES (?, ?, ?)",
                        (unit.id, unit.order, unit.model_dump_json()),
                    )
                return
            for seed in SEED_ICBT_UNITS:
                payload = existing.get(seed.id)
                if payload is None:
                    continue
                unit = ICBTUnit.model_validate_json(payload)
                if unit.content_steps:
                    continue  # 已有正文，不再覆盖
                unit.goal = unit.goal or seed.goal
                unit.content_steps = seed.content_steps
                unit.source = unit.source or seed.source
                unit.source_note = unit.source_note or seed.source_note
                connection.execute(
                    "UPDATE icbt_units SET payload = ? WHERE id = ?",
                    (unit.model_dump_json(), seed.id),
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

    def delete_by_student(self, student_ref: str) -> dict[str, int]:
        """永久删除预约与个人 iCBT 完成度，不删除公共课程内容。"""
        with self._lock, self._connection() as connection:
            appointments = connection.execute(
                "DELETE FROM appointments WHERE student_ref = ?", (student_ref,)
            ).rowcount
            progress = connection.execute(
                "DELETE FROM icbt_progress WHERE student_ref = ?", (student_ref,)
            ).rowcount
        return {
            "appointments": max(appointments, 0),
            "icbt_progress": max(progress, 0),
        }

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
