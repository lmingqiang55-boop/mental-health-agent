"""视觉状态 API（C 接入，B 输出）。

- 提交句级 VisionState，服务端做 merge（只更新显式传入字段，包括 null），
  不再全量替换。
- 实时日志用于展示；带采集时间的帧按发言区间冻结，评估从绑定的逐句快照汇总。
"""

import base64
import binascii
import io
import hashlib

from fastapi import APIRouter, HTTPException
from PIL import Image

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.requests import (
    VisionCaptureRequest, VisionFrameRequest, VisionSegmentRequest, VisionUpsertRequest,
)
from backend.models.responses import StateUpsertResponse, VisionFrameResponse, VisionSegmentResponse
from backend.models.states import SessionState, VisionFrameObservation, VisionSegment
from backend.vision.aggregation import aggregate_frames
from backend.vision.detector import get_detector

router = APIRouter(prefix="/api", tags=["vision"])
MAX_FRAME_PIXELS = 1920 * 1080
MAX_FRAME_OBSERVATIONS = 512


@router.post("/vision", response_model=StateUpsertResponse)
def update_vision(request: VisionUpsertRequest) -> StateUpsertResponse:
    incoming = request.state

    def mutator(session: SessionState) -> None:
        merged = _merge_vision(session.latest_vision_state, incoming)
        session.latest_vision_state = merged
        session.vision_state_log.append(merged)
        session.vision_state_log = session.vision_state_log[-MAX_FRAME_OBSERVATIONS:]

    updated = session_manager.modify_session(request.session_id, mutator)
    if updated is None:
        raise session_not_found()
    return StateUpsertResponse(
        session_id=request.session_id,
        vision_state=updated.latest_vision_state)


@router.post("/vision/capture")
def update_capture(request: VisionCaptureRequest) -> dict:
    def mutator(session: SessionState) -> None:
        if request.generation < session.vision_capture_generation:
            return
        if request.generation == session.vision_capture_generation:
            expected = request.capture_id if request.active else None
            if expected != session.active_vision_capture_id:
                raise HTTPException(status_code=409, detail={
                    "code": "VISION_CAPTURE_CONFLICT", "message": "采集代次已用于其他状态。"})
            return
        session.vision_capture_generation = request.generation
        session.active_vision_capture_id = request.capture_id if request.active else None
        session.latest_vision_state = None

    updated = session_manager.modify_session(request.session_id, mutator)
    if updated is None:
        raise session_not_found()
    return {"session_id": request.session_id,
            "capture_id": updated.active_vision_capture_id,
            "generation": updated.vision_capture_generation}


def _ensure_active(session: SessionState, request: VisionFrameRequest) -> None:
    if (request.capture_id is not None and
            request.capture_id != session.active_vision_capture_id) or (
            session.vision_capture_generation >= 0 and session.active_vision_capture_id is None):
        raise HTTPException(status_code=409, detail={
            "code": "VISION_CAPTURE_INACTIVE", "message": "该摄像头采集已停止或已被替换。"})


def _existing_frame(session, request, digest):
    if request.frame_id is None:
        return None
    existing = next((item for item in session.vision_frames
                     if item.frame_id == request.frame_id), None)
    if existing is not None and (
            existing.capture_id != request.capture_id or
            existing.captured_at_ms != request.captured_at_ms or existing.image_digest != digest):
        raise HTTPException(status_code=409, detail={
            "code": "VISION_FRAME_CONFLICT", "message": "同一帧标识不能用于不同图像或时间。"})
    return existing


