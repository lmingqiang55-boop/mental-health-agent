"""``/api/tts/probe`` 真探测：它存在的理由是"配置齐全"不等于"现在能出声"。"""

import httpx  # noqa: F401  (与 test_tts.py 共用环境，保持导入形态一致)
import pytest
from fastapi.testclient import TestClient

from backend.api import tts as tts_api
from backend.audio.tts import EdgeTTSConfig, TTSConfig, TTSError
from backend.main import app


client = TestClient(app)


class _FakeService:
    def __init__(self, config, audio=b"ID3probe", error=None):
        self.config = config
        self._audio = audio
        self._error = error
        self.calls = 0

    async def synthesize(self, text):
        self.calls += 1
        assert text  # 探测必须真的送一句话进去
        if self._error is not None:
            raise self._error
        return self._audio


@pytest.fixture(autouse=True)
def clean_probe_state():
    tts_api._PROBE_CACHE.clear()
    tts_api._LAST_FAILURE.clear()
    yield
    tts_api._PROBE_CACHE.clear()
    tts_api._LAST_FAILURE.clear()


def _ready_config():
    return TTSConfig(api_key="fake", workspace_id="ws-fake")


def test_probe_reports_real_synthesis_and_caches(monkeypatch):
    fake = _FakeService(_ready_config())
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: fake)
    assert client.get("/api/tts/status").json()["last_probe"] is None

    first = client.post("/api/tts/probe")
    assert first.status_code == 200
    body = first.json()
    assert body["ok"] is True
    assert body["audio_bytes"] == len(b"ID3probe")
    assert body["latency_ms"] >= 0
    assert body["error"] is None
    assert body["cached"] is False
    assert fake.calls == 1

    second = client.post("/api/tts/probe").json()
    assert second["cached"] is True
    assert second["checked_at"] == body["checked_at"]
    assert fake.calls == 1, "缓存期内不该再真合成一次"

    assert client.get("/api/tts/status").json()["last_probe"]["ok"] is True


def test_probe_cache_expires(monkeypatch):
    fake = _FakeService(_ready_config())
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: fake)
    monkeypatch.setattr(tts_api, "PROBE_CACHE_SECONDS", 0.0)
    client.post("/api/tts/probe")
    assert client.post("/api/tts/probe").json()["cached"] is False
    assert fake.calls == 2


def test_probe_reports_missing_configuration(monkeypatch):
    # 没有 Key 的 provider：探测不该报"通"，也不该真去合成。
    fake = _FakeService(TTSConfig())
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: fake)
    body = client.post("/api/tts/probe").json()
    assert body["ok"] is False
    assert body["audio_bytes"] == 0
    assert body["latency_ms"] is None
    assert body["error"] == fake.config.unavailable_reason
    assert fake.calls == 0


def test_status_without_fallback_reports_no_reason(monkeypatch):
    fake = _FakeService(_ready_config())
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: fake)
    monkeypatch.setattr(tts_api, "configured_provider_name", lambda: "cosyvoice")
    body = client.get("/api/tts/status").json()
    assert body["configured_provider"] == "cosyvoice"
    assert body["fallback_reason"] is None


def test_status_shows_which_provider_is_configured(monkeypatch):
    """配置的 provider 缺东西时会静默回退；状态接口必须说明退了、以及为什么。"""
    fake = _FakeService(EdgeTTSConfig())
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: fake)
    monkeypatch.setattr(tts_api, "configured_provider_name", lambda: "cosyvoice")
    monkeypatch.setattr(
        tts_api, "provider_unavailable_reason",
        lambda name: "缺少 DASHSCOPE_API_KEY" if name == "cosyvoice" else None)

    body = client.get("/api/tts/status").json()
    assert body["provider"] == "edge"
    assert body["configured_provider"] == "cosyvoice"
    assert body["fallback_reason"] == "缺少 DASHSCOPE_API_KEY"


def test_failed_probe_degrades_status(monkeypatch):
    fake = _FakeService(_ready_config(), error=TTSError("语音服务暂时不可用。"))
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: fake)
    body = client.post("/api/tts/probe").json()
    assert body["ok"] is False
    assert body["error"] == "语音服务暂时不可用。"
    # 探测失败也进状态接口，前端才不会一直显示"语音可用"。
    status = client.get("/api/tts/status").json()
    assert status["state"] == "degraded"
    assert status["last_error"] == "语音服务暂时不可用。"
    assert status["last_probe"]["ok"] is False


def test_failed_probe_is_forgotten_after_a_success(monkeypatch):
    broken = _FakeService(_ready_config(), error=TTSError("语音服务暂时不可用。"))
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: broken)
    assert client.post("/api/tts/probe").json()["ok"] is False

    healthy = _FakeService(_ready_config())
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: healthy)
    monkeypatch.setattr(tts_api, "PROBE_CACHE_SECONDS", 0.0)
    assert client.post("/api/tts/probe").json()["ok"] is True
    status = client.get("/api/tts/status").json()
    assert status["state"] == "ready"
    assert status["last_error"] is None
