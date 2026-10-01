"""对话 API（C 编排，A 决策）。

路由层只做编排：
1. 原子地完成「加用户消息 → DialogueManager 决策 → 加助手消息」。
2. 决策模型不可用时返回 503 POLICY_UNAVAILABLE，本轮不落库。

对话没有自动结束信号：决策模型的 11 个动作里没有「结束评估」，因此聊天不再
自动触发最终评估。综合评估由 ``POST /api/assessment`` 显式触发，
该接口直接接收上游提供的会话级视觉汇总（见 ``backend/api/assessment.py``）。
"""

from fastapi import APIRouter, HTTPException

from backend.api.errors import session_not_found
from backend.core.dialogue_manager import DialogueManager
from backend.core.session_manager import session_manager
from backend.models.enums import MessageRole
from backend.models.requests import ChatRequest
from backend.models.responses import ChatResponse
from backend.models.states import Message, SessionState
from backend.policy.client import PolicyClientError

router = APIRouter(prefix="/api", tags=["chat"])
dialogue_manager = DialogueManager()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR", "message": "Text cannot be blank."})

    dialogue_payload = {"value": None}

    def mutator(session: SessionState) -> None:
        session.conversation_history.append(Message(
            role=MessageRole.USER, content=text,
            vision_snapshot=request.vision_snapshot,
        ))
        payload = dialogue_manager.process_turn(text, session)
        dialogue_payload["value"] = payload
        session.conversation_history.append(Message(
            role=MessageRole.ASSISTANT, content=payload.reply))
        session.turn_count += 1

    try:
        updated = session_manager.modify_session(request.session_id, mutator)
    except PolicyClientError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "POLICY_UNAVAILABLE",
            "message": "决策模型暂时不可用，请稍后重试。",
        }) from exc
    if updated is None:
        raise session_not_found()

    payload = dialogue_payload["value"]

    return ChatResponse(
        session_id=request.session_id,
        turn_count=updated.turn_count,
        reply=payload.reply,
        next_strategy=payload.next_strategy,
        current_stage=payload.current_stage,
        risk=payload.risk,
    )
