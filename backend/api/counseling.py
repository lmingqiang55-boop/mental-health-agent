"""咨询预约与 iCBT API。

两个 router：
- ``router``      → /api/counseling/appointments （管理端 + 学生端共用）
- ``icbt_router`` → /api/heal/icbt/units|progress （学生端读写 / 管理端查看）

注意：状态变更一律用 POST/PUT，避免依赖 PATCH（CORS 白名单不含 PATCH）。
"""

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from backend.core.counseling_store import counseling_store
from backend.core.profile_store import profile_store
from backend.models.counseling import (
    Appointment,
    AppointmentCreate,
    AppointmentListResponse,
    AppointmentResponse,
    AppointmentStatusUpdate,
    ICBTProgressResponse,
    ICBTProgressUpdate,
    ICBTUnitListResponse,
    ICBTUnitUpdate,
    ICBTUnitView,
)

router = APIRouter(prefix="/api/counseling", tags=["counseling"])
icbt_router = APIRouter(prefix="/api/heal/icbt", tags=["icbt"])


# ---------------------------------------------------------------------------
# 咨询预约（#10）
# ---------------------------------------------------------------------------

@router.get("/appointments", response_model=AppointmentListResponse)
def list_appointments(
    student_ref: str | None = Query(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
) -> AppointmentListResponse:
    appointments = counseling_store.list_appointments(student_ref)
    return AppointmentListResponse(appointments=appointments, total=len(appointments))


@router.post("/appointments", response_model=AppointmentResponse)
def create_appointment(request: AppointmentCreate) -> AppointmentResponse:
    # 学生端只带 student_ref，这里按档案补全姓名/班级，避免管理端列表出现空白。
    student_name, class_name = request.student_name, request.class_name
    if not student_name or not class_name:
        profile = profile_store.get_profile(request.student_ref)
        student_name = student_name or profile.nickname or None
        class_name = class_name or profile.class_name or None
    appointment = Appointment(
        id=f"apt-{uuid4().hex[:10]}",
        student_ref=request.student_ref,
        student_name=student_name,
        class_name=class_name,
        counselor=request.counselor,
        slot=request.slot or "",
        preferred_label=request.preferred_label,
        duration=request.duration,
        room=request.room,
        topic=request.topic,
        status=request.status,
        source=request.source,
    )
    return AppointmentResponse(appointment=counseling_store.create_appointment(appointment))


@router.post("/appointments/{appointment_id}/status", response_model=AppointmentResponse)
def update_appointment_status(appointment_id: str,
                              request: AppointmentStatusUpdate) -> AppointmentResponse:
    appointment = counseling_store.set_appointment_status(appointment_id, request.status)
    if appointment is None:
        raise HTTPException(status_code=404, detail={
            "code": "APPOINTMENT_NOT_FOUND", "message": "Appointment does not exist."})
    return AppointmentResponse(appointment=appointment)


# ---------------------------------------------------------------------------
# iCBT（#9）
# ---------------------------------------------------------------------------

@icbt_router.get("/units", response_model=ICBTUnitListResponse)
def list_icbt_units() -> ICBTUnitListResponse:
    assigned, counts = counseling_store.unit_completion()
    units = [
        ICBTUnitView(**unit.model_dump(), assigned=assigned,
                     completed=counts.get(unit.id, 0))
        for unit in counseling_store.list_units()
    ]
    return ICBTUnitListResponse(units=units)


@icbt_router.put("/units/{unit_id}", response_model=ICBTUnitView)
def update_icbt_unit(unit_id: str, request: ICBTUnitUpdate) -> ICBTUnitView:
    unit = counseling_store.update_unit(unit_id, request)
    if unit is None:
        raise HTTPException(status_code=404, detail={
            "code": "ICBT_UNIT_NOT_FOUND", "message": "Unit does not exist."})
    assigned, counts = counseling_store.unit_completion()
    return ICBTUnitView(**unit.model_dump(), assigned=assigned,
                        completed=counts.get(unit.id, 0))


@icbt_router.get("/progress", response_model=ICBTProgressResponse)
def get_icbt_progress(
    student_ref: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
) -> ICBTProgressResponse:
    progress = counseling_store.get_progress(student_ref)
    return ICBTProgressResponse(
        student_ref=progress.student_ref,
        completed_units=progress.completed_units,
        updated_at=progress.updated_at,
    )


@icbt_router.post("/progress", response_model=ICBTProgressResponse)
def set_icbt_progress(request: ICBTProgressUpdate) -> ICBTProgressResponse:
    progress = counseling_store.set_progress(request.student_ref, request.completed_units)
    return ICBTProgressResponse(
        student_ref=progress.student_ref,
        completed_units=progress.completed_units,
        updated_at=progress.updated_at,
    )
