"""治愈小工具数据模型（心情日记 / 微光打卡 / 专注记录 / 内容库）。

与 #13 治愈陪伴（``backend.models.healing``）相互独立：
本模块只服务前端「治愈航线」里的自查小工具，记录按匿名 student_ref 保存。
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from backend.models.states import _now


#: 心情档位（1 最差 ~ 5 最好）→ 该档位常见的心情标签。
#: 取值必须落在 :data:`MOOD_TAGS` 那套词里：学生端「按此刻的心情看看」就是拿
#: 这些词去匹配内容卡片的 ``tags``（见 ``HealContent.fill_display_fields``）。
MOOD_LEVEL_TAGS: dict[int, tuple[str, ...]] = {
    1: ("想哭", "委屈", "孤单"),
    2: ("焦虑", "紧张", "累"),
    3: ("烦躁", "生气", "无聊", "困"),
    4: ("平静", "放松"),
    5: ("开心", "有精神"),
}

#: 心情标签候选（内容库的筛选候选词）。顺序即学生端筛选 chip 的展示顺序。
#:
#: **每个词都必须至少被一个档位分组覆盖**（见 :data:`MOOD_LEVEL_TAGS`）：内容卡片的
#: ``tags`` 只由档位分组推导，候选表里多出来的词点下去就是一张空列表（"被理解"曾经
#: 就是这样，已删）。反过来，档位分组里的词也必须在候选表里——两张表放在同一个文件里
#: 就是为了改一处时能立刻看到另一处；``tests/test_heal_mood_tags.py`` 双向守这条规则。
#:
#: 注意它**不是**心情日记「和什么有关」的标签（那是学生端自己的场景词表，例如
#: 学习/人际/家庭），两者的含义与消费者都不同，别合并。
MOOD_TAGS: list[str] = [
    "开心", "平静", "放松", "有精神",
    "累", "困", "烦躁", "焦虑", "委屈",
    "孤单", "生气", "无聊", "紧张", "想哭",
]


class MoodEntry(BaseModel):
    """一条心情日记（按日期唯一，重复提交覆盖当天）。

    ``tags`` 是学生端心情日记里「和什么有关」的场景标签，由学生端自己给出、后端
    不校验，供 ``/api/heal/growth`` 聚合出「常出现的心情标签」。它与
    :data:`MOOD_TAGS`（内容库筛选候选词）**不是同一套词**，别再按后者去校验或过滤。
    """
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    mood: int = Field(ge=1, le=5, description="心情档位 1（最差）~ 5（最好）")
    weather: str | None = Field(default=None, max_length=20, description="自定义天气，如 晴/多云")
    color: str | None = Field(default=None, max_length=20, description="心情色，如 #FFD166")
    tags: list[str] = Field(default_factory=list, description="场景标签，如 学习/人际")
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
    """治愈工具箱内容卡片。

    ``category`` / ``tags`` / ``summary`` 是学生端页面**直接读取**的三个字段
    （``frontend-vue/student/src/views/heal/Toolkit.vue``：分类标签取
    ``c.category``、按心情筛选取 ``c.tags?.includes(tag)``、简介取 ``c.summary``
    或 ``c.body``）。它们不需要在内容清单里重复填写，由 ``tag`` / ``moods`` /
    ``desc`` 推导，避免两份数据各自漂移。
    """
    id: str
    title: str
    tag: str
    type: str = Field(description="breath / meditation / noise / mindful / comic")
    cover: str
    desc: str
    moods: list[int] = Field(default_factory=list, description="适用的心情档位 1-5")

    category: str = Field(default="", description="展示用分类，默认取 tag")
    tags: list[str] = Field(
        default_factory=list,
        description="心情标签，取值与 MOOD_TAGS 同一套词，供前端按心情筛选")
    summary: str = Field(default="", description="展示用简介，默认取 desc")

    @model_validator(mode="after")
    def fill_display_fields(self) -> "HealContent":
        if not self.category:
            self.category = self.tag
        if not self.summary:
            self.summary = self.desc
        if not self.tags:
            merged: list[str] = []
            for level in sorted(self.moods):
                for label in MOOD_LEVEL_TAGS.get(level, ()):
                    if label not in merged:
                        merged.append(label)
            self.tags = merged
        return self
