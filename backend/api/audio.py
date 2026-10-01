"""音频状态 API（C 接入，B 输出）。

- 提交句级 AudioState，服务端做 merge（部分更新）。
- 同时追加到 session 的 audio_state_log，供实时状态查看；评估 Agent 当前只读取 ASR 文本。
"""

from fastapi import APIRouter

from backend.api.errors import session_not_found
from backend.core.session_manager import session_manager
from backend.models.requests import AudioUpsertRequest
from backend.models.responses import StateUpsertResponse
from backend.models.states import SessionState

router = APIRouter(prefix="/api", tags=["audio"])


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
