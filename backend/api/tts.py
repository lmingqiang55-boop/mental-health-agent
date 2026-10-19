"""Read a saved assistant reply and return its synthesized audio."""

import asyncio
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.api.errors import session_not_found
from backend.audio.tts import (
    PROBE_TEXT,
    TTSError,
    configured_provider_name,
    get_tts_service,
    provider_unavailable_reason,
)
from backend.core.session_manager import session_manager
from backend.api.consent_guard import require_scopes
from backend.models.enums import MessageRole
from backend.models.states import SessionState


router = APIRouter(prefix="/api/tts", tags=["tts"])


class SynthesizeRequest(BaseModel):
    session_id: str
    turn_count: int = Field(ge=0)


#: 最近一次合成失败（按 provider 记录）。``config.ready`` 只能证明配置与依赖
#: 齐了，证明不了上游此刻可达——edge-tts 的 7.2.8 及更早版本就是这样：依赖装
#: 得好好的，真合成却稳定 403。把真实失败留在状态接口上，前端才不会一直显示
#: "语音可用"。
_LAST_FAILURE: dict[str, str] = {}

#: 真探测的缓存与超时。合成两个字成本可忽略，但前端可能连点，缓存 60 秒够用；
#: 超时比 provider 自己的 ``timeout_seconds``（默认 30 秒）短一些，避免把请求
#: 挂死——探测的结论只有"通"和"不通"两种，不差这点耐心。
PROBE_CACHE_SECONDS = 60.0
PROBE_TIMEOUT_SECONDS = 15.0
_PROBE_CACHE: dict[str, tuple[float, dict]] = {}


def _probe_snapshot(provider: str) -> dict | None:
    cached = _PROBE_CACHE.get(provider)
    if cached is None:
        return None
    return {**cached[1], "cached": True} if time.time() - cached[0] < PROBE_CACHE_SECONDS else None


@router.get("/status")
def tts_status() -> dict:
    service = get_tts_service()
    provider = service.config.provider_name
    ready = bool(service.config.ready)
    last_error = _LAST_FAILURE.get(provider)
    state = "unconfigured" if not ready else ("degraded" if last_error else "ready")
    # 配置的 provider 不可用时 get_tts_service 会静默退到另一个；只报生效的那个
    # 会让"Key 配错"看起来和"一切正常"一模一样，所以把回退本身也报出来。
    configured = configured_provider_name()
    return {"state": state,
            "provider": provider,
            "configured_provider": configured,
            "fallback_reason": (
                None if configured == provider
                else provider_unavailable_reason(configured)),
            "model": service.config.model if ready else None,
            "voice": service.config.voice if ready else None,
            "reason": None if ready else service.config.unavailable_reason,
            "last_error": last_error,
            # 只有真合成过才会有值；没探测过就是 None，别把 None 当成"通"。
            "last_probe": _probe_snapshot(provider)}


