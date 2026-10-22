"""Healing API: independent history, fixed assessment binding and retry receipts.

安全口径（新版 Safety）：
- Healing **不做任何风险判定**，也不再有自己的一套关键词/正则规则；
- 每个进入普通治愈的入口都先判断会话安全状态
  （``safety_blocks_normal_flow``）与本轮 Safety 结论（``SafetyVerdict.halted``），
  为真时只返回安全支持/澄清状态，绝不继续普通治愈；
- 拿不到安全结论时**不当作低风险放行**：是否继续只以上述判断为准。
"""

import asyncio
import hashlib
import json
from time import perf_counter

from fastapi import APIRouter, HTTPException

from backend.api.chat import safety_runner
from backend.core.healing_adapter import HealingBackgroundInvalid, build_healing_memory
from backend.core.memory_store import memory_store
from backend.core.session_manager import session_manager
from backend.core.conversation_archive import conversation_archive
from backend.healing.agent import HealingAgent
from backend.healing.client import HealingUnavailable
from backend.healing.safety_bridge import most_severe_verdict, session_safety_verdict
from backend.healing.store import healing_store
from backend.models.healing import HealingChatRequest, HealingMessage, HealingResponse, StartHealingRequest, student_view
from backend.models.states import SessionState, _now
from backend.safety.schemas import SafetyVerdict
from backend.safety.support import safety_blocks_normal_flow, safety_reply_messages

router = APIRouter(prefix="/api/healing", tags=["healing"])
healing_agent = HealingAgent()


def error(status, code, message):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def live_session(session_id):
    session = session_manager.get_session(session_id)
    if session is None:
        session = session_manager.resume_for_healing(session_id)
    if session is None and not conversation_archive.is_deleted(session_id):
        # Legacy reports predate durable conversations. They can seed a new
        # companionship, but cannot reconstruct messages already lost in memory.
        record = next((r for r in memory_store.list_all_records()
                       if r.result.session_id == session_id), None)
        if record is not None:
            # Recheck the actual saved report with the same Safety agent used
            # for new messages; no fabricated normal verdict on restoration.
            safety = await evaluate_safety(record.result.model_dump_json(), [])
            if safety is None:
                raise error(503, "HEALING_UNAVAILABLE", "暂时无法恢复陪伴，请稍后重试。")
            session = session_manager.resume_for_healing(session_id, SessionState(
                session_id=session_id, student_ref=record.student_ref,
                assessment_result_id=record.result.result_id,
                latest_safety=safety,
                safety_halted=safety.route.value == "safety_stop",
                safety_stage=("stopped" if safety.route.value == "safety_stop"
                              else "review" if safety.halted else "none"),
            ))
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


async def evaluate_safety(text: str, history) -> SafetyVerdict | None:
    """本轮治愈发言的安全结论，来自系统唯一的安全判定调用点。

    ``safety_runner`` 就是 ``/api/chat`` 使用的那个实例（chat.py 声明它是
    安全判定的唯一调用点），因此测试用同一处替换即可注入离线结论，
    Healing 侧不会再出现第二套判定实现。判定本身是同步的，放进线程执行，
    避免在事件循环里触发内部 ``asyncio.run``。空文本不产生结论（返回 None）。
    """
    if not text.strip():
        return None
    return await asyncio.to_thread(safety_runner.evaluate, text, list(history))


def safe_to_continue(session) -> bool:
    """普通治愈是否可以继续：只看会话安全状态（统一守卫，不看报告风险字段）。"""
    return not safety_blocks_normal_flow(safety_halted=session.safety_halted,
                                         safety_stage=session.safety_stage)


def publish_state(session_id, slot, candidate=None, *, answer=None, safety=None,
                  start_receipt=None, message_receipt=None):
    """Under the slot lock, check the current safety conclusion and commit without an await.

    The session read lock also serializes this commit with safety updates from
    worker threads. Ordinary replies produced while a safety stop/review arrived
    are discarded; their feedback and recommendations must not become accepted
    progress.
    """
    def publish(session):
        state = candidate if candidate is not None else slot.state
        if state is None:
            raise error(404, "HEALING_NOT_FOUND", "本次陪伴记录不可恢复，请重新进入陪伴。")
        # 安全暂停/中止必须阻断普通治愈：本轮的 Safety 结论与会话上的
        # 安全状态取更严重的一份，任一要求停止都不得继续普通治愈。
        session_safety = session_safety_verdict(session)
        blocked = not safe_to_continue(session)
        governing = most_severe_verdict(
            safety, session_safety, state.risk if state.status == "referred" else None)
        if blocked or governing.halted:
            if state.status != "referred" or governing != state.risk:
                if candidate is not None and answer is not None and state.status != "referred":
                    # 安全结论在生成期间变化：丢弃这条普通治愈回复，
                    # 只保留这条用户回答，且不写入任何普通治愈进度。
                    state = slot.state.model_copy(deep=True)
                    state.turn_count += 1
                    state.messages.append(HealingMessage(role="user", content=answer))
                else:
                    state = state.model_copy(deep=True)
                healing_agent.enter_safety_mode(
                    state, governing,
                    initial=candidate is not None and answer is None and state.status != "referred",
                    already_halted=blocked or state.status == "referred")
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
        healing_store.persist(session_id, slot)
        return response

    response = session_manager.read_session(session_id, publish)
    if response is None:
        raise error(404, "HEALING_SESSION_EXPIRED", "本次会话已过期，陪伴记录不可恢复。请重新开始并进入陪伴。")
    return response


