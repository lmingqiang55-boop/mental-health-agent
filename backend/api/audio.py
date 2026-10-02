"""音频状态 API（C 接入，B 输出）。

- 提交句级 AudioState，服务端做 merge（部分更新）。
- 同时追加到 session 的 audio_state_log，供实时状态查看；评估 Agent 当前只读取 ASR 文本。
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request

from backend.api.errors import session_not_found
from backend.audio.decoder import SUPPORTED_MIME_TYPES
from backend.audio.errors import AudioError
from backend.audio.transcriber import get_transcription_service
from backend.audio.upload import UPLOAD_SCHEMA, read_recording
from backend.core.session_manager import session_manager
from backend.models.requests import AudioUpsertRequest
from backend.models.responses import StateUpsertResponse, TranscriptionResponse
from backend.models.states import SessionState

router = APIRouter(prefix="/api", tags=["audio"])


@router.get("/audio/status")
def audio_status() -> dict:
    service = get_transcription_service()
    config = service.config
    return {
        "state": service.state, "provider": config.provider,
        "model": "SenseVoiceSmall" if config.provider == "sensevoice" else None,
        "max_upload_bytes": config.max_upload_bytes,
        "max_duration_seconds": config.max_duration_seconds,
        "timeout_seconds": config.timeout_seconds,
        "max_pending": config.max_pending,
        "supported_mime_types": sorted(SUPPORTED_MIME_TYPES),
    }


@router.post("/audio/transcribe", response_model=TranscriptionResponse,
             openapi_extra=UPLOAD_SCHEMA)
async def transcribe_audio(request: Request) -> TranscriptionResponse:
    service = get_transcription_service()
    try:
        # Cover upload and both session checks, not just the inference queue.
        with service.reserve() as reservation:
            metadata, data, content_type = await read_recording(request, service.config)
            # Chat holds this global lock during policy calls; never wait on it
            # in the event loop, including the check after inference.
            if await asyncio.to_thread(session_manager.get_session, metadata.session_id) is None:
                raise session_not_found()
            text = await reservation.transcribe(
                data, content_type,
                metadata.speech.recording_end_ms - metadata.speech.recording_start_ms)
            # A deleted/expired session must not receive a late result.
            if await asyncio.to_thread(session_manager.get_session, metadata.session_id) is None:
                raise session_not_found()
            return TranscriptionResponse(
                session_id=metadata.session_id, utterance_id=metadata.utterance_id,
                text=text, speech=metadata.speech)
    except AudioError as exc:
        raise HTTPException(status_code=exc.status_code, detail={
            "code": exc.code, "message": exc.message}) from exc


@router.post("/audio", response_model=StateUpsertResponse)
def update_audio(request: AudioUpsertRequest) -> StateUpsertResponse:
    incoming = request.state

    def mutator(session: SessionState) -> None:
        merged = _merge_audio(session.latest_audio_state, incoming)
        session.latest_audio_state = merged
        session.audio_state_log.append(merged)

    updated = session_manager.modify_session(request.session_id, mutator)
    if updated is None:
        raise session_not_found()
    return StateUpsertResponse(
        session_id=request.session_id,
        audio_state=updated.latest_audio_state)


def _merge_audio(existing, incoming):
    if existing is None:
        return incoming
    data = existing.model_dump()
    new_data = incoming.model_dump(exclude_unset=True)
    data.update(new_data)
    return type(incoming).model_validate(data)