@router.post("/vision/frame", response_model=VisionFrameResponse)
def analyze_vision_frame(request: VisionFrameRequest) -> VisionFrameResponse:
    """分析单张 JPEG/PNG 帧并写入会话视觉日志。原始图像不落盘。"""
    session = session_manager.get_session(request.session_id)
    if session is None:
        raise session_not_found()
    _ensure_active(session, request)
    try:
        frame = base64.b64decode(_strip_data_url(request.image_base64), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_FRAME", "message": "image_base64 不是有效的图片数据。"
        }) from exc
    try:
        with Image.open(io.BytesIO(frame)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("Unsupported image format")
            if image.width * image.height > MAX_FRAME_PIXELS:
                raise HTTPException(status_code=422, detail={
                    "code": "INVALID_FRAME",
                    "message": "图片分辨率超过允许的最大值。",
                })
            image.verify()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_FRAME", "message": "帧不是有效的 JPEG 或 PNG 图片。"
        }) from exc

    digest = hashlib.sha256(frame).hexdigest()
    existing = _existing_frame(session, request, digest)
    try:
        state = existing.state if existing else get_detector().analyze_frame(frame)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={
            "code": "VISION_UNAVAILABLE", "message": str(exc)
        }) from exc

    def mutator(session: SessionState) -> None:
        _ensure_active(session, request)
        duplicate = _existing_frame(session, request, digest)
        if duplicate is not None:
            result["state"] = duplicate.state
            return
        # A frame is a complete detector snapshot; only /api/vision uses merge semantics.
        result["state"] = state
        # Out-of-order results stay in the interval buffer, but cannot replace a newer frame.
        latest = next((item for item in reversed(session.vision_frames)
                       if item.capture_id == request.capture_id), None)
        if request.captured_at_ms is None or latest is None or request.captured_at_ms >= latest.captured_at_ms:
            session.latest_vision_state = state
        session.vision_state_log.append(state)
        session.vision_state_log = session.vision_state_log[-MAX_FRAME_OBSERVATIONS:]
        if request.frame_id is not None:
            session.vision_frames.append(VisionFrameObservation(
                frame_id=request.frame_id, capture_id=request.capture_id,
                captured_at_ms=request.captured_at_ms, image_digest=digest, state=state))
            session.vision_frames.sort(key=lambda item: item.captured_at_ms)
            session.vision_frames = session.vision_frames[-MAX_FRAME_OBSERVATIONS:]

    result = {"state": state}
    updated = session_manager.modify_session(request.session_id, mutator)
    if updated is None:
        raise session_not_found()
    return VisionFrameResponse(
        session_id=request.session_id,
        vision_state=result["state"], frame_id=request.frame_id,
        capture_id=request.capture_id, captured_at_ms=request.captured_at_ms)


@router.post("/vision/segment", response_model=VisionSegmentResponse)
def freeze_segment(request: VisionSegmentRequest) -> VisionSegmentResponse:
    result = {}

    def mutator(session: SessionState) -> None:
        existing = session.vision_segments.get(request.utterance_id)
        if existing is not None:
            if (existing.capture_id, existing.start_ms, existing.end_ms) != (
                    request.capture_id, request.start_ms, request.end_ms):
                raise HTTPException(status_code=409, detail={
                    "code": "UTTERANCE_CONFLICT", "message": "发言标识已绑定其他视觉区间。"})
            result["value"] = existing
            return
        if any(message.utterance_id == request.utterance_id for message in session.conversation_history):
            raise HTTPException(status_code=409, detail={
                "code": "UTTERANCE_CONFLICT", "message": "发言已提交，不能重新生成视觉快照。"})
        frames = [item.state for item in session.vision_frames
                  if item.capture_id == request.capture_id
                  and request.start_ms <= item.captured_at_ms < request.end_ms]
        segment = VisionSegment(
            capture_id=request.capture_id, start_ms=request.start_ms, end_ms=request.end_ms,
            vision_snapshot=aggregate_frames(frames), frame_count=len(frames),
            valid_frame_count=sum(state.face_detected for state in frames))
        session.vision_segments[request.utterance_id] = segment
        result["value"] = segment

    updated = session_manager.modify_session(request.session_id, mutator)
    if updated is None:
        raise session_not_found()
    return VisionSegmentResponse(session_id=request.session_id, utterance_id=request.utterance_id,
                                 **result["value"].model_dump())


def _strip_data_url(value: str) -> str:
    """允许 canvas.toDataURL 返回的 data:image/...;base64,... 格式。"""
    return value.split(",", 1)[1] if value.startswith("data:") and "," in value else value


def _merge_vision(existing, incoming):
    if existing is None:
        return incoming
    data = existing.model_dump()
    new_data = incoming.model_dump(exclude_unset=True)
    new_data.setdefault("timestamp", incoming.timestamp)
    data.update(new_data)
    return type(incoming).model_validate(data)
