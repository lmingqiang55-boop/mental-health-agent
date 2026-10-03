"""心理老师端 API（专业视角，C 模块）。

对应目标图三大块：
1. 个体筛查管理：记录列表、个体详情、历史变化
2. 高风险预警与干预：高风险名单、人工跟进记录
3. 群体心理统计：聚合概览（框架占位）

注意：当前没有身份认证，这是框架骨架；接入真实权限前不得连接真实学生数据。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.memory_store import memory_store
from backend.models.enums import RiskLevel

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


class CounselorNoteRequest(BaseModel):
    counselor_ref: str
    content: str


# -- 1. 个体筛查管理 ----------------------------------------------------

@router.get("/records")
def list_all_records() -> dict:
    records = memory_store.list_all_records()
    summaries = [
        {
            "record_id": r.record_id,
            "student_ref": r.student_ref,
            "concern_index": r.result.concern_index,
            "overall_level": r.result.overall_level.value,
            "risk_level": r.result.risk.risk_level.value,
            "created_at": r.created_at,
            "follow_up_status": r.follow_up_status.value,
        }
        for r in records
    ]
    return {"records": summaries, "total": len(summaries)}


@router.get("/records/{record_id}")
def get_record_detail(record_id: str) -> dict:
    record = memory_store.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail={
            "code": "RECORD_NOT_FOUND", "message": "Record does not exist."})
    return {"record": record}


@router.get("/student/{student_ref}")
def get_student_history(student_ref: str) -> dict:
    records = memory_store.list_by_student(student_ref)
    return {"student_ref": student_ref, "records": records,
            "total": len(records)}


# -- 2. 高风险预警与干预 ------------------------------------------------

@router.get("/high-risk")
def list_high_risk() -> dict:
    records = memory_store.list_all_records()
    high = [r for r in records
            if r.result.risk.risk_level in {RiskLevel.HIGH, RiskLevel.MEDIUM}]
    return {
        "high_risk_count": len(high),
        "students": [
            {
                "record_id": r.record_id,
                "student_ref": r.student_ref,
                "risk_level": r.result.risk.risk_level.value,
                "risk_types": r.result.risk.risk_types,
                "risk_reasons": r.result.risk.risk_reasons,
                "key_evidence": r.result.risk.key_evidence,
                "follow_up_status": r.follow_up_status.value,
            }
            for r in high
        ],
    }


@router.post("/records/{record_id}/notes")
def add_follow_up_note(record_id: str,
                       request: CounselorNoteRequest) -> dict:
    updated = memory_store.add_counselor_note(
        record_id, request.counselor_ref, request.content)
    if updated is None:
        raise HTTPException(status_code=404, detail={
            "code": "RECORD_NOT_FOUND", "message": "Record does not exist."})
    return {"status": "added", "record": updated}


# -- 3. 群体心理统计（框架占位） ---------------------------------------

@router.get("/group-stats")
def group_stats() -> dict:
    records = memory_store.list_all_records()
    # Each student contributes their latest assessment once, even when they
    # have multiple results in the three-assessment memory.
    latest_by_student = {record.student_ref: record for record in records}
    current_records = list(latest_by_student.values())
    total = len(current_records)
    if total == 0:
        return {"total_students": 0, "risk_distribution": {},
                "dimension_averages": {}}

    distribution = {"low": 0, "medium": 0, "high": 0}
    dim_acc: dict[str, list[float]] = {}
    for r in current_records:
        distribution[r.result.risk.risk_level.value] += 1
        for dimension, score in r.result.psychological_profile.model_dump().items():
            dim_acc.setdefault(dimension, []).append(score)

    dimension_averages = {
        dim: round(sum(vals) / len(vals), 3)
        for dim, vals in dim_acc.items()
    }
    return {
        "total_students": total,
        "risk_distribution": distribution,
        "dimension_averages": dimension_averages,
    }
