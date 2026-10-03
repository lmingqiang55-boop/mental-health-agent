"""Whole-recording SenseVoice inference, with a bounded serial worker.

Reference: FunASR AutoModel and QwenAudio/SenseVoice inference examples.
We remove control tags directly: upstream rich postprocessing adds emotion emoji.
"""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache
from threading import BoundedSemaphore, Event
from time import perf_counter
from typing import Protocol

from backend.audio.config import ASRConfig
from backend.audio.decoder import decode_audio
from backend.audio.errors import AudioError

logger = logging.getLogger(__name__)
SAMPLE_RATE = 16000


class Recognizer(Protocol):
    def load(self) -> None: ...
    def recognize(self, waveform) -> str: ...


def clean_transcript(raw_text: str) -> str:
    return re.sub(r"<\|[^<>]*\|>", "", raw_text).strip()


class SenseVoiceRecognizer:
    def __init__(self, config: ASRConfig) -> None:
        self.config = config
        self._model = None

    def load(self) -> None:
        import numpy as np
        import torch
        from funasr import AutoModel
        from backend.audio.tokenizer import register_memory_tokenizer

        if self.config.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("Requested CUDA ASR device is unavailable")
        # Use FunASR's built-in implementation rather than downloaded Python code.
        self._model = AutoModel(
            model=self.config.model,
            model_revision=self.config.model_revision,
            tokenizer=register_memory_tokenizer(),
            device=self.config.device,
            ncpu=self.config.cpu_threads,
            trust_remote_code=False,
            disable_update=True,
            disable_pbar=True,
            disable_log=True,
        )
        self.recognize(np.zeros(SAMPLE_RATE, dtype=np.float32))

    def recognize(self, waveform) -> str:
        if self._model is None:
            raise RuntimeError("ASR model has not loaded")
        result = self._model.generate(
            input=waveform,
            fs=SAMPLE_RATE,
            cache={},
            language=self.config.language,
            use_itn=True,
            batch_size=1,
        )
        if not isinstance(result, list) or len(result) != 1:
            raise RuntimeError("Unexpected whole-recording ASR response")
        text = result[0].get("text")
        if not isinstance(text, str):
            raise RuntimeError("ASR response does not contain text")
        return text


class _TranscriptionReservation:
    """One slot held until both the request and any submitted work have ended."""

    def __init__(self, service) -> None:
        self.service = service
        self.future = None
        self.active = True

    async def transcribe(self, data: bytes, content_type: str,
                         recording_duration_ms: float) -> str:
        return await self.service._transcribe_reserved(
            self, data, content_type, recording_duration_ms)


class TranscriptionService:
    def __init__(self, config: ASRConfig, recognizer: Recognizer | None = None) -> None:
        self.config = config
        self._recognizer = recognizer or SenseVoiceRecognizer(config)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")
        self._slots = BoundedSemaphore(config.max_pending)
        self.state = "disabled" if config.provider == "disabled" else "not_started"

    async def start(self) -> None:
        if self.config.provider == "disabled" or self.state == "ready":
            return
        self.state = "loading"
        try:
            await asyncio.wrap_future(self._worker.submit(self._recognizer.load))
        except Exception:
            logger.exception("ASR loading failed; audio requests will return ASR_UNAVAILABLE")
            self.state = "unavailable"
        else:
            self.state = "ready"

    def close(self) -> None:
        self.state = "closed"
        self._worker.shutdown(wait=False, cancel_futures=True)

    def ensure_ready(self) -> None:
        if self.state != "ready":
            raise AudioError("ASR_UNAVAILABLE", "语音识别尚未就绪，请检查配置与模型加载状态。", 503)

    @contextmanager
    def reserve(self):
        """Reject excess requests before reading their audio into memory."""
        self.ensure_ready()
        if not self._slots.acquire(blocking=False):
            raise AudioError("ASR_BUSY", "语音识别正在处理其他录音，请稍后重试。", 503)
        reservation = _TranscriptionReservation(self)
        try:
            yield reservation
        finally:
            reservation.active = False
            if reservation.future is None:
                self._slots.release()
            else:
                # Cancellation/timeout cannot free work still held by the worker.
                reservation.future.add_done_callback(lambda _: self._slots.release())

    async def transcribe(self, data: bytes, content_type: str,
                         recording_duration_ms: float) -> str:
        with self.reserve() as reservation:
            return await reservation.transcribe(data, content_type, recording_duration_ms)

    async def _transcribe_reserved(self, reservation: _TranscriptionReservation,
                                  data: bytes, content_type: str,
                                  recording_duration_ms: float) -> str:
        if not reservation.active or reservation.future is not None:
            raise RuntimeError("Transcription reservation is inactive or already used")
        self.ensure_ready()
        abandoned = Event()

        def run():
            if abandoned.is_set():
                return None
            return self._transcribe(data, content_type, recording_duration_ms)

        future = reservation.future = self._worker.submit(run)
        wrapped = asyncio.wrap_future(future)
        # Shield keeps cancelled work items counted until the worker dequeues them.
        # ThreadPoolExecutor otherwise retains their large arguments in its queue
        # while a cancelled Future's callback prematurely releases the slot.
        wrapped.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        try:
            return await asyncio.wait_for(
                asyncio.shield(wrapped), timeout=self.config.timeout_seconds)
        except TimeoutError as exc:
            abandoned.set()
            raise AudioError("ASR_TIMEOUT", "语音识别超时，请稍后重试原录音。", 504) from exc
        except asyncio.CancelledError:
            abandoned.set()
            raise

    def _transcribe(self, data: bytes, content_type: str,
                    recording_duration_ms: float) -> str:
        start = perf_counter()
        waveform = decode_audio(data, content_type, self.config, recording_duration_ms)
        decoded = perf_counter()
        try:
            raw_text = self._recognizer.recognize(waveform)
            text = clean_transcript(raw_text)
        except Exception as exc:
            logger.exception("ASR inference failed")
            raise AudioError("ASR_UNAVAILABLE", "语音识别暂时不可用，请稍后重试。", 503) from exc
        logger.info("ASR decode_ms=%.1f inference_ms=%.1f audio_duration_ms=%.1f",
                    (decoded - start) * 1000, (perf_counter() - decoded) * 1000,
                    waveform.size / 16)
        if "<|nospeech|>" in raw_text or not text or not any(char.isalnum() for char in text):
            raise AudioError("NO_SPEECH", "没有识别到有效语音，请重新录音。")
        if len(text) > 4000:
            raise AudioError("TRANSCRIPT_TOO_LONG", "转写结果超过 4000 字，请缩短录音。")
        return text


@lru_cache(maxsize=1)
def get_transcription_service() -> TranscriptionService:
    return TranscriptionService(ASRConfig.from_env())
