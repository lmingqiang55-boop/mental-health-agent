"""视觉状态 API（C 接入，B 输出）。

- 提交句级 VisionState，服务端做 merge（只更新传入的非 None 字段），
  不再全量替换。
- 同时追加到 session 的 vision_state_log，供会话级汇总。
"""

from fastapi import APIRouter

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.requests import VisionUpsertRequest
from backend.models.responses import StateUpsertResponse
from backend.models.states import SessionState

router = APIRouter(prefix="/api", tags=["vision"])


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


def _merge_vision(existing, incoming):
    if existing is None:
        return incoming
    data = existing.model_dump()
    new_data = incoming.model_dump(exclude_unset=True)
    data.update(new_data)
    return type(incoming).model_validate(data)
