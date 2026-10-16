"""对话 API（C 编排，A 决策）。

路由层只做编排。

【执行顺序】每个用户消息：
1. 幂等与冻结校验（沿用原有逻辑，未改动）；
2. 落一条 USER 消息；
3. **新版 Safety 判定（系统唯一安全来源，每轮恰好一次）**；
4. 安全分支（UNCERTAIN / HIGH / IMMINENT，或会话已处于支持模式）：
   不进入普通对话，不调用 Decision / Dialogue / 视觉通道，直接给出澄清或支持消息；
5. 普通分支：按 ``DIALOGUE_ENGINE`` 交给 legacy 顺序执行或 LangGraph 图调度
   （两条路径共用同一份业务函数，行为等价）；
6. 落一条 ASSISTANT 消息、``turn_count`` +1、写幂等回执（**各仅一次**）。

决策模型或对话 Agent 不可用时返回 503，本轮不落库。
安全判定失败时**不放行**，按 Safety 的 fail-to-REVIEW 口径进入安全澄清。
同一会话不得中途切换 ``DIALOGUE_ENGINE``，否则返回 409。

会话控制器根据话题交流和轮数上限发送收尾信号。收尾不自动生成报告，
前端显示按钮，用户点击后通过 ``POST /api/assessment`` 生成结果。
"""

import hashlib
import json

from fastapi import APIRouter, HTTPException

from backend.api.errors import session_not_found
from backend.core.agent_trace import build_agent_trace, trace_enabled
from backend.core.dialogue_manager import DialogueManager, DialogueUnavailable, ScreeningFinished
from backend.core.session_manager import session_manager
from backend.graph.engine import (
    DEFAULT_ENGINE,
    DialogueEngineConfigError,
    DialogueTurnRunner,
    EngineSessionMismatch,
    dialogue_engine,
)
from backend.models.enums import MessageRole, SessionStage
from backend.models.requests import ChatRequest
from backend.models.responses import (
    ChatResponse, DialogueResponsePayload, VisualFeedback,
)
from backend.models.states import ChatReceipt, Message, SessionState
from backend.policy.client import PolicyClientError
from backend.safety import agent as safety_agent_module
from backend.safety.schemas import SafetyRoute
from backend.safety.support import (
    safety_next_strategy,
    safety_reply_messages,
    safety_session_stage,
    safety_stage_value,
)

router = APIRouter(prefix="/api", tags=["chat"])
dialogue_manager = DialogueManager()
#: 与 legacy 路径共用同一个 DialogueManager；引擎由 DIALOGUE_ENGINE 决定。
dialogue_runner = DialogueTurnRunner(dialogue_manager)


class _SafetyRunner:
    """安全判定的唯一调用点。

    测试通过替换本实例的 ``evaluate`` 注入离线结论，
    与 ``dialogue_manager._dialogue_agent`` 的注入方式保持一致。
    """

    def evaluate(self, text: str, history: list[tuple[str, str]]):
        return safety_agent_module.evaluate_safety(text, history)


safety_runner = _SafetyRunner()


