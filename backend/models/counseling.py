"""咨询预约与 iCBT 数据模型（自包含 domain / 请求 / 响应）。

- 咨询预约（#10）：学生提交预约意向 → 管理端列表 / 确认 / 取消 / 转介
- iCBT（#9）：单元目录 + 学生完成度上报 → 管理端查看完成度

与筛查主链路解耦，仅按匿名 student_ref 关联。
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.models.states import _now

AppointmentStatus = Literal["pending", "confirmed", "done", "cancelled"]
AppointmentSource = Literal["student", "teacher", "warning"]
ICBTStatus = Literal["draft", "published", "offline"]

_STUDENT_REF = r"^[A-Za-z0-9_-]+$"


class Appointment(BaseModel):
    """一条咨询预约记录。slot 统一为 'YYYY-MM-DD HH:MM'。"""

    id: str
    student_ref: str
    student_name: str | None = Field(default=None, max_length=64)
    class_name: str | None = Field(default=None, max_length=64)
    counselor: str | None = Field(default=None, max_length=64)
    slot: str = Field(max_length=32)
    preferred_label: str | None = Field(default=None, max_length=64, description="学生端原始时段文案")
    duration: int = Field(default=50, ge=10, le=180)
    room: str | None = Field(default=None, max_length=64)
    topic: str | None = Field(default=None, max_length=200)
    status: AppointmentStatus = "pending"
    source: AppointmentSource = "student"
    created_at: datetime = Field(default_factory=_now)


class AppointmentCreate(BaseModel):
    """创建预约意向。管理端直接给 slot；学生端给 date + preferred_label 由后端归一化。"""

    student_ref: str = Field(min_length=1, max_length=128, pattern=_STUDENT_REF)
    student_name: str | None = Field(default=None, max_length=64)
    class_name: str | None = Field(default=None, max_length=64)
    counselor: str | None = Field(default=None, max_length=64)
    slot: str | None = Field(default=None, max_length=32, description="'YYYY-MM-DD HH:MM'")
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    preferred_label: str | None = Field(default=None, max_length=64)
    duration: int = Field(default=50, ge=10, le=180)
    room: str | None = Field(default=None, max_length=64)
    topic: str | None = Field(default=None, max_length=200)
    status: AppointmentStatus = "pending"
    source: AppointmentSource = "student"

    @model_validator(mode="after")
    def normalize_slot(self) -> "AppointmentCreate":
        if self.slot:
            return self
        match = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", self.preferred_label or "")
        hour, minute = (match.group(1), match.group(2)) if match else ("12", "30")
        time_part = f"{int(hour):02d}:{minute}"
        self.slot = f"{self.date} {time_part}" if self.date else time_part
        return self


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus


class ICBTUnit(BaseModel):
    """一个 iCBT 单元。

    ``steps`` 是步骤数量（管理端展示用的计数），单元正文存在 ``content_steps``，
    两者互不影响：管理端仍可只改计数/标题，学生端读到的是完整正文。
    """

    id: str
    no: int = Field(ge=1)
    title: str = Field(max_length=64)
    module: str = Field(max_length=32)
    order: int = Field(ge=1)
    steps: int = Field(ge=1, le=20)
    est_minutes: int = Field(default=10, ge=1, le=120)
    status: ICBTStatus = "published"
    audience: str | None = Field(default=None, max_length=64)
    goal: str = Field(default="", max_length=200, description="本单元要达成的小目标")
    content_steps: list[str] = Field(default_factory=list, description="单元正文步骤（学生端渲染）")
    source: str = Field(default="", max_length=120, description="循证出处，如 CBT 认知模型")
    source_note: str = Field(default="", max_length=300, description="出处补充说明")
    updated_at: datetime = Field(default_factory=_now)


class ICBTUnitUpdate(BaseModel):
    """部分更新单元；仅传入字段生效。"""

    title: str | None = Field(default=None, max_length=64)
    module: str | None = Field(default=None, max_length=32)
    order: int | None = Field(default=None, ge=1)
    steps: int | None = Field(default=None, ge=1, le=20)
    est_minutes: int | None = Field(default=None, ge=1, le=120)
    status: ICBTStatus | None = None
    audience: str | None = Field(default=None, max_length=64)


class ICBTProgress(BaseModel):
    """一个学生的 iCBT 完成情况。"""

    student_ref: str
    completed_units: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_now)


class ICBTProgressUpdate(BaseModel):
    student_ref: str = Field(min_length=1, max_length=128, pattern=_STUDENT_REF)
    completed_units: list[str] = Field(default_factory=list)


# ---------- 响应 ----------

class AppointmentResponse(BaseModel):
    appointment: Appointment


class AppointmentListResponse(BaseModel):
    appointments: list[Appointment]
    total: int


class ICBTUnitView(ICBTUnit):
    """管理端视图：附带参与/完成人数。"""

    assigned: int = 0
    completed: int = 0


class ICBTUnitListResponse(BaseModel):
    units: list[ICBTUnitView]


class ICBTCatalogResponse(BaseModel):
    """学生端目录：仅含已发布单元的正文/来源，不含管理端统计。"""

    units: list[ICBTUnit]


class ICBTProgressResponse(BaseModel):
    student_ref: str
    completed_units: list[str]
    updated_at: datetime | None = None


# ---------- 想法自查（大模型辅助，认知偏差标注）----------

class ICBTAnalyzeRequest(BaseModel):
    """学生写下的一句话；可选带上正在练习的单元，让小晴的回应更贴合。"""

    text: str = Field(min_length=1, max_length=1000, description="学生写下的想法/自我陈述")
    unit_title: str | None = Field(default=None, max_length=64)
    unit_goal: str | None = Field(default=None, max_length=200)


class ICBTBias(BaseModel):
    """命中的一条认知偏差。"""

    name: str = Field(default="", max_length=32)
    hint: str = Field(default="", max_length=200)


class ICBTAnalyzeResponse(BaseModel):
    """小晴的分析结果；全部字段都有默认值，单个字段缺失不影响整体可用。"""

    biases: list[ICBTBias] = Field(default_factory=list)
    reframe: str = Field(default="", max_length=500, description="更有弹性的改写建议")
    encouragement: str = Field(default="", max_length=300, description="一句简短的支持")
    question: str = Field(default="", max_length=200, description="温和的追问，帮学生继续觉察")
