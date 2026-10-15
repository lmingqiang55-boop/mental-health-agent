"""治愈小工具 API（心情日记 / 微光打卡 / 专注学习 / 内容库 / 成长回顾）。

与学生心理筛查主链路相互独立：只按匿名 student_ref 落库，不参与风险判定。
记录持久化在 backend/data/heal_journal.sqlite3，刷新/重启不丢。
"""

from fastapi import APIRouter, HTTPException, Query

from backend.core.art_reflect import ArtReflectUnavailable, reflect_artwork
from backend.core.heal_store import heal_store, recommend_contents, _since, _today
from backend.models.heal import MOOD_TAGS, MoodEntry
from backend.models.requests import (
    ArtReflectRequest,
    FocusLogRequest,
    HabitCheckinRequest,
    SaveMoodRequest,
)
from backend.models.responses import (
    ArtReflectResponse,
    FocusListResponse,
    FocusLogResponse,
    GrowthResponse,
    HabitCheckinResponse,
    HabitListResponse,
    HealContentsResponse,
    MoodListResponse,
    SaveMoodResponse,
)

router = APIRouter(prefix="/api/heal", tags=["heal"])


def _days(days: int) -> int:
    return max(1, min(days, 365))


# ---------------------------------------------------------------------------
# 内容库与情绪推荐（#3 音景 / #7 推荐）
# ---------------------------------------------------------------------------

@router.get("/contents", response_model=HealContentsResponse)
def list_contents(
    mood: int | None = Query(default=None, ge=1, le=5),
    tag: str | None = Query(default=None),
) -> HealContentsResponse:
    return HealContentsResponse(contents=recommend_contents(mood=mood, tag=tag), tags=MOOD_TAGS)


# ---------------------------------------------------------------------------
# 心情日记（#1 / #12）
# ---------------------------------------------------------------------------

@router.post("/mood", response_model=SaveMoodResponse)
def save_mood(request: SaveMoodRequest) -> SaveMoodResponse:
    entry = MoodEntry(
        date=request.date,
        mood=request.mood,
        weather=request.weather,
        color=request.color,
        tags=request.tags,
        note=request.note,
        voice_text=request.voice_text,
    )
    return SaveMoodResponse(entry=heal_store.save_mood(request.student_ref, entry))


@router.get("/mood", response_model=MoodListResponse)
def list_moods(
    student_ref: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    days: int = Query(default=30),
) -> MoodListResponse:
    entries = heal_store.list_moods(student_ref, _since(_days(days)))
    return MoodListResponse(student_ref=student_ref, entries=entries)


# ---------------------------------------------------------------------------
# 微光打卡（#4 / #12）
# ---------------------------------------------------------------------------

@router.post("/habits", response_model=HabitCheckinResponse)
def checkin_habits(request: HabitCheckinRequest) -> HabitCheckinResponse:
    day = request.date or _today()
    record, streak, total_days = heal_store.save_habits(request.student_ref, day, request.items)
    return HabitCheckinResponse(record=record, streak=streak, total_days=total_days)


@router.get("/habits", response_model=HabitListResponse)
def list_habits(
    student_ref: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    days: int = Query(default=30),
) -> HabitListResponse:
    records = heal_store.list_habits(student_ref, _since(_days(days)))
    return HabitListResponse(
        student_ref=student_ref,
        records=records,
        streak=heal_store._streak(records),
        total_days=heal_store._total_days(records),
    )


# ---------------------------------------------------------------------------
# 专注学习（#9 / #12）
# ---------------------------------------------------------------------------

@router.post("/focus", response_model=FocusLogResponse)
def log_focus(request: FocusLogRequest) -> FocusLogResponse:
    session = heal_store.log_focus(
        request.student_ref, request.minutes, request.mood_before, request.mood_after)
    return FocusLogResponse(session=session)


@router.get("/focus", response_model=FocusListResponse)
def list_focus(
    student_ref: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    days: int = Query(default=30),
) -> FocusListResponse:
    sessions = heal_store.list_focus(student_ref, _since(_days(days)))
    return FocusListResponse(
        student_ref=student_ref,
        sessions=sessions,
        total_minutes=sum(s.minutes for s in sessions),
    )


# ---------------------------------------------------------------------------
# 成长回顾（#12）
# ---------------------------------------------------------------------------

@router.get("/growth", response_model=GrowthResponse)
def growth(
    student_ref: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    days: int = Query(default=90),
) -> GrowthResponse:
    window = _days(days)
    since = _since(window)
    moods = heal_store.list_moods(student_ref, since)
    habits = heal_store.list_habits(student_ref, since)
    focus = heal_store.list_focus(student_ref, since)

    tag_counts: dict[str, int] = {}
    for entry in moods:
        for tag in entry.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return GrowthResponse(
        student_ref=student_ref,
        days=window,
        mood_days=len({m.date for m in moods}),
        habit_days=heal_store._total_days(habits),
        streak=heal_store._streak(heal_store.list_habits(student_ref, "0000-01-01")),
        focus_sessions=len(focus),
        focus_minutes=sum(s.minutes for s in focus),
        mood_tag_counts=tag_counts,
        moods=moods,
        habits=habits,
    )


# ---------------------------------------------------------------------------
# 艺术表达「读画」（#8，可选增强）
# ---------------------------------------------------------------------------

@router.post("/art/reflect", response_model=ArtReflectResponse)
async def reflect_art(request: ArtReflectRequest) -> ArtReflectResponse:
    """把画面的客观特征交给大模型，写一段陪伴式解读。

    仅做语言生成：不落库、不参与风险判定。大模型不可用时返回 503，
    前端静默回退到本地回看文案。
    """
    try:
        text = await reflect_artwork(request.model_dump())
    except ArtReflectUnavailable:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ART_REFLECT_UNAVAILABLE",
                "message": "读画服务暂时不可用，已保留本地回看文案。",
            },
        ) from None
    return ArtReflectResponse(text=text)
