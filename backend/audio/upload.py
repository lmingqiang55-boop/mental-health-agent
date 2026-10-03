"""Bound multipart parsing before buffering; uploaded audio stays in memory."""

from fastapi import Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from backend.audio.config import ASRConfig
from backend.audio.errors import AudioError
from backend.models.requests import ChatRequest
from backend.models.states import SpeechMetadata

UPLOAD_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object",
            "required": ["file", "session_id", "utterance_id", "capture_id",
                         "recording_start_ms", "recording_end_ms"],
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "session_id": {"type": "string"},
                "utterance_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "capture_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "recording_start_ms": {"type": "number", "minimum": 0},
                "recording_end_ms": {"type": "number", "exclusiveMinimum": 0},
            },
        }}},
    },
}


async def read_recording(request: Request, config: ASRConfig):
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        raise AudioError("VALIDATION_ERROR", "请使用 multipart/form-data 上传录音。")
    body_limit = config.max_upload_bytes + 64 * 1024
    try:
        if int(request.headers.get("content-length", "0")) > body_limit:
            raise AudioError("AUDIO_TOO_LARGE", "录音超过上传大小限制。", 413)
    except ValueError as exc:
        raise AudioError("VALIDATION_ERROR", "无效的请求长度。") from exc

    async def bounded_stream():
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > body_limit:
                raise AudioError("AUDIO_TOO_LARGE", "录音超过上传大小限制。", 413)
            yield chunk

    parser = MultiPartParser(
        request.headers, bounded_stream(), max_files=1, max_fields=5, max_part_size=1024)
    # Bound the body first and keep all accepted file bytes below the spool threshold.
    parser.spool_max_size = body_limit + 1
    parser.max_file_size = body_limit + 1  # Starlette 0.40–0.45 compatibility.
    form = None
    try:
        form = await parser.parse()
        required = {"file", "session_id", "utterance_id", "capture_id",
                    "recording_start_ms", "recording_end_ms"}
        if set(form) != required or any(len(form.getlist(key)) != 1 for key in form):
            raise AudioError("VALIDATION_ERROR", "录音字段缺失、重复或包含未知字段。")
        upload = form["file"]
        if not isinstance(upload, UploadFile) or any(
                not isinstance(form[key], str) for key in required - {"file"}):
            raise AudioError("VALIDATION_ERROR", "无效的录音文件或元数据。")
        speech = SpeechMetadata(
            capture_id=form["capture_id"], recording_start_ms=form["recording_start_ms"],
            recording_end_ms=form["recording_end_ms"])
        # Share identifier validation with the subsequent chat request.
        metadata = ChatRequest(
            session_id=form["session_id"], utterance_id=form["utterance_id"],
            speech=speech, text="metadata")
        duration_ms = speech.recording_end_ms - speech.recording_start_ms
        if duration_ms > config.max_duration_seconds * 1000:
            raise AudioError("AUDIO_TOO_LONG", "录音区间超过允许时长。")
        if upload.size is not None and upload.size > config.max_upload_bytes:
            raise AudioError("AUDIO_TOO_LARGE", "录音超过上传大小限制。", 413)
        data = await upload.read(config.max_upload_bytes + 1)
        if len(data) > config.max_upload_bytes:
            raise AudioError("AUDIO_TOO_LARGE", "录音超过上传大小限制。", 413)
        if not data:
            raise AudioError("INVALID_AUDIO", "录音文件为空。")
        return metadata, data, upload.content_type or ""
    except AudioError:
        raise
    except (ValidationError, MultiPartException, ValueError, KeyError) as exc:
        raise AudioError("VALIDATION_ERROR", "录音表单或采集时间无效。") from exc
    finally:
        if form is not None:
            await form.close()
        else:
            # Starlette also closes on multipart errors; closing twice is harmless.
            for handle in parser._files_to_close_on_error:
                handle.close()
