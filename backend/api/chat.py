from threading import RLock

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.api.errors import session_not_found
from backend.core.dialogue_manager import DialogueManager
from backend.core.session_manager import session_manager
from backend.models.response import ChatResponse
from backend.models.states import Message


router = APIRouter(prefix="/api", tags=["chat"])
dialogue_manager = DialogueManager()
chat_lock = RLock()


class ChatRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=4000)


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if not request.text.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR", "message": "Text cannot be blank."
        })
    with chat_lock:
        session = session_manager.get_session(request.session_id)
        if session is None:
            raise session_not_found()
        session.conversation_history.append(Message(role="user", content=request.text.strip()))
        result = dialogue_manager.process_turn(
            request.text.strip(), session,
            session.latest_vision_state, session.latest_audio_state,
        )
        session.conversation_history.append(Message(role="assistant", content=result.reply))
        session.turn_count += 1
        session_manager.update_session(
            request.session_id,
            conversation_history=session.conversation_history,
            turn_count=session.turn_count,
            current_stage=session.current_stage,
            assessment_state=session.assessment_state,
            latest_risk=session.latest_risk,
        )
        return ChatResponse(session_id=request.session_id, turn_count=session.turn_count,
                            **result.model_dump())
