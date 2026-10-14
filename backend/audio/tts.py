"""Speech synthesis for one completed assistant turn.

Two providers are available, selected by the ``TTS_PROVIDER`` env var:

- ``cosyvoice`` (default): 阿里云百炼 CosyVoice（需 ``DASHSCOPE_API_KEY`` + ``DASHSCOPE_WORKSPACE_ID``）。
- ``edge``: Microsoft Edge 神经语音（免费、无需 Key，需联网，依赖 ``edge-tts`` 包）。

默认值从 ``edge`` 改成 ``cosyvoice``：cosyvoice 是团队已在用的中文音色；
而 edge-tts 的 **7.2.8 及更早版本**合成握手会稳定返回 403（升级到 7.3.1 后
本机实测恢复）。

``ready`` 只表示"这个 provider 的配置/依赖齐了"，不代表上游此刻可达——
真实可达性只有真合成一次才知道。因此 ``/api/tts/status`` 会带上最近一次
合成的失败原因，``POST /api/tts/probe`` 可以按需真合成一小段做一次性探测：
**"列声音列表"这类探测不算数**（实测它一直 200，而合成 403）。
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
MAX_AUDIO_BYTES = 4 * 1024 * 1024

#: 真探测用的最短文本：够便宜，又足以走完「建连 → 认证 → 出音频」全流程。
PROBE_TEXT = "你好"


def edge_tts_installed() -> bool:
    """edge-tts 包是否装得上。

    这是**依赖检查**，不是可达性检查：edge-tts 不需要 Key，能不能真的合成
    只有联网才知道，所以 ``EdgeTTSConfig.ready`` 为真不代表上游没坏。
    """
    try:
        import edge_tts  # noqa: F401
    except Exception:
        return False
    return True


class TTSError(Exception):
    """A synthesis failure that can be reported without exposing credentials."""


@dataclass(frozen=True)
class TTSConfig:
    api_key: str = ""
    workspace_id: str = ""
    model: str = "cosyvoice-v3-flash"
    voice: str = "longyingtao_v3"
    timeout_seconds: float = 30.0

    @property
    def provider_name(self) -> str:
        return "cosyvoice"

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.workspace_id)

    @property
    def unavailable_reason(self) -> str | None:
        """不可用时缺的是什么。状态接口照实报出去，不做假绿灯。"""
        if not self.api_key:
            return "缺少 DASHSCOPE_API_KEY"
        if not self.workspace_id:
            return "缺少 DASHSCOPE_WORKSPACE_ID"
        return None

    @property
    def endpoint(self) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.workspace_id):
            raise TTSError("语音服务的业务空间 ID 无效。")
        return (
            f"https://{self.workspace_id}.cn-beijing.maas.aliyuncs.com"
            "/api/v1/services/audio/tts/SpeechSynthesizer"
        )

    @classmethod
    def from_env(cls) -> "TTSConfig":
        load_dotenv(ENV_FILE, override=False)
        return cls(
            api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
            workspace_id=os.getenv("DASHSCOPE_WORKSPACE_ID", "").strip(),
            model=os.getenv("TTS_MODEL", "cosyvoice-v3-flash").strip(),
            voice=os.getenv("TTS_VOICE", "longyingtao_v3").strip(),
            timeout_seconds=float(os.getenv("TTS_TIMEOUT_SECONDS", "30")),
        )


class CosyVoiceTTS:
    def __init__(self, config: TTSConfig) -> None:
        self.config = config

    async def synthesize(self, text: str) -> bytes:
        if not self.config.ready:
            raise TTSError("语音服务尚未配置。")
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    self.config.endpoint,
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json={
                        "model": self.config.model,
                        "input": {
                            "text": text,
                            "voice": self.config.voice,
                            "format": "mp3",
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
                output = payload.get("output") if isinstance(payload, dict) else None
                audio = output.get("audio") if isinstance(output, dict) else None
                audio_url = audio.get("url") if isinstance(audio, dict) else None
                if not isinstance(audio_url, str) or not audio_url:
                    raise TTSError("语音服务没有返回音频。")
                audio_url = self._audio_url(audio_url)
                async with client.stream("GET", audio_url) as audio_response:
                    audio_response.raise_for_status()
                    content = bytearray()
                    async for chunk in audio_response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_AUDIO_BYTES:
                            raise TTSError("合成音频过大。")
                if not content:
                    raise TTSError("语音服务返回了空音频。")
                return bytes(content)
        except (httpx.HTTPError, ValueError) as exc:
            raise TTSError("语音服务暂时不可用。") from exc

    @staticmethod
    def _audio_url(value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme not in {"http", "https"}
                or not host.endswith(".aliyuncs.com")
                or parsed.username or parsed.password):
            raise TTSError("语音服务返回了无效的音频地址。")
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))


@dataclass(frozen=True)
class EdgeTTSConfig:
    """Microsoft Edge 神经语音配置（免费、无需 Key）。"""

    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    timeout_seconds: float = 30.0

    @property
    def model(self) -> str:
        return "edge-tts"

    @property
    def provider_name(self) -> str:
        return "edge"

    @property
    def ready(self) -> bool:
        return edge_tts_installed()

    @property
    def unavailable_reason(self) -> str | None:
        if not edge_tts_installed():
            return "未安装 edge-tts"
        return None

    @classmethod
    def from_env(cls) -> "EdgeTTSConfig":
        load_dotenv(ENV_FILE, override=False)
        return cls(
            voice=os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural").strip(),
            rate=os.getenv("EDGE_TTS_RATE", "+0%").strip(),
            volume=os.getenv("EDGE_TTS_VOLUME", "+0%").strip(),
            pitch=os.getenv("EDGE_TTS_PITCH", "+0Hz").strip(),
            timeout_seconds=float(os.getenv("TTS_TIMEOUT_SECONDS", "30")),
        )


class EdgeTTS:
    """微软 Edge 神经语音（非流式一次性合成，返回 mp3 字节）。"""

    def __init__(self, config: EdgeTTSConfig) -> None:
        self.config = config

    async def synthesize(self, text: str) -> bytes:
        if not self.config.ready:
            raise TTSError("语音服务尚未配置。")
        try:
            import edge_tts

            communicate = edge_tts.Communicate(
                text,
                self.config.voice,
                rate=self.config.rate,
                volume=self.config.volume,
                pitch=self.config.pitch,
            )
            content = bytearray()
            async for chunk in communicate.stream():
                if chunk.get("type") != "audio":
                    continue
                content.extend(chunk["data"])
                if len(content) > MAX_AUDIO_BYTES:
                    raise TTSError("合成音频过大。")
            if not content:
                raise TTSError("语音服务返回了空音频。")
            return bytes(content)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError("语音服务暂时不可用。") from exc


PROVIDER_NAMES = ("cosyvoice", "edge")


def build_tts_service(provider: str):
    if provider == "edge":
        return EdgeTTS(EdgeTTSConfig.from_env())
    return CosyVoiceTTS(TTSConfig.from_env())


def configured_provider_name() -> str:
    """``TTS_PROVIDER`` 指定的 provider；非法值按默认的 cosyvoice 处理。

    它可能**不是**实际生效的那个——见 :func:`get_tts_service` 的回退。回退是
    静默的，所以状态接口把两者都报出去，否则"配置的那个没就绪"在回退之后
    完全看不出来。
    """
    configured = os.getenv("TTS_PROVIDER", "cosyvoice").strip().lower()
    return configured if configured in PROVIDER_NAMES else "cosyvoice"


def provider_unavailable_reason(name: str) -> str | None:
    """指定 provider 不可用时缺的是什么；配置齐备时返回 ``None``。"""
    return build_tts_service(name).config.unavailable_reason


def get_tts_service():
    """按 ``TTS_PROVIDER`` 选择语音服务（默认 cosyvoice，edge 作为备选）。

    配置的 provider 不可用时退到另一个可用的 provider——语音是锦上添花，不该
    因为一个依赖缺失就让整条链路哑掉；两个都不可用时返回配置的那个，让
    ``/api/tts/status`` 如实报出到底缺了什么。回退本身是静默的，因此状态接口
    另外用 ``configured_provider`` / ``fallback_reason`` 说明退到了哪、为什么退。
    """
    configured = configured_provider_name()
    service = build_tts_service(configured)
    if service.config.ready:
        return service
    for name in PROVIDER_NAMES:
        if name == configured:
            continue
        candidate = build_tts_service(name)
        if candidate.config.ready:
            return candidate
    return service