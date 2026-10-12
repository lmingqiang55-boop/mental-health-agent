"""治愈小工具数据模型（心情日记 / 微光打卡 / 专注记录 / 内容库）。

与 #13 治愈陪伴（``backend.models.healing``）相互独立：
本模块只服务前端「治愈航线」里的自查小工具，记录按匿名 student_ref 保存。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from backend.models.states import _now


class MoodEntry(BaseModel):
    """一条心情日记（按日期唯一，重复提交覆盖当天）。"""
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    mood: int = Field(ge=1, le=5, description="心情档位 1（最差）~ 5（最好）")
    weather: str | None = Field(default=None, max_length=20, description="自定义天气，如 晴/多云")
    color: str | None = Field(default=None, max_length=20, description="心情色，如 #FFD166")
    tags: list[str] = Field(default_factory=list, description="心情标签，如 焦虑/放松")
    note: str | None = Field(default=None, max_length=200)
    voice_text: str | None = Field(default=None, max_length=200, description="语音输入转写文本")
    updated_at: datetime = Field(default_factory=_now)


class HabitRecord(BaseModel):
    """一天的微光打卡（items 为已完成的微行动 id 列表）。"""
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    items: list[str] = Field(default_factory=list)


class FocusSession(BaseModel):
    """一次专注学习记录。"""
    session_id: str
    student_ref: str
    minutes: int = Field(ge=1, le=180)
    mood_before: int | None = Field(default=None, ge=1, le=5)
    mood_after: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime = Field(default_factory=_now)


class HealContent(BaseModel):
    """治愈工具箱内容卡片。"""
    id: str
    title: str
    tag: str
    type: str = Field(description="breath / meditation / noise / mindful / comic")
    cover: str
    desc: str
    moods: list[int] = Field(default_factory=list, description="适用的心情档位 1-5")
