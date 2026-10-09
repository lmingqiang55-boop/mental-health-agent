"""对话 API（C 编排，A 决策）。

路由层只做编排：
1. 原子地完成「加用户消息 → DialogueManager 决策 → 加助手消息」。
2. 决策模型或对话 Agent 不可用时返回 503，本轮不落库。

对话没有自动结束信号：决策模型的 11 个动作里没有「结束评估」，因此聊天不再
自动触发最终评估。综合评估由 ``POST /api/assessment`` 显式触发，
该接口直接接收上游提供的会话级视觉汇总（见 ``backend/api/assessment.py``）。
"""

import hashlib
import json

from fastapi import APIRouter, HTTPException

from backend.api.errors import session_not_found
from backend.core.dialogue_manager import DialogueManager, DialogueUnavailable
from backend.core.session_manager import session_manager
from backend.models.enums import MessageRole
from backend.models.requests import ChatRequest
from backend.models.responses import ChatResponse
from backend.models.states import ChatReceipt, Message, SessionState
from backend.policy.client import PolicyClientError

router = APIRouter(prefix="/api", tags=["chat"])
dialogue_manager = DialogueManager()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR", "message": "Text cannot be blank."})

    response_holder = {"value": None}
    fingerprint = _fingerprint(request, text)

    def mutator(session: SessionState) -> None:
        if request.utterance_id is not None:
            receipt = session.chat_receipts.get(request.utterance_id)
            if receipt is not None:
                if receipt.fingerprint != fingerprint:
                    raise HTTPException(status_code=409, detail={
                        "code": "UTTERANCE_CONFLICT",
                        "message": "该发言标识已用于不同内容，请复用原请求或为新发言生成新标识。",
                    })
                response_holder["value"] = ChatResponse.model_validate(receipt.response)
                return
            if any(item.utterance_id == request.utterance_id
                   for item in session.conversation_history):
                raise HTTPException(status_code=409, detail={
                    "code": "UTTERANCE_CONFLICT",
                    "message": "该标识已存在于导入历史中，无法作为新聊天重复提交。",
                })
        segment = session.vision_segments.get(request.utterance_id)
        if segment is not None:
            supplied = request.vision_snapshot.model_dump(exclude={"timestamp"}) if request.vision_snapshot else None
            frozen = segment.vision_snapshot.model_dump(exclude={"timestamp"}) if segment.vision_snapshot else None
            wrong_interval = request.speech is not None and (
                request.speech.capture_id, request.speech.recording_start_ms,
                request.speech.recording_end_ms) != (segment.capture_id, segment.start_ms, segment.end_ms)
            if supplied != frozen or wrong_interval:
                raise HTTPException(status_code=409, detail={
                    "code": "UTTERANCE_CONFLICT", "message": "聊天输入必须复用已冻结的本句视觉结果和时间区间。"})
        session.conversation_history.append(Message(
            role=MessageRole.USER, content=text,
            vision_snapshot=request.vision_snapshot,
            utterance_id=request.utterance_id, speech=request.speech,
        ))
        kwargs = {"vision_snapshot": request.vision_snapshot}
        if request.speech is not None or "vision_snapshot" in request.model_fields_set:
            kwargs["use_latest_states"] = False
        payload = dialogue_manager.process_turn(text, session, **kwargs)
        session.conversation_history.append(Message(
            role=MessageRole.ASSISTANT, content=payload.reply))
        session.turn_count += 1
        response = ChatResponse(
            session_id=request.session_id, turn_count=session.turn_count,
            **payload.model_dump(),
        )
        response_holder["value"] = response
        if request.utterance_id is not None:
            session.chat_receipts[request.utterance_id] = ChatReceipt(
                fingerprint=fingerprint, response=response.model_dump(mode="json"))

    try:
        updated = session_manager.modify_session(request.session_id, mutator)
    except PolicyClientError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "POLICY_UNAVAILABLE",
            "message": "决策模型暂时不可用，请稍后重试。",
        }) from exc
    except DialogueUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "code": "DIALOGUE_UNAVAILABLE",
            "message": "对话生成服务暂时不可用，请稍后重试。",
        }) from exc
    if updated is None:
        raise session_not_found()

    return response_holder["value"]


def _fingerprint(request: ChatRequest, text: str) -> str:
    """Hash effective input; generated vision timestamps do not change retries."""
    value = {
        "text": text,
        "speech": request.speech.model_dump(mode="json") if request.speech else None,
        "vision_snapshot": request.vision_snapshot.model_dump(
            mode="json", exclude={"timestamp"}) if request.vision_snapshot else None,
    }
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
