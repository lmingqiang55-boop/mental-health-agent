"""CosyVoice playback uses only a saved assistant reply and returns MP3 bytes."""

import asyncio

import httpx
from fastapi.testclient import TestClient

from backend.api import tts as tts_api
from backend.audio import tts as tts_module
from backend.audio.tts import CosyVoiceTTS, TTSConfig, TTSError
from backend.core.session_manager import session_manager
from backend.main import app
from backend.models.enums import MessageRole
from backend.models.states import Message


client = TestClient(app)


def test_cosyvoice_http_contract_and_audio_download(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == "POST":
            assert request.url.host == "ws-example.cn-beijing.maas.aliyuncs.com"
            assert request.headers["Authorization"] == "Bearer example-key"
            assert request.read()
            return httpx.Response(200, json={"output": {"audio": {
                "url": "http://result.oss-cn-beijing.aliyuncs.com/reply.mp3?signature=test"
            }}})
        assert str(request.url) == "https://result.oss-cn-beijing.aliyuncs.com/reply.mp3?signature=test"
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=b"ID3example", headers={"Content-Type": "audio/mpeg"})

    transport = httpx.MockTransport(handle)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(tts_module.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=transport, **kwargs))
    service = CosyVoiceTTS(TTSConfig(api_key="example-key", workspace_id="ws-example"))
    assert asyncio.run(service.synthesize("我听到你最近压力很大。")) == b"ID3example"
    assert len(calls) == 2
    assert calls[0].read().decode("utf-8").find("longyingtao_v3") != -1


def test_tts_route_reads_saved_assistant_turn(monkeypatch):
    class FakeTTS:
        config = TTSConfig(api_key="fake", workspace_id="ws-fake")
        received = None

        async def synthesize(self, text):
            self.received = text
            return b"ID3test"

    fake = FakeTTS()
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: fake)
    session_id = client.post("/api/session").json()["session_id"]

    def add_turn(session):
        session.conversation_history.extend([
            Message(role=MessageRole.USER, content="最近睡不好"),
            Message(role=MessageRole.ASSISTANT, content="我们可以先聊聊睡眠。"),
        ])
        session.turn_count = 1

    session_manager.modify_session(session_id, add_turn)
    response = client.post("/api/tts", json={"session_id": session_id, "turn_count": 1})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3test"
    assert fake.received == "我们可以先聊聊睡眠。"
    assert client.post("/api/tts", json={
        "session_id": session_id, "turn_count": 2,
    }).status_code == 404


def test_cosyvoice_handles_missing_audio(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(tts_module.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"output": {"audio": None}})), **kwargs))
    service = CosyVoiceTTS(TTSConfig(api_key="example-key", workspace_id="ws-example"))
    try:
        asyncio.run(service.synthesize("你好"))
    except TTSError as exc:
        assert "没有返回音频" in str(exc)
    else:
        raise AssertionError("missing audio must raise TTSError")