def _trace_engine() -> str:
    """演示面板上标注的对话引擎名。

    环境变量写错时按默认引擎标注即可——**不能**让一块展示面板把整轮请求拖垮，
    所以这里不像对话链路那样直接抛出 ``DialogueEngineConfigError``。
    """
    try:
        return dialogue_engine()
    except DialogueEngineConfigError:
        return DEFAULT_ENGINE


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

        # ── 第一道闸门：新版 Safety（每轮恰好一次）─────────────────────
        history = [(message.role.value, message.content)
                   for message in session.conversation_history[:-1]]
        safety = safety_runner.evaluate(text, history)
        session.conversation_history[-1].safety = safety
        session.latest_safety = safety

        # 安全状态推进**每轮无条件执行**，包括「恢复正常」的那一轮；
        # 只在安全分支内更新会让 safety_stage 永远停在 review，
        # 从而让 Healing 等入口的守卫永久误判为安全暂停中。
        already_halted = session.safety_halted
        session.safety_stage = safety_stage_value(safety, session.safety_stage)
        if safety.route is SafetyRoute.SAFETY_STOP:
            session.safety_halted = True

        # 已在支持模式时，后续任何一条正常表达都不得自动恢复普通评估。
        in_safety_branch = session.safety_halted or safety.route is not SafetyRoute.CONTINUE

        # 普通分支才有对话载荷；安全分支下保持 None，演示轨迹据此如实标出
        # "Dialogue / Decision / 视觉通道本轮都没有执行"。
        payload: DialogueResponsePayload | None = None

        if in_safety_branch:
            stage = safety_session_stage(session.safety_stage)
            if stage is not None:
                session.current_stage = stage
            messages = safety_reply_messages(safety, already_halted=already_halted)
            reply = messages[0]
            next_strategy = safety_next_strategy(safety, already_halted=already_halted)
            assessment_ready = False
            completion_reason = None
            visual_feedback = VisualFeedback(
                reason="safety_stop" if session.safety_stage == "stopped" else "safety_review")
        else:
            # 澄清结束且未落入停止锁：结束安全模式，回到普通评估。
            # 不还原会话阶段会让学生永久卡在安全澄清页。
            if session.current_stage is SessionStage.SAFETY_REVIEW:
                session.current_stage = SessionStage.EXPLORATION
            kwargs = {"vision_snapshot": request.vision_snapshot,
                      "utterance_id": request.utterance_id}
            if request.speech is not None or "vision_snapshot" in request.model_fields_set:
                kwargs["use_latest_states"] = False
            payload = dialogue_runner.process_turn(text, session, **kwargs)
            # 本轮的气泡（1~3 条）由 Dialogue 决定；reply 是它的全文投影。
            messages = payload.messages or [payload.reply]
            reply = payload.reply
            next_strategy = payload.next_strategy
            assessment_ready = payload.assessment_ready
            completion_reason = payload.completion_reason
            visual_feedback = payload.visual_feedback

        # ── 落库与计数：各只做一次 ────────────────────────────────────
        # 一轮用户输入只追加**一条** assistant 消息，多条气泡存在它的 messages 里：
        # 这样历史不会因为气泡数而多长出几条记录，turn_count 也不会重复自增。
        session.conversation_history.append(Message(
            role=MessageRole.ASSISTANT, content=reply, messages=messages))
        session.turn_count += 1
        # Agent 运行轨迹：**默认关闭**（AGENT_TRACE 未开启时为 None）。
        # 只是把本轮已经算好的结论搬运出来，不额外调用任何模型、不改任何判定。
        trace = (
            build_agent_trace(safety=safety, payload=payload, messages=messages,
                              engine=_trace_engine())
            if trace_enabled() else None
        )
        response = ChatResponse(
            session_id=request.session_id,
            turn_count=session.turn_count,
            reply=reply,
            next_strategy=next_strategy,
            current_stage=session.current_stage.value,
            assessment_ready=assessment_ready,
            completion_reason=completion_reason,
            screening_progress=session.screening_progress,
            visual_feedback=visual_feedback,
            safety=safety,
            messages=messages,
            trace=trace,
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
    except ScreeningFinished as exc:
        raise HTTPException(status_code=409, detail={
            "code": "SCREENING_FINISHED", "message": str(exc),
        }) from exc
    except EngineSessionMismatch as exc:
        raise HTTPException(status_code=409, detail={
            "code": "DIALOGUE_ENGINE_MISMATCH", "message": str(exc),
        }) from exc
    except DialogueEngineConfigError as exc:
        raise HTTPException(status_code=503, detail={
            "code": "DIALOGUE_ENGINE_INVALID",
            "message": f"对话引擎配置无效：{exc}",
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
