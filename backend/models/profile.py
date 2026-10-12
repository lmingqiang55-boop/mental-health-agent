"""学生档案与紧急联系人模型。

- 学生档案：昵称 / 学校阶段 / 班级，按匿名 student_ref 保存；
- 紧急联系人：学生信任的求助对象，同样按 student_ref 归属。

两者都只用于学生端自助展示与求助，不参与风险判定。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.models.states import _now


class EmergencyContact(BaseModel):
    """一名紧急联系人。"""

    id: str
    name: str = Field(min_length=1, max_length=20, description="称呼，如 妈妈 / 班主任王老师")
    relation: str = Field(default="", max_length=20, description="关系，选填")
    phone: str = Field(pattern=r"^[\d\-+\s]{3,20}$", description="手机或座机号码")
    created_at: datetime = Field(default_factory=_now)


class StudentProfile(BaseModel):
    """学生档案（昵称 / 学校阶段 / 班级）。"""

    student_ref: str
    nickname: str = Field(default="", max_length=20)
    school_stage: Literal["primary", "middle", "high"] | None = Field(
        default=None, description="学校阶段：小学 / 初中 / 高中"
    )
    class_name: str = Field(default="", max_length=40, description="班级，如 初二(3)班")
    updated_at: datetime = Field(default_factory=_now)
