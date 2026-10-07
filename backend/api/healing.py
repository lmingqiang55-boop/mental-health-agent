"""Healing API: independent history, fixed assessment binding and retry receipts."""

import hashlib
import json
from time import perf_counter

from fastapi import APIRouter, HTTPException

from backend.core.healing_adapter import HealingBackgroundInvalid, build_healing_memory
from backend.core.memory_store import memory_store
from backend.core.session_manager import session_manager
from backend.healing.agent import HealingAgent
from backend.healing.client import HealingUnavailable
from backend.healing.safety import guard_risk, referral_text
from backend.healing.store import healing_store
from backend.llm.prompts import QUESTIONS
from backend.models.enums import MessageRole, RiskLevel
from backend.models.healing import HealingChatRequest, HealingMessage, HealingResponse, StartHealingRequest, student_view
from backend.models.states import _now

router = APIRouter(prefix="/api/healing", tags=["healing"])
healing_agent = HealingAgent()


def error(status, code, message):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def live_session(session_id):
    session = session_manager.get_session(session_id)
    if session is None:
        raise error(404, "HEALING_SESSION_EXPIRED", "本次会话已过期，陪伴记录不可恢复。请重新开始并进入陪伴。")
    return session


def fingerprint(request):
    return hashlib.sha256(json.dumps(request.model_dump(mode="json"), ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")).hexdigest()


def get_slot(session_id):
    try:
        return healing_store.slot(session_id)
    except RuntimeError:
        raise error(503, "HEALING_BUSY", "陪伴服务繁忙，请稍后重试。") from None


def risk_priority(risk):
    return ({RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}[risk.risk_level],
            risk.risk_score)


def publish_state(session_id, slot, candidate=None, *, answer=None,
                  start_receipt=None, message_receipt=None):
    """Under the slot lock, check current screening risk and commit without an await.

    The session read lock also serializes this commit with screening updates from
    worker threads. Ordinary replies produced while risk changed are discarded;
    their feedback and recommendations must not become accepted progress.
    """
    def publish(session):
        state = candidate if candidate is not None else slot.state
        if state is None:
            raise error(404, "HEALING_NOT_FOUND", "本次陪伴记录不可恢复，请重新进入陪伴。")
        # Direct assessment imports may update the transcript without latest_risk.
        # Inspect its current user text without changing the report's binding.
        contexts = list(dict.fromkeys([*state.memory.current_session_messages,
            *(message.content for message in session.conversation_history if message.role == MessageRole.USER)]))
        risk_memory = state.memory.model_copy(update={"current_session_messages": contexts})
        risk = guard_risk(risk_memory, answer or "", session.latest_risk, session.crisis_mode)
        if risk is not None and (state.status != "referred" or (
                risk_priority(risk) >= risk_priority(state.risk) and risk != state.risk)):
            if candidate is not None and answer is not None and state.status != "referred":
                state = slot.state.model_copy(deep=True)
                state.turn_count += 1
                state.messages.append(HealingMessage(role="user", content=answer))
            else:
                state = state.model_copy(deep=True)
            previous_text = (state.messages[-1].content if state.messages and
                             state.messages[-1].role == "assistant" else state.report.understanding)
            if state.status != "referred" or previous_text != referral_text(risk, QUESTIONS["crisis_support"]):
                healing_agent.refer(state, risk, initial=candidate is not None and answer is None)
            else:
                state.risk = risk
                state.audit.append({"phase": "risk_refresh", "at": _now().isoformat(),
                                    "risk": risk.model_dump(mode="json")})
        elif risk is None and risk_priority(session.latest_risk) > risk_priority(state.risk):
            state = state.model_copy(deep=True)
            state.risk = session.latest_risk.model_copy(deep=True)
        response = student_view(state)
        if message_receipt is not None:
            message_id, digest = message_receipt
            state.receipts[message_id] = {"fingerprint": digest}
        if start_receipt is not None:
            request_id, digest = start_receipt
            slot.start_receipts[request_id] = {"fingerprint": digest, "healing_id": state.healing_id}
            if len(slot.start_receipts) > 32:
                slot.start_receipts.pop(next(iter(slot.start_receipts)))
        if state is not slot.state:
            slot.state = state
            slot.touched_at = _now()
        return response

    response = session_manager.read_session(session_id, publish)
    if response is None:
        raise error(404, "HEALING_SESSION_EXPIRED", "本次会话已过期，陪伴记录不可恢复。请重新开始并进入陪伴。")
    return response


@router.post("/start", response_model=HealingResponse)
async def start_healing(request: StartHealingRequest):
    live_session(request.session_id)
    slot = get_slot(request.session_id)
    async with slot.lock:
        session = live_session(request.session_id)
        digest = fingerprint(request)
        receipt = slot.start_receipts.get(request.request_id)
        if receipt is not None:
            if receipt["fingerprint"] != digest:
                raise error(409, "HEALING_REQUEST_CONFLICT", "请求标识已用于其他内容，请为新操作生成新标识。")
            if slot.state is None or slot.state.healing_id != receipt["healing_id"]:
                raise error(409, "HEALING_STATE_CHANGED", "陪伴已更新，请返回当前陪伴记录。")
            return publish_state(request.session_id, slot)
        if slot.state is not None and not request.regenerate:
            return publish_state(request.session_id, slot,
                                 start_receipt=(request.request_id, digest))
        if request.regenerate and slot.state is not None and request.expected_healing_id != slot.state.healing_id:
            raise error(409, "HEALING_STATE_CHANGED", "当前陪伴已更新，请确认当前记录后重新生成。")
        if slot.state is not None:
            publish_state(request.session_id, slot)
        try:
            adapted_at = perf_counter()
            memory = build_healing_memory(session, memory_store, request.background)
            adapter_ms = (perf_counter()-adapted_at)*1000
        except HealingBackgroundInvalid as exc:
            raise error(422, "VALIDATION_ERROR", str(exc)) from None
        except ValueError:
            raise error(409, "HEALING_ASSESSMENT_REQUIRED", "请先完成一次筛查，再进入心理支持陪伴。") from None
        try:
            new_state = await healing_agent.start(memory, session.latest_risk, session.crisis_mode)
            if new_state.audit:
                new_state.audit[-1]["adapter_ms"] = adapter_ms
        except HealingUnavailable:
            if slot.state is not None:
                publish_state(request.session_id, slot)
            raise error(503, "HEALING_UNAVAILABLE", "支持服务暂时不可用，请稍后重试；已有陪伴记录会保留。") from None
        return publish_state(request.session_id, slot, new_state,
                             start_receipt=(request.request_id, digest))


@router.get("/{session_id}", response_model=HealingResponse)
async def get_healing(session_id: str):
    live_session(session_id)
    slot = get_slot(session_id)
    async with slot.lock:
        return publish_state(session_id, slot)


@router.post("/chat", response_model=HealingResponse)
async def healing_chat(request: HealingChatRequest):
    live_session(request.session_id)
    slot = get_slot(request.session_id)
    async with slot.lock:
        session = live_session(request.session_id)
        state = slot.state
        if state is None:
            raise error(404, "HEALING_NOT_FOUND", "本次陪伴记录不可恢复，请重新进入陪伴。")
        if state.healing_id != request.healing_id:
            raise error(409, "HEALING_STATE_CHANGED", "陪伴已重新生成，请在当前陪伴中继续。")
        digest = fingerprint(request)
        receipt = state.receipts.get(request.message_id)
        if receipt is not None:
            if receipt["fingerprint"] != digest:
                raise error(409, "HEALING_REQUEST_CONFLICT", "该回答标识已用于不同内容。")
            return publish_state(request.session_id, slot)
        publish_state(request.session_id, slot)
        state = slot.state
        if state.status == "ended":
            raise error(409, "HEALING_ENDED", "这轮陪伴已经结束，可以重新生成一轮支持。")
        if state.turn_count >= 80:
            raise error(409, "HEALING_TURN_LIMIT", "这轮陪伴已达到保存上限，请重新生成一轮支持。")
        try:
            new_state = await healing_agent.reply(state, request.text, session.latest_risk, session.crisis_mode)
        except HealingUnavailable:
            publish_state(request.session_id, slot)
            raise error(503, "HEALING_UNAVAILABLE", "陪伴服务暂时不可用，请重试本次回答；此前进度会保留。") from None
        return publish_state(request.session_id, slot, new_state, answer=request.text,
                             message_receipt=(request.message_id, digest))
