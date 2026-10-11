"""Speech synthesis for one completed assistant turn.

Two providers are available, selected by the ``TTS_PROVIDER`` env var:

- ``edge`` (default): Microsoft Edge 神经语音（免费、无需 Key，需联网）。
- ``cosyvoice``: 阿里云百炼 CosyVoice（需 ``DASHSCOPE_API_KEY`` + ``DASHSCOPE_WORKSPACE_ID``）。
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
    def ready(self) -> bool:
        return bool(self.api_key and self.workspace_id)

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
    def ready(self) -> bool:
        try:
            import edge_tts  # noqa: F401
        except Exception:
            return False
        return True

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


def get_tts_service():
    """按 ``TTS_PROVIDER`` 选择语音服务（默认 edge-tts）。"""
    provider = os.getenv("TTS_PROVIDER", "edge").strip().lower()
    if provider == "cosyvoice":
        return CosyVoiceTTS(TTSConfig.from_env())
    return EdgeTTS(EdgeTTSConfig.from_env())