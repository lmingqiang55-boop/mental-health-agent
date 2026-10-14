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
from backend.healing.client import HealingJSONClient, HealingUnavailable
from backend.models.counseling import (
    Appointment,
    AppointmentCreate,
    AppointmentListResponse,
    AppointmentResponse,
    AppointmentStatusUpdate,
    ICBTAnalyzeRequest,
    ICBTAnalyzeResponse,
    ICBTCatalogResponse,
    ICBTProgressResponse,
    ICBTProgressUpdate,
    ICBTUnitListResponse,
    ICBTUnitUpdate,
    ICBTUnitView,
)

router = APIRouter(prefix="/api/counseling", tags=["counseling"])
icbt_router = APIRouter(prefix="/api/heal/icbt", tags=["icbt"])

# 大模型「想法自查」客户端：复用现有 DeepSeek 连接与有界 JSON 生成。
_icbt_client = HealingJSONClient()

_ICBT_ANALYZE_SYSTEM = """你是「小晴」，一位温和、尊重学生的 CBT（认知行为疗法）自助陪伴助手，服务对象是中学生。
任务：阅读学生写下的一句自我陈述，帮他看见其中可能存在的「思维陷阱」（认知偏差），并给出一句更有弹性的改写。

【可选的思维陷阱（name 只能从这里取）】
- 全或无：把结果分成「全好 / 全坏」，忽略中间地带
- 以偏概全：用一次或部分的经历，概括成「总是 / 所有人都这样」
- 灾难化：把可能的小事想成最坏、无法承受的结果
- 贴标签：用一句话给自己或别人下定义
- 读心术：认定别人怎么想，并把它当成事实
- 情绪化推理：把「我感觉」当成「事实就是」
- 应该式：用「必须 / 应该」要求自己或他人

【要求】
1. 只有确实贴合时才标注，不要牵强；同一句最多标注 2 条最贴合、最值得被看见的。
2. 不要把「一次具体的不顺」误判成「没有偏差」，也不要为了凑数而标注；确实没有明显偏差时 biases 给空数组。
3. 语气温暖、平等，不说教、不评判、不下诊断。
4. reframe：给一句学生自己可以说出口、更柔软有弹性的话（第一人称）。
5. encouragement：一句简短真诚的支持，不超过 40 字。
6. question：一个温和的追问，帮学生继续觉察，不超过 30 字。
7. 若文本中有伤害自己或他人的念头，不要标注偏差，改为表达关心并鼓励他立刻告诉信任的成年人或拨打 12356。

【输出协议】只输出 JSON，不要任何解释或代码块：
{"biases":[{"name":"","hint":""}],"reframe":"","encouragement":"","question":""}
"""


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


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

@icbt_router.get("/catalog", response_model=ICBTCatalogResponse)
def get_icbt_catalog() -> ICBTCatalogResponse:
    """学生端目录：已发布单元的正文与循证出处。"""
    units = [u for u in counseling_store.list_units() if u.status == "published"]
    units.sort(key=lambda u: u.order)
    return ICBTCatalogResponse(units=units)


@icbt_router.post("/analyze", response_model=ICBTAnalyzeResponse)
async def analyze_icbt_thought(request: ICBTAnalyzeRequest) -> ICBTAnalyzeResponse:
    """想法自查：由大模型标注可能的认知偏差，并给出弹性改写与一句支持。

    失败一律抛 503，由前端静默回退到本地关键词规则，页面永远可用。
    """
    payload = {"text": request.text}
    if request.unit_title:
        payload["正在练习的单元"] = {
            "title": request.unit_title,
            "goal": request.unit_goal or "",
        }
    try:
        return await _icbt_client.generate(
            _ICBT_ANALYZE_SYSTEM, payload, ICBTAnalyzeResponse, max_tokens=800)
    except HealingUnavailable:
        raise error(503, "ICBT_ANALYZE_UNAVAILABLE", "小晴暂时没能分析，请稍后再试。") from None


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
