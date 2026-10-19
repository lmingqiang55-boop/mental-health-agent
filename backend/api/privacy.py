"""学生隐私权接口：按匿名 student_ref 删除本机保存的全部个人数据。"""

from fastapi import APIRouter, Path

from backend.core.communication import communication_store
from backend.core.counseling_store import counseling_store
from backend.core.heal_store import heal_store
from backend.core.memory_store import memory_store
from backend.core.profile_store import profile_store
from backend.core.session_manager import session_manager
from backend.healing.store import healing_store


router = APIRouter(prefix="/api/privacy", tags=["privacy"])


@router.delete("/student/{student_ref}")
def delete_student_data(
    student_ref: str = Path(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
) -> dict:
    """永久删除该匿名身份在本机后端中的全部记录。

    数据分布在数个独立 SQLite 文件和进程内存中，因此返回每类删除数量，
    方便前端明确告知用户，而不是只清浏览器缓存后声称已经全部删除。
    """
    sessions = session_manager.delete_by_student(student_ref)
    deleted: dict[str, int] = {
        "assessment_records": memory_store.delete_by_student(student_ref),
        **heal_store.delete_by_student(student_ref),
        **profile_store.delete_by_student(student_ref),
        **counseling_store.delete_by_student(student_ref),
        "communication_messages": communication_store.delete_by_student(student_ref),
        "sessions": len(sessions),
        "healing_sessions": healing_store.delete_sessions(sessions),
    }
    return {
        "status": "deleted",
        "student_ref": student_ref,
        "deleted": deleted,
        "total": sum(deleted.values()),
    }
