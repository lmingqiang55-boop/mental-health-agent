from threading import RLock

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.assessment.engine import AssessmentEngine
from backend.assessment.extractor import ExtractionUnavailable
from backend.assessment.models import AssessmentReport, AssessmentSession, build_report
from backend.assessment.question_generator import (
    QuestionActionRejected, QuestionGenerationUnavailable,
)


def _action_rejected(exc: QuestionActionRejected) -> HTTPException:
    """A model proposed an action the program refuses to execute.

    The turn is not committed and nothing is silently substituted, so the caller
    can retry: an illegal topic or an invented quote never becomes a question.
    """
    return HTTPException(status_code=503, detail={
        "code": "QUESTION_ACTION_REJECTED",
        "message": f"The decider proposed an illegal action ({exc.code}). Please retry this turn.",
    })


router = APIRouter(prefix="/api/assessment", tags=["assessment"])
engine = AssessmentEngine()
_sessions: dict[str, AssessmentSession] = {}
_lock = RLock()


class AnswerRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class CreateAssessmentRequest(BaseModel):
    grade: int | None = Field(default=None, ge=1, le=12)


class AssessmentTurnResponse(BaseModel):
    session_id: str
    status: str
    current_item_id: str | None
    reply: str
    report: AssessmentReport


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={
        "code": "ASSESSMENT_NOT_FOUND", "message": "Assessment session does not exist."
    })


@router.post("", response_model=AssessmentTurnResponse)
def create_assessment(request: CreateAssessmentRequest | None = None) -> AssessmentTurnResponse:
    try:
        state, reply = engine.start(grade=request.grade if request else None)
    except QuestionActionRejected as exc:
        raise _action_rejected(exc) from exc
    except QuestionGenerationUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "code": "QUESTION_GENERATION_UNAVAILABLE",
            "message": "Question generation is temporarily unavailable. Please retry.",
        }) from exc
    with _lock:
        _sessions[state.session_id] = state
    return AssessmentTurnResponse(
        session_id=state.session_id, status=state.status,
        current_item_id=state.current_item_id, reply=reply,
        report=build_report(state),
    )


@router.post("/{session_id}/turn", response_model=AssessmentTurnResponse)
def answer_assessment(session_id: str, request: AnswerRequest) -> AssessmentTurnResponse:
    if not request.text.strip():
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR", "message": "Text cannot be blank."
        })
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            raise _not_found()
        if state.status != "in_progress":
            raise HTTPException(status_code=409, detail={
                "code": "ASSESSMENT_CLOSED", "message": "Assessment is complete, stopped, or paused."
            })
        try:
            updated, reply = engine.process(state, request.text)
        except ExtractionUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": "EXTRACTION_UNAVAILABLE",
                "message": "Assessment extraction is temporarily unavailable. Please retry this turn.",
            }) from exc
        except QuestionActionRejected as exc:
            raise _action_rejected(exc) from exc
        except QuestionGenerationUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": "QUESTION_GENERATION_UNAVAILABLE",
                "message": "Question generation is temporarily unavailable. Please retry this turn.",
            }) from exc
        _sessions[session_id] = updated
        return AssessmentTurnResponse(
            session_id=session_id, status=updated.status,
            current_item_id=updated.current_item_id, reply=reply,
            report=build_report(updated),
        )


@router.get("/{session_id}", response_model=AssessmentSession)
def get_assessment(session_id: str) -> AssessmentSession:
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            raise _not_found()
        return state.model_copy(deep=True)


@router.get("/{session_id}/report", response_model=AssessmentReport)
def get_assessment_report(session_id: str) -> AssessmentReport:
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            raise _not_found()
        return build_report(state)


@router.delete("/{session_id}")
def delete_assessment(session_id: str) -> dict[str, str]:
    with _lock:
        if _sessions.pop(session_id, None) is None:
            raise _not_found()
    return {"status": "deleted"}
