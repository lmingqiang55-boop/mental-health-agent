"""评估后的人工跟进与双向沟通消息。"""

from datetime import datetime

from pydantic import BaseModel, Field

from backend.models.states import _now


class CounselorNote(BaseModel):
    """心理老师人工复核与跟进记录。"""

    note_id: str
    counselor_ref: str
    content: str
    created_at: datetime = Field(default_factory=_now)


class CommunicationMessage(BaseModel):
    """学生与心理老师双向互动沟通的消息。"""

    message_id: str
    student_ref: str
    counselor_ref: str | None = None
    direction: str = Field(description="student_to_counselor / counselor_to_student")
    content: str
    read: bool = False
    created_at: datetime = Field(default_factory=_now)
