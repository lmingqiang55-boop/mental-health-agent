"""历史记录 API（学生个人视角）。

学生按自己的匿名标识查看历史筛查记录与趋势。
同一浏览器复用匿名 student_ref；结果持续保存，直到用户主动删除。
"""

from fastapi import APIRouter, HTTPException, Path

from backend.core.memory_store import memory_store
from backend.models.responses import HistoryListResponse

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{student_ref}", response_model=HistoryListResponse)
def get_history(student_ref: str) -> HistoryListResponse:
    records = memory_store.list_by_student(student_ref)
    return HistoryListResponse(
        student_ref=student_ref, records=records, total=len(records))


@router.delete("/{student_ref}/{record_id}")
def delete_history_record(
    student_ref: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    record_id: str = Path(min_length=1, max_length=128),
) -> dict:
    if not memory_store.delete_record(student_ref, record_id):
        raise HTTPException(status_code=404, detail={
            "code": "RECORD_NOT_FOUND", "message": "未找到可删除的评估结果。"})
    return {"status": "deleted", "record_id": record_id}