@router.post("/probe")
async def probe_speech() -> dict:
    """真合成一小段，回答"现在到底能不能出声"。

    为什么单独做一个接口：``/api/tts/status`` 看到的是配置；``/voices/list`` 之类
    的轻量探测**不算数**（实测它一直返回 200，而合成一直返回 403）。唯一可信的
    证据是真合成一次。这里合成两个字，成本可忽略，结果缓存 ``PROBE_CACHE_SECONDS``。

    前端可以在用户点"测试语音"时调用，或让老师端在开课前自检。
    """
    service = get_tts_service()
    provider = service.config.provider_name
    cached = _PROBE_CACHE.get(provider)
    if cached is not None and time.time() - cached[0] < PROBE_CACHE_SECONDS:
        return {**cached[1], "cached": True}
    base = {"provider": provider,
            "voice": service.config.voice,
            "model": service.config.model,
            "checked_at": time.time()}
    if not service.config.ready:
        result = {**base, "ok": False, "latency_ms": None, "audio_bytes": 0,
                  "error": service.config.unavailable_reason or "语音服务尚未配置。",
                  "cached": False}
        _PROBE_CACHE[provider] = (time.time(), result)
        return result
    started = time.perf_counter()
    try:
        audio = await asyncio.wait_for(service.synthesize(PROBE_TEXT),
                                       timeout=PROBE_TIMEOUT_SECONDS)
    except (TTSError, asyncio.TimeoutError) as exc:
        reason = "语音服务响应超时。" if isinstance(exc, asyncio.TimeoutError) else str(exc)
        _LAST_FAILURE[provider] = reason
        result = {**base, "ok": False,
                  "latency_ms": int((time.perf_counter() - started) * 1000),
                  "audio_bytes": 0, "error": reason, "cached": False}
        _PROBE_CACHE[provider] = (time.time(), result)
        return result
    _LAST_FAILURE.pop(provider, None)
    result = {**base, "ok": True,
              "latency_ms": int((time.perf_counter() - started) * 1000),
              "audio_bytes": len(audio), "error": None, "cached": False}
    _PROBE_CACHE[provider] = (time.time(), result)
    return result


@router.post("", response_class=Response)
async def synthesize_reply(request: SynthesizeRequest) -> Response:
    session = await asyncio.to_thread(session_manager.get_session, request.session_id)
    if session is None:
        raise session_not_found()
    require_scopes(session, "text_processing")
    if request.turn_count == 0:
        opening = session.conversation_history[0] if session.conversation_history else None
        if opening is None or opening.role != MessageRole.ASSISTANT:
            raise HTTPException(status_code=404, detail={
                "code": "REPLY_NOT_FOUND", "message": "这轮回复不存在。"})
        text = opening.content
    else:
        # 一轮可能有 1~3 条气泡，**整轮一起合成**：既不漏读，也不会因为
        # reply 兼容字段而把同一句话读两遍（reply 从不单独合成）。
        text = _text_for_turn(session, request.turn_count)
    if not text.strip() or len(text) > 2000:
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_TTS_TEXT", "message": "这轮回复无法合成语音。"})
    service = get_tts_service()
    try:
        audio = await service.synthesize(text)
    except TTSError as exc:
        _LAST_FAILURE[service.config.provider_name] = str(exc)
        raise HTTPException(status_code=503, detail={
            "code": "TTS_UNAVAILABLE", "message": str(exc)}) from exc
    _LAST_FAILURE.pop(service.config.provider_name, None)
    return Response(content=audio, media_type="audio/mpeg",
                    headers={"Cache-Control": "no-store"})


def _turn_bubbles(session: SessionState, turn_count: int) -> list[str]:
    """取第 ``turn_count`` 轮助手回复的全部气泡（保持顺序）。

    一轮用户输入只对应**一条** assistant 消息（见 ``backend/api/chat.py``），
    所以这里按"第几条 assistant 回复"定位，而不是按消息条数——气泡再多，
    也只算一条回复、一个轮次。

    旧历史里 ``messages`` 为空（本次改动之前的记录）时退回 ``content``。
    """
    bubbles: list[list[str]] = []
    user_turns = 0
    for message in session.conversation_history:
        if message.role == MessageRole.USER:
            user_turns += 1
        elif message.role == MessageRole.ASSISTANT and user_turns > len(bubbles):
            # The fixed opening question precedes the first user turn.
            stored = [item.strip() for item in message.messages if item and item.strip()]
            bubbles.append(stored or [message.content])
    if turn_count > session.turn_count or turn_count > len(bubbles):
        raise HTTPException(status_code=404, detail={
            "code": "REPLY_NOT_FOUND", "message": "这轮回复不存在。"})
    return bubbles[turn_count - 1]


def _text_for_turn(session: SessionState, turn_count: int) -> str:
    """整轮合成用的文本：把所有气泡用换行连起来，一条都不落。"""
    return "\n".join(_turn_bubbles(session, turn_count))
