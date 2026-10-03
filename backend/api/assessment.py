"""评估结果 API。可直接接收上游提供的双层视觉评估输入。"""

from fastapi import APIRouter
from fastapi import HTTPException

from evaluation_agent.llm_client import LLMError
from evaluation_agent.inputs import EvaluationInput

from backend.api.errors import session_not_found
from backend.core.evaluation_engine import evaluation_engine
from backend.core.memory_store import memory_store
from backend.core.multimodal_fusion import build_vision_summary
from backend.core.session_manager import session_manager
from backend.models.enums import MessageRole, SessionStage
from backend.models.requests import TriggerAssessmentRequest
from backend.models.responses import AssessmentResponse
from backend.models.states import Message, SessionState, SessionVisionSummary

router = APIRouter(prefix="/api", tags=["assessment"])


@router.post("/assessment", response_model=AssessmentResponse)
def trigger_assessment(request: TriggerAssessmentRequest) -> AssessmentResponse:
    session = session_manager.get_session(request.session_id)
    if session is None:
        raise session_not_found()
    initial_history = session.conversation_history
    if request.evaluation_input is not None:
        _validate_speech_history(session, request.evaluation_input.dialogue_history)
    try:
        prepared_history = (
            _prepare_history(session, request.evaluation_input.dialogue_history)
            if request.evaluation_input is not None else None)
        working = session.model_copy(deep=True)
        if prepared_history is not None:
            working.conversation_history = prepared_history
        snapshots = [message.vision_snapshot for message in working.conversation_history
                     if message.role == MessageRole.USER and message.vision_snapshot is not None]
        if request.evaluation_input is not None and request.evaluation_input.vision_summary is not None:
            working.vision_summary = SessionVisionSummary.model_validate(
                request.evaluation_input.vision_summary.model_dump(mode="json"))
        elif snapshots:
            working.vision_summary = build_vision_summary(snapshots)
        elif prepared_history is not None and not _same_history(initial_history, prepared_history):
            # A summary belongs to its transcript; keep it only for unchanged-history retries.
            working.vision_summary = None
        data = None
        if request.evaluation_input is not None:
            data = EvaluationInput.model_validate({
                "dialogue_history": [message.model_dump(mode="json")
                                     for message in prepared_history],
                "vision_summary": working.vision_summary.model_dump(mode="json")
                                  if working.vision_summary is not None else None,
                "user_memory": request.evaluation_input.user_memory,
            })
        result = evaluation_engine.assess(working, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_EVALUATION_INPUT", "message": str(exc),
        }) from exc
    except LLMError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "EVALUATION_UNAVAILABLE",
            "message": "评估模型配置缺失或服务暂时不可用。",
        }) from exc

    def link(session: SessionState) -> None:
        if not _same_history(
                session.conversation_history, initial_history):
            raise HTTPException(status_code=409, detail={
                "code": "HISTORY_CONFLICT",
                "message": "评估期间对话已更新，请用最新完整记录重新评估。",
            })
        session.assessment_result_id = result.result_id
        session.current_stage = SessionStage.COMPLETED
        session.vision_summary = working.vision_summary
        if request.evaluation_input is not None:
            data = request.evaluation_input
            _validate_speech_history(session, data.dialogue_history)
            session.conversation_history = prepared_history
            session.turn_count = sum(
                item.role == MessageRole.USER for item in session.conversation_history
            )

    updated = session_manager.modify_session(request.session_id, link)
    if updated is None:
        raise session_not_found()
    memory_store.save_result(result)
    return AssessmentResponse(session_id=request.session_id, result=result)


def _same_history(previous, incoming) -> bool:
    return len(previous) == len(incoming) and all(
        left.role.value == right.role.value and left.content == right.content
        for left, right in zip(previous, incoming)
    )


def _validate_speech_history(session: SessionState, incoming) -> None:
    # Positional association is safe only for the complete unchanged transcript.
    # Reject ambiguous replacements before calling the external evaluation model.
    if any(item.speech is not None or item.utterance_id is not None
           for item in session.conversation_history) and not _same_history(
               session.conversation_history, incoming):
        raise HTTPException(status_code=409, detail={
            "code": "HISTORY_CONFLICT",
            "message": "已有发言标识的会话必须提交原完整对话，避免丢失录音元数据。",
        })


def _prepare_history(session: SessionState, incoming) -> list[Message]:
    """Preserve authoritative metadata; validate metadata on externally supplied history."""
    same = _same_history(session.conversation_history, incoming)
    prepared = []
    seen_ids = set()
    for index, item in enumerate(incoming):
        data = item.model_dump(mode="json", exclude_none=True)
        if same:
            original = session.conversation_history[index]
            supplied_id = data.get("utterance_id")
            supplied_speech = data.get("speech")
            if (supplied_id is not None and supplied_id != original.utterance_id) or (
                    supplied_speech is not None and supplied_speech != (
                        original.speech.model_dump(mode="json") if original.speech else None)):
                raise HTTPException(status_code=409, detail={
                    "code": "HISTORY_CONFLICT", "message": "评估输入中的录音标识或时间与原消息不一致。",
                })
            supplied_vision = item.vision_snapshot
            if supplied_vision is not None and (
                (original.vision_snapshot is not None and
                 supplied_vision.model_dump(mode="json", exclude={"timestamp"}) !=
                 original.vision_snapshot.model_dump(mode="json", exclude={"timestamp"})) or
                (original.vision_snapshot is None and original.utterance_id is not None)
            ):
                raise HTTPException(status_code=409, detail={
                    "code": "HISTORY_CONFLICT", "message": "已绑定发言的视觉快照不能被评估输入改写。"})
            data.update({"created_at": original.created_at,
                         "utterance_id": original.utterance_id,
                         "speech": original.speech, "audio_snapshot": original.audio_snapshot})
            if original.vision_snapshot is not None:
                data["vision_snapshot"] = original.vision_snapshot
        message = Message.model_validate(data)
        if message.speech is not None and message.utterance_id is None:
            raise ValueError("录音元数据需要 utterance_id")
        if message.utterance_id is not None:
            if message.utterance_id in seen_ids:
                raise ValueError("dialogue_history 中发言标识重复")
            seen_ids.add(message.utterance_id)
        prepared.append(message)
    return prepared


@router.get("/assessment/result/{result_id}", response_model=AssessmentResponse)
def get_result(result_id: str, session_id: str) -> AssessmentResponse:
    record = memory_store.get_record_by_result_id(result_id)
    if record is None or record.result.session_id != session_id:
        raise HTTPException(status_code=404, detail={
            "code": "RESULT_NOT_FOUND", "message": "Assessment result does not exist."})
    return AssessmentResponse(session_id=record.result.session_id, result=record.result)
