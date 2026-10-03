"""Optional ASR settings; no machine-specific paths or automatic mock fallback."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class ASRConfig:
    provider: str = "disabled"
    model: str = "iic/SenseVoiceSmall"
    model_revision: str = "master"
    device: str = "cpu"
    language: str = "auto"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_duration_seconds: float = 60.0
    timeout_seconds: float = 60.0
    max_pending: int = 4
    cpu_threads: int = 4

    def __post_init__(self) -> None:
        import math

        if self.provider not in {"disabled", "sensevoice"}:
            raise ValueError("ASR_PROVIDER must be disabled or sensevoice")
        if self.language not in {"auto", "zh", "en", "yue", "ja", "ko"}:
            raise ValueError("Unsupported ASR_LANGUAGE")
        if not self.model.strip() or not self.model_revision.strip():
            raise ValueError("ASR model and revision cannot be blank")
        if not 0 < self.max_upload_bytes <= 20 * 1024 * 1024:
            raise ValueError("ASR_MAX_UPLOAD_MB must be in (0, 20]")
        if not math.isfinite(self.max_duration_seconds) or not 0 < self.max_duration_seconds <= 60:
            raise ValueError("ASR_MAX_DURATION_SECONDS must be in (0, 60]")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("ASR_TIMEOUT_SECONDS must be positive and finite")
        if not 1 <= self.max_pending <= 16 or not 1 <= self.cpu_threads <= 32:
            raise ValueError("Invalid ASR queue or CPU thread limit")

    @classmethod
    def from_env(cls) -> "ASRConfig":
        # Shared by startup and the benchmark CLI; explicit process settings win.
        load_dotenv(DEFAULT_ENV_FILE, override=False)
        return cls(
            provider=os.getenv("ASR_PROVIDER", "disabled").strip().lower(),
            model=os.getenv("ASR_MODEL", "iic/SenseVoiceSmall"),
            model_revision=os.getenv("ASR_MODEL_REVISION", "master"),
            device=os.getenv("ASR_DEVICE", "cpu"),
            language=os.getenv("ASR_LANGUAGE", "auto"),
            max_upload_bytes=int(float(os.getenv("ASR_MAX_UPLOAD_MB", "10")) * 1024 * 1024),
            max_duration_seconds=float(os.getenv("ASR_MAX_DURATION_SECONDS", "60")),
            timeout_seconds=float(os.getenv("ASR_TIMEOUT_SECONDS", "60")),
            max_pending=int(os.getenv("ASR_MAX_PENDING", "4")),
            cpu_threads=int(os.getenv("ASR_CPU_THREADS", "4")),
        )
