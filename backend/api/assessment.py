"""评估结果 API。可直接接收上游提供的双层视觉评估输入。"""

from fastapi import APIRouter
from fastapi import HTTPException

from evaluation_agent.llm_client import LLMError

from backend.api.errors import session_not_found
from backend.core.evaluation_engine import evaluation_engine
from backend.core.memory_store import memory_store
from backend.core.session_manager import session_manager
from backend.models.enums import MessageRole, SessionStage
from backend.models.requests import TriggerAssessmentRequest
from backend.models.responses import AssessmentResponse
from backend.models.states import Message, SessionState, SessionVisionSummary, VisionState

router = APIRouter(prefix="/api", tags=["assessment"])


@router.post("/assessment", response_model=AssessmentResponse)
def trigger_assessment(request: TriggerAssessmentRequest) -> AssessmentResponse:
    session = session_manager.get_session(request.session_id)
    if session is None:
        raise session_not_found()
    try:
        result = evaluation_engine.assess(session, request.evaluation_input)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_EVALUATION_INPUT", "message": str(exc),
        }) from exc
    except LLMError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "EVALUATION_UNAVAILABLE",
            "message": "评估模型配置缺失或服务暂时不可用。",
        }) from exc
    memory_store.save_result(result)

    def link(session: SessionState) -> None:
        session.assessment_result_id = result.result_id
        session.current_stage = SessionStage.COMPLETED
        if request.evaluation_input is not None:
            data = request.evaluation_input
            session.conversation_history = [
                Message(
                    role=MessageRole(item.role.value),
                    content=item.content,
                    vision_snapshot=(
                        VisionState.model_validate(
                            item.vision_snapshot.model_dump(
                                mode="json", exclude_none=True
                            )
                        )
                        if item.vision_snapshot is not None else None
                    ),
                )
                for item in data.dialogue_history
            ]
            session.turn_count = sum(
                item.role == MessageRole.USER for item in session.conversation_history
            )
            session.vision_summary = (
                SessionVisionSummary.model_validate(
                    data.vision_summary.model_dump(mode="json")
                )
                if data.vision_summary is not None else None
            )

    session_manager.modify_session(request.session_id, link)
    return AssessmentResponse(session_id=request.session_id, result=result)


@router.get("/assessment/result/{result_id}", response_model=AssessmentResponse)
def get_result(result_id: str, session_id: str) -> AssessmentResponse:
    record = memory_store.get_record_by_result_id(result_id)
    if record is None or record.result.session_id != session_id:
        raise HTTPException(status_code=404, detail={
            "code": "RESULT_NOT_FOUND", "message": "Assessment result does not exist."})
    return AssessmentResponse(session_id=record.result.session_id, result=record.result)
