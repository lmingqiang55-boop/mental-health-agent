"""Read a saved assistant reply and return its synthesized audio."""

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.api.errors import session_not_found
from backend.audio.tts import TTSError, get_tts_service
from backend.core.session_manager import session_manager
from backend.models.enums import MessageRole


router = APIRouter(prefix="/api/tts", tags=["tts"])


class SynthesizeRequest(BaseModel):
    session_id: str
    turn_count: int = Field(ge=1)


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
    replies = [message.content for message in session.conversation_history
               if message.role == MessageRole.ASSISTANT]
    if request.turn_count > session.turn_count or request.turn_count > len(replies):
        raise HTTPException(status_code=404, detail={
            "code": "REPLY_NOT_FOUND", "message": "这轮回复不存在。"})
    text = replies[request.turn_count - 1]
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