@router.post("/start", response_model=HealingResponse)
async def start_healing(request: StartHealingRequest):
    await live_session(request.session_id)
    slot = get_slot(request.session_id)
    async with slot.lock:
        session = await live_session(request.session_id)
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
        # 进入普通治愈前的安全判定：学生本轮带来的文本（关注点/最近发言）
        # 由新版 Safety 判定，再与会话已有的安全结论取更严重的一份。
        entry = memory.background.current_concern or "\n".join(memory.current_session_messages[-8:])
        transcript = [(message.role.value, message.content)
                      for message in session.conversation_history[-20:]]
        safety = most_severe_verdict(await evaluate_safety(entry, transcript),
                                     session_safety_verdict(session))
        try:
            new_state = await healing_agent.start(
                memory, safety,
                safety_halted=session.safety_halted, safety_stage=session.safety_stage)
            if new_state.audit:
                new_state.audit[-1]["adapter_ms"] = adapter_ms
        except HealingUnavailable:
            if slot.state is not None:
                publish_state(request.session_id, slot, safety=safety)
            raise error(503, "HEALING_UNAVAILABLE", "支持服务暂时不可用，请稍后重试；已有陪伴记录会保留。") from None
        return publish_state(request.session_id, slot, new_state, safety=safety,
                             start_receipt=(request.request_id, digest))


@router.get("/{session_id}", response_model=HealingResponse)
async def get_healing(session_id: str):
    await live_session(session_id)
    slot = get_slot(session_id)
    async with slot.lock:
        return publish_state(session_id, slot)


@router.post("/chat", response_model=HealingResponse)
async def healing_chat(request: HealingChatRequest):
    await live_session(request.session_id)
    slot = get_slot(request.session_id)
    async with slot.lock:
        session = await live_session(request.session_id)
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
        if state.status == "referred" or not safe_to_continue(session):
            # Stop ordinary coaching, not communication. Safety alone handles
            # each new message; keep the stop/review lock and all methods off.
            history = [(message.role, message.content) for message in state.messages[-20:]]
            turn_safety = await evaluate_safety(request.text, history)
            if turn_safety is None:
                raise error(503, "HEALING_UNAVAILABLE", "陪伴服务暂时不可用，请重试本次回答。")
            governing = most_severe_verdict(turn_safety, state.risk, session_safety_verdict(session))
            candidate = state.model_copy(deep=True)
            candidate.status = "referred"
            candidate.risk = governing
            candidate.turn_count += 1
            candidate.messages.extend([
                HealingMessage(role="user", content=request.text),
                HealingMessage(role="assistant", content="\n".join(
                    safety_reply_messages(turn_safety, already_halted=True))),
            ])
            for suggestion in candidate.suggestions:
                suggestion.active = False
            return publish_state(request.session_id, slot, candidate, safety=governing,
                                 message_receipt=(request.message_id, digest))
        # 本条治愈发言的安全结论（新版 Safety），与会话已有的安全结论取更严重的。
        history = [(message.role, message.content) for message in state.messages[-20:]]
        turn_safety = await evaluate_safety(request.text, history)
        safety = most_severe_verdict(turn_safety, session_safety_verdict(session))
        try:
            new_state = await healing_agent.reply(
                state, request.text, safety,
                safety_halted=session.safety_halted, safety_stage=session.safety_stage)
        except HealingUnavailable:
            publish_state(request.session_id, slot, safety=safety)
            raise error(503, "HEALING_UNAVAILABLE", "陪伴服务暂时不可用，请重试本次回答；此前进度会保留。") from None
        return publish_state(request.session_id, slot, new_state, answer=request.text, safety=safety,
                             message_receipt=(request.message_id, digest))
