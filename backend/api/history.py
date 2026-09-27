"""历史记录 API（学生个人视角）。

学生按自己的匿名标识查看历史筛查记录与趋势。
当前 session_id 可作为临时 student_ref。
"""

from fastapi import APIRouter

from backend.core.memory_store import memory_store
from backend.models.responses import HistoryListResponse

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{student_ref}", response_model=HistoryListResponse)
def get_history(student_ref: str) -> HistoryListResponse:
    records = memory_store.list_by_student(student_ref)
    return HistoryListResponse(
        student_ref=student_ref, records=records, total=len(records))
