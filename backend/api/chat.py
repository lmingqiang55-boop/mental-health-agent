"""对话 API（C 编排，A 决策）。

路由层只做编排：
1. 原子地完成「加用户消息 → DialogueManager 决策 → 加助手消息」。
2. 对话结束（finish_assessment）时聚合会话级多模态汇总，并在锁外触发
   多模态综合评估 Agent、写入评估记忆库。
"""

from fastapi import APIRouter

from backend.api.errors import session_not_found
from backend.core.assessment_engine import assessment_engine
from backend.core.dialogue_manager import DialogueManager
from backend.core.memory_store import memory_store
from backend.core.multimodal_fusion import (
    build_audio_summary,
    build_vision_summary,
)
from backend.core.session_manager import session_manager
from backend.models.enums import MessageRole
from backend.models.requests import ChatRequest
from backend.models.responses import ChatResponse
from backend.models.states import Message, SessionState

router = APIRouter(prefix="/api", tags=["chat"])
dialogue_manager = DialogueManager()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    text = request.text.strip()
    if not text:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail={
            "code": "VALIDATION_ERROR", "message": "Text cannot be blank."})

    dialogue_payload = {"value": None}

    def mutator(session: SessionState) -> None:
        session.conversation_history.append(Message(
            role=MessageRole.USER, content=text,
            vision_snapshot=session.latest_vision_state,
            audio_snapshot=session.latest_audio_state,
        ))
        payload = dialogue_manager.process_turn(text, session)
        dialogue_payload["value"] = payload
        session.conversation_history.append(Message(
            role=MessageRole.ASSISTANT, content=payload.reply))
        session.turn_count += 1

        if payload.next_strategy == "finish_assessment":
            session.vision_summary = build_vision_summary(
                session.vision_state_log)
            session.audio_summary = build_audio_summary(
                session.audio_state_log)

    updated = session_manager.modify_session(request.session_id, mutator)
    if updated is None:
        raise session_not_found()

    payload = dialogue_payload["value"]

    # 对话闭环结束 → 触发多模态综合评估（在 session 锁外执行）
    if payload.next_strategy == "finish_assessment":
        result = assessment_engine.assess(updated)
        memory_store.save_result(result)

        def link_result(session: SessionState) -> None:
            session.assessment_result_id = result.result_id

        session_manager.modify_session(request.session_id, link_result)

    return ChatResponse(
        session_id=request.session_id,
        turn_count=updated.turn_count,
        reply=payload.reply,
        next_strategy=payload.next_strategy,
        current_stage=payload.current_stage,
        risk=payload.risk,
    )
