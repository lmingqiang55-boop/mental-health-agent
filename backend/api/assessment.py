"""评估结果 API。

- 手动触发多模态综合评估（正常流程由 chat 在对话结束时自动触发）。
- 按 result_id / session_id 获取评估结果。
"""

from fastapi import APIRouter
from fastapi import HTTPException

from backend.api.errors import session_not_found
from backend.core.assessment_engine import assessment_engine
from backend.core.memory_store import memory_store
from backend.core.session_manager import session_manager
from backend.core.multimodal_fusion import (
    build_audio_summary,
    build_vision_summary,
)
from backend.models.enums import SessionStage
from backend.models.requests import TriggerAssessmentRequest
from backend.models.responses import AssessmentResponse
from backend.models.states import SessionState

router = APIRouter(prefix="/api", tags=["assessment"])


@router.post("/assessment", response_model=AssessmentResponse)
def trigger_assessment(request: TriggerAssessmentRequest) -> AssessmentResponse:
    def prepare(session: SessionState) -> None:
        if session.vision_summary is None:
            session.vision_summary = build_vision_summary(
                session.vision_state_log)
        if session.audio_summary is None:
            session.audio_summary = build_audio_summary(
                session.audio_state_log)
        session.current_stage = SessionStage.ASSESSMENT

    updated = session_manager.modify_session(request.session_id, prepare)
    if updated is None:
        raise session_not_found()

    result = assessment_engine.assess(updated)
    memory_store.save_result(result)

    def link(session: SessionState) -> None:
        session.assessment_result_id = result.result_id
        session.current_stage = SessionStage.COMPLETED

    session_manager.modify_session(request.session_id, link)
    return AssessmentResponse(session_id=request.session_id, result=result)


@router.get("/assessment/result/{result_id}", response_model=AssessmentResponse)
def get_result(result_id: str, session_id: str) -> AssessmentResponse:
    record = memory_store.get_record(result_id)
    if record is None:
        raise HTTPException(status_code=404, detail={
            "code": "RESULT_NOT_FOUND", "message": "Assessment result does not exist."})
    return AssessmentResponse(session_id=session_id, result=record.result)
