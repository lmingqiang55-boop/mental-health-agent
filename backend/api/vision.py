"""视觉状态 API（C 接入，B 输出）。

- 提交句级 VisionState，服务端做 merge（只更新传入的非 None 字段），
  不再全量替换。
- 同时追加到 session 的 vision_state_log，供实时状态查看；评估用逐句快照和汇总由上游提供。
"""

import base64
import binascii
import io

from fastapi import APIRouter, HTTPException
from PIL import Image

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.requests import VisionFrameRequest, VisionUpsertRequest
from backend.models.responses import StateUpsertResponse
from backend.models.states import SessionState
from backend.vision.detector import get_detector

router = APIRouter(prefix="/api", tags=["vision"])
MAX_FRAME_PIXELS = 1920 * 1080


@router.post("/vision", response_model=StateUpsertResponse)
def update_vision(request: VisionUpsertRequest) -> StateUpsertResponse:
    incoming = request.state

    def mutator(session: SessionState) -> None:
        merged = _merge_vision(session.latest_vision_state, incoming)
        session.latest_vision_state = merged
        session.vision_state_log.append(merged)

    updated = session_manager.modify_session(request.session_id, mutator)
    if updated is None:
        raise session_not_found()
    return StateUpsertResponse(
        session_id=request.session_id,
        vision_state=updated.latest_vision_state)


@router.post("/vision/frame", response_model=StateUpsertResponse)
def analyze_vision_frame(request: VisionFrameRequest) -> StateUpsertResponse:
    """分析单张 JPEG/PNG 帧并写入会话视觉日志。原始图像不落盘。"""
    try:
        frame = base64.b64decode(_strip_data_url(request.image_base64), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_FRAME", "message": "image_base64 不是有效的图片数据。"
        }) from exc
    try:
        with Image.open(io.BytesIO(frame)) as image:
            image.verify()
            if image.width * image.height > MAX_FRAME_PIXELS:
                raise HTTPException(status_code=422, detail={
                    "code": "INVALID_FRAME",
                    "message": "图片分辨率超过允许的最大值。",
                })
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_FRAME", "message": "帧不是有效的 JPEG 或 PNG 图片。"
        }) from exc

    try:
        state = get_detector().analyze_frame(frame)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={
            "code": "VISION_UNAVAILABLE", "message": str(exc)
        }) from exc

    def mutator(session: SessionState) -> None:
        # A frame is a complete detector snapshot; only /api/vision uses merge semantics.
        session.latest_vision_state = state
        session.vision_state_log.append(state)

    updated = session_manager.modify_session(request.session_id, mutator)
    if updated is None:
        raise session_not_found()
    return StateUpsertResponse(
        session_id=request.session_id,
        vision_state=updated.latest_vision_state)


def _strip_data_url(value: str) -> str:
    """允许 canvas.toDataURL 返回的 data:image/...;base64,... 格式。"""
    return value.split(",", 1)[1] if value.startswith("data:") and "," in value else value


def _merge_vision(existing, incoming):
    if existing is None:
        return incoming
    data = existing.model_dump()
    new_data = incoming.model_dump(exclude_unset=True)
    data.update(new_data)
    return type(incoming).model_validate(data)
