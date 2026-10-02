"""ASR startup reads the project .env before creating the cached service."""

import asyncio
import os
from unittest.mock import patch

from backend import main
from backend.audio import config as audio_config
from backend.audio import transcriber


def test_env_file_enables_asr_during_startup(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ASR_PROVIDER=sensevoice\nASR_DEVICE=cpu\nASR_LANGUAGE=zh\n", encoding="utf-8")
    monkeypatch.setattr(audio_config, "DEFAULT_ENV_FILE", env_file, raising=False)
    loaded = []

    class Recognizer:
        def load(self):
            loaded.append(True)

        def recognize(self, waveform):
            return "没有。"

    monkeypatch.setattr(transcriber, "SenseVoiceRecognizer", lambda config: Recognizer())
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith("ASR_")}

    async def run():
        async with main.lifespan(main.app):
            service = transcriber.get_transcription_service()
            assert service.config.provider == "sensevoice"
            assert service.config.language == "zh"
            assert service.state == "ready"
            assert loaded == [True]

    transcriber.get_transcription_service.cache_clear()
    try:
        with patch.dict(os.environ, clean_env, clear=True):
            asyncio.run(run())
    finally:
        transcriber.get_transcription_service.cache_clear()


def test_process_environment_overrides_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ASR_PROVIDER=sensevoice\nASR_LANGUAGE=zh\nASR_CPU_THREADS=2\n", encoding="utf-8")
    monkeypatch.setattr(audio_config, "DEFAULT_ENV_FILE", env_file, raising=False)
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith("ASR_")}
    clean_env.update({"ASR_PROVIDER": "disabled", "ASR_LANGUAGE": "en"})
    with patch.dict(os.environ, clean_env, clear=True):
        config = audio_config.ASRConfig.from_env()
        assert config.provider == "disabled"
        assert config.language == "en"
        assert config.cpu_threads == 2
