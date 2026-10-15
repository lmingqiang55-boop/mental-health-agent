"""治愈小工具数据存储（心情日记 / 微光打卡 / 专注记录）与内容库。

- 心情、微光打卡、专注记录按匿名 student_ref 落到 SQLite，刷新/重启不丢；
- 内容库为静态清单（含情绪推荐用的 moods 映射），无需落库。
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from threading import RLock
from uuid import uuid4

from backend.models.heal import FocusSession, HabitRecord, HealContent, MoodEntry


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "heal_journal.sqlite3"

# 内容库：type 决定前端交互（breath 呼吸 / meditation 冥想 / noise 音景 / mindful 小文章 / comic 漫画）
# moods 用于 #7「按当前情绪推荐」，取值为心情档位 1-5
HEAL_CONTENTS: list[HealContent] = [
    HealContent(id="hc_breath", title="4-7-8 呼吸练习", tag="放松", type="breath", cover="breath",
                desc="跟着像素小球一起，吸气 4 秒、屏息 7 秒、呼气 8 秒，让心跳慢下来。", moods=[2, 3, 4]),
    HealContent(id="hc_box", title="方框呼吸", tag="放松", type="breath", cover="breath",
                desc="吸气 4、屏息 4、呼气 4、再屏息 4，四个边循环一次，烦躁时很快能稳住。", moods=[1, 2, 3]),
    HealContent(id="hc_meditation", title="5 分钟身体扫描", tag="冥想", type="meditation", cover="meditation",
                desc="从头顶到脚尖，一点点放松身体的小角落。", moods=[2, 3]),
    HealContent(id="hc_noise_rain", title="雨声白噪音", tag="白噪音", type="noise", cover="rain",
                desc="淅淅沥沥的像素雨，适合写作业和睡前听。", moods=[1, 2, 3]),
    HealContent(id="hc_noise_fire", title="篝火白噪音", tag="白噪音", type="noise", cover="fire",
                desc="噼里啪啦的温暖声音，冬天晚自习必备。", moods=[2, 3, 4]),
    HealContent(id="hc_noise_wave", title="海浪白噪音", tag="白噪音", type="noise", cover="wave",
                desc="一遍遍冲刷沙滩的浪声，让脑子放空。", moods=[1, 2, 3]),
    HealContent(id="hc_noise_bell", title="风铃白噪音", tag="白噪音", type="noise", cover="bell",
                desc="清脆的风铃声，心情烦躁的时候听一听。", moods=[3, 4, 5]),
    HealContent(id="hc_mindful_letter", title="写给情绪的一封信", tag="正念", type="mindful", cover="letter",
                desc="图文小练习：把此刻的情绪写下来，和它打个招呼。", moods=[1, 2, 3]),
    HealContent(id="hc_mindful_ground", title="五感着陆练习", tag="正念", type="mindful", cover="ground",
                desc="看到什么、听到什么、摸到什么——把自己带回当下。", moods=[1, 2, 3, 4]),
    HealContent(id="hc_comic_weather", title="情绪也有天气", tag="漫画", type="comic", cover="doc",
                desc="八格小漫画：坏天气会过去，你不需要一直晴朗。", moods=[1, 2, 3, 4, 5]),
]

# 心情标签候选（前端多选，供情绪云图统计）不在这里定义：它是
# ``backend.models.heal.MOOD_TAGS``——和按档位分组的 ``MOOD_LEVEL_TAGS``
# 放在同一个文件里，避免同一套词抄两份、改一处忘一处。


def recommend_contents(mood: int | None = None, tag: str | None = None) -> list[HealContent]:
    """按情绪（1-5）与分类筛选内容；命中情绪的内容优先。"""
    items = list(HEAL_CONTENTS)
    if tag:
        items = [c for c in items if c.tag == tag or c.type == tag]
    if mood:
        hit = [c for c in items if mood in c.moods]
        if hit:
            return hit
    return items


def _today() -> str:
    return date.today().isoformat()


def _since(days: int) -> str:
    return (date.today() - timedelta(days=max(1, days) - 1)).isoformat()


class HealStore:
    """治愈小工具记录存储（SQLite，线程安全）。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._lock = RLock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS mood_entries (
                    student_ref TEXT NOT NULL,
                    date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (student_ref, date)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS habit_records (
                    student_ref TEXT NOT NULL,
                    date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (student_ref, date)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS focus_sessions (
                    session_id TEXT PRIMARY KEY,
                    student_ref TEXT NOT NULL,
                    date TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS focus_sessions_student
                ON focus_sessions (student_ref, date)
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

    # ---------- 心情日记 ----------
    def save_mood(self, student_ref: str, entry: MoodEntry) -> MoodEntry:
        payload = entry.model_dump_json()
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO mood_entries (student_ref, date, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(student_ref, date) DO UPDATE SET payload = excluded.payload",
                (student_ref, entry.date, payload),
            )
        return entry

    def list_moods(self, student_ref: str, since: str) -> list[MoodEntry]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM mood_entries WHERE student_ref = ? AND date >= ? ORDER BY date",
                (student_ref, since),
            ).fetchall()
        return [MoodEntry.model_validate_json(r[0]) for r in rows]

    # ---------- 微光打卡 ----------
    def save_habits(self, student_ref: str, day: str,
                    items: list[str]) -> tuple[HabitRecord, int, int]:
        record = HabitRecord(date=day, items=items)
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO habit_records (student_ref, date, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(student_ref, date) DO UPDATE SET payload = excluded.payload",
                (student_ref, day, record.model_dump_json()),
            )
        records = self.list_habits(student_ref, "0000-01-01")
        return record, self._streak(records), self._total_days(records)

    def list_habits(self, student_ref: str, since: str) -> list[HabitRecord]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM habit_records WHERE student_ref = ? AND date >= ? ORDER BY date",
                (student_ref, since),
            ).fetchall()
        return [HabitRecord.model_validate_json(r[0]) for r in rows]

    @staticmethod
    def _total_days(records: list[HabitRecord]) -> int:
        return len({r.date for r in records if r.items})

    @staticmethod
    def _streak(records: list[HabitRecord]) -> int:
        """连续打卡天数：从今天（未打卡则从昨天）向前数连续有记录的天数。"""
        done = {r.date for r in records if r.items}
        if not done:
            return 0
        cursor = date.today()
        if cursor.isoformat() not in done:
            cursor = cursor - timedelta(days=1)
        streak = 0
        while cursor.isoformat() in done:
            streak += 1
            cursor = cursor - timedelta(days=1)
        return streak

    # ---------- 专注记录 ----------
    def log_focus(self, student_ref: str, minutes: int,
                  mood_before: int | None, mood_after: int | None) -> FocusSession:
        session = FocusSession(
            session_id=str(uuid4()),
            student_ref=student_ref,
            minutes=minutes,
            mood_before=mood_before,
            mood_after=mood_after,
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO focus_sessions (session_id, student_ref, date, payload) VALUES (?, ?, ?, ?)",
                (session.session_id, student_ref, date.today().isoformat(),
                 session.model_dump_json()),
            )
        return session

    def list_focus(self, student_ref: str, since: str) -> list[FocusSession]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM focus_sessions WHERE student_ref = ? AND date >= ? ORDER BY date",
                (student_ref, since),
            ).fetchall()
        return [FocusSession.model_validate_json(r[0]) for r in rows]


heal_store = HealStore()
