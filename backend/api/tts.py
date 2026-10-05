"""Read a saved assistant reply and return its synthesized audio."""

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.api.errors import session_not_found
from backend.audio.tts import TTSError, get_tts_service
from backend.core.session_manager import session_manager
from backend.models.enums import MessageRole
from backend.models.states import SessionState


router = APIRouter(prefix="/api/tts", tags=["tts"])


class SynthesizeRequest(BaseModel):
    session_id: str
    turn_count: int = Field(ge=0)


@router.get("/status")
def tts_status() -> dict:
    service = get_tts_service()
    return {"state": "ready" if service.config.ready else "unconfigured",
            "model": service.config.model if service.config.ready else None,
            "voice": service.config.voice if service.config.ready else None}


@router.post("", response_class=Response)
async def synthesize_reply(request: SynthesizeRequest) -> Response:
    session = await asyncio.to_thread(session_manager.get_session, request.session_id)
    if session is None:
        raise session_not_found()
    if request.turn_count == 0:
        opening = session.conversation_history[0] if session.conversation_history else None
        if opening is None or opening.role != MessageRole.ASSISTANT:
            raise HTTPException(status_code=404, detail={
                "code": "REPLY_NOT_FOUND", "message": "这轮回复不存在。"})
        text = opening.content
    else:
        text = _reply_for_turn(session, request.turn_count)
    if not text.strip() or len(text) > 2000:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_TTS_TEXT", "message": "这轮回复无法合成语音。"})
    try:
        audio = await get_tts_service().synthesize(text)
    except TTSError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "TTS_UNAVAILABLE", "message": str(exc)}) from exc
    return Response(content=audio, media_type="audio/mpeg",
                    headers={"Cache-Control": "no-store"})


def _reply_for_turn(session: SessionState, turn_count: int) -> str:
    replies = []
    user_turns = 0
    for message in session.conversation_history:
        if message.role == MessageRole.USER:
            user_turns += 1
        elif message.role == MessageRole.ASSISTANT and user_turns > len(replies):
            # The fixed opening question precedes the first user turn.
            replies.append(message.content)
    if turn_count > session.turn_count or turn_count > len(replies):
        raise HTTPException(status_code=404, detail={
            "code": "REPLY_NOT_FOUND", "message": "这轮回复不存在。"})
    return replies[turn_count - 1]
