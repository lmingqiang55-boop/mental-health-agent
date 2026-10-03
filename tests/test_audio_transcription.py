"""Real multipart parsing and PyAV decoding; only model inference is stubbed."""

import asyncio
from dataclasses import replace
from io import BytesIO
from threading import Event, Thread
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from backend.api import audio
from backend.audio.config import ASRConfig
from backend.audio.decoder import decode_audio
from backend.audio.transcriber import AudioError, TranscriptionService, clean_transcript
from backend.core.session_manager import session_manager
from backend.main import app

client = TestClient(app)


def wav_bytes(seconds=0.5, rate=48000, channels=2, silent=False):
    t = np.arange(int(seconds * rate)) / rate
    pcm = np.zeros(t.size, dtype="<i2") if silent else (
        8000 * np.sin(2 * np.pi * 440 * t)).astype("<i2")
    stream = BytesIO()
    with wave.open(stream, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(np.repeat(pcm[:, None], channels, axis=1).tobytes())
    return stream.getvalue()


class StubRecognizer:
    def __init__(self, text="<|zh|><|SAD|><|Speech|><|withitn|>没有。", hook=None):
        self.text = text
        self.hook = hook
        self.calls = []

    def load(self):
        pass

    def recognize(self, waveform):
        self.calls.append(waveform)
        if self.hook:
            self.hook()
        return self.text


@pytest.fixture
def service(monkeypatch):
    recognizer = StubRecognizer()
    instance = TranscriptionService(ASRConfig(provider="sensevoice", max_pending=1), recognizer)
    asyncio.run(instance.start())
    monkeypatch.setattr(audio, "get_transcription_service", lambda: instance)
    yield instance, recognizer
    instance.close()


def upload(data=None, *, mime="audio/wav", fields=None):
    metadata = {
        "session_id": client.post("/api/session").json()["session_id"],
        "utterance_id": "u1", "capture_id": "c1", "recording_start_ms": "12000",
        "recording_end_ms": "12500",
    }
    metadata.update(fields or {})
    return client.post("/api/audio/transcribe", data=metadata,
                       files={"file": ("recording.wav", wav_bytes() if data is None else data, mime)})


def test_upload_downmix_resample_returns_metadata_without_chat(service):
    instance, recognizer = service
    response = upload(mime="audio/wav; codecs=pcm")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["text"] == "没有。"
    assert body["utterance_id"] == "u1"
    assert body["speech"] == {"capture_id": "c1", "recording_start_ms": 12000,
                              "recording_end_ms": 12500}
    waveform = recognizer.calls[0]
    assert waveform.dtype == np.float32 and waveform.shape == (8000,)
    assert np.max(np.abs(waveform[-100:])) > 0.1  # resampler tail was flushed
    session = client.get(f"/api/session/{body['session_id']}").json()
    assert session["turn_count"] == 0 and session["conversation_history"] == []
    assert session["latest_audio_state"] is None


def test_short_answer_is_not_rejected_for_duration(service):
    response = upload(wav_bytes(seconds=0.15), fields={"recording_end_ms": "12150"})
    assert response.status_code == 200 and response.json()["text"] == "没有。"


@pytest.mark.parametrize("data,mime,fields,status,code", [
    (b"", "audio/wav", {}, 422, "INVALID_AUDIO"),
    (b"broken audio", "audio/wav", {}, 422, "INVALID_AUDIO"),
    (None, "application/octet-stream", {}, 415, "UNSUPPORTED_AUDIO_FORMAT"),
    (None, "audio/webm", {}, 415, "UNSUPPORTED_AUDIO_FORMAT"),
    (None, "audio/wav", {"session_id": "missing"}, 404, "SESSION_NOT_FOUND"),
    (None, "audio/wav", {"recording_end_ms": "12000"}, 422, "VALIDATION_ERROR"),
    (None, "audio/wav", {"recording_end_ms": "Infinity"}, 422, "VALIDATION_ERROR"),
    (None, "audio/wav", {"recording_end_ms": "73000"}, 422, "AUDIO_TOO_LONG"),
    (None, "audio/wav", {"recording_end_ms": "15000"}, 422, "AUDIO_TIME_MISMATCH"),
])
def test_upload_errors_do_not_call_model(service, data, mime, fields, status, code):
    response = upload(data, mime=mime, fields=fields)
    assert response.status_code == status, response.json()
    assert response.json()["error"]["code"] == code
    assert service[1].calls == []


def test_limits_bound_stream_and_actual_decoded_duration(service):
    service[0].config = replace(service[0].config, max_upload_bytes=256)
    response = upload()
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "AUDIO_TOO_LARGE"
    with pytest.raises(AudioError) as error:
        decode_audio(wav_bytes(seconds=1), "audio/wav",
                     ASRConfig(max_duration_seconds=0.5), 500)
    assert error.value.code == "AUDIO_TOO_LONG"


def test_full_minute_upload_preserves_all_samples_and_metadata(service):
    response = upload(wav_bytes(seconds=60, rate=16000, channels=1),
                      fields={"recording_end_ms": "72000"})
    assert response.status_code == 200, response.json()
    assert service[1].calls[0].shape == (60 * 16000,)
    assert response.json()["speech"]["recording_end_ms"] == 72000
    assert client.get("/api/audio/status").json()["max_duration_seconds"] == 60


def test_actual_audio_over_minute_is_rejected_even_if_timeline_claims_one_minute(service):
    response = upload(wav_bytes(seconds=60.2, rate=16000, channels=1),
                      fields={"recording_end_ms": "72000"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AUDIO_TOO_LONG"
    assert service[1].calls == []


@pytest.mark.parametrize("raw", ["<|nospeech|><|NEUTRAL|><|Event_UNK|><|woitn|>",
                                 "<|nospeech|>hello", "。"])
def test_empty_model_output_is_no_speech(service, raw):
    service[1].text = raw
    response = upload()
    assert response.status_code == 422 and response.json()["error"]["code"] == "NO_SPEECH"


def test_exact_silence_does_not_call_model(service):
    response = upload(wav_bytes(silent=True))
    assert response.status_code == 422 and response.json()["error"]["code"] == "NO_SPEECH"
    assert service[1].calls == []


def test_overlong_transcript_is_not_truncated(service):
    service[1].text = "没有" * 2001
    response = upload()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TRANSCRIPT_TOO_LONG"


def test_model_failure_and_unavailable_status(service):
    def fail():
        raise RuntimeError("model failure")
    service[1].hook = fail
    response = upload()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ASR_UNAVAILABLE"
    service[0].state = "unavailable"
    assert client.get("/api/audio/status").json()["state"] == "unavailable"
    assert upload().status_code == 503


def test_late_transcription_rechecks_session(service):
    session_id = client.post("/api/session").json()["session_id"]
    service[1].hook = lambda: session_manager.delete_session(session_id)
    response = upload(fields={"session_id": session_id})
    assert response.status_code == 404


@pytest.mark.parametrize("lookup_number", [1, 2])
def test_session_lock_does_not_block_event_loop(service, monkeypatch, lookup_number):
    target = session_manager.create_session().session_id
    unrelated = session_manager.create_session().session_id
    lock_entered, lookup_entered, release = Event(), Event(), Event()
    released_by_event_loop = []

    def hold_lock(session):
        lock_entered.set()
        released_by_event_loop.append(release.wait(2))

    holder = Thread(target=lambda: session_manager.modify_session(unrelated, hold_lock))

    def start_holder():
        holder.start()
        assert lock_entered.wait(1)

    real_lookup = session_manager.get_session
    lookups = 0

    def checked_lookup(session_id):
        nonlocal lookups
        lookups += 1
        if lookups == lookup_number:
            lookup_entered.set()
        return real_lookup(session_id)

    monkeypatch.setattr(session_manager, "get_session", checked_lookup)
    if lookup_number == 1:
        start_holder()
    else:
        service[1].hook = start_holder

    async def unblock_from_event_loop():
        assert await asyncio.to_thread(lookup_entered.wait, 1)
        release.set()

    async def run():
        heartbeat = asyncio.create_task(unblock_from_event_loop())
        try:
            async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test") as async_client:
                response = await async_client.post("/api/audio/transcribe", data={
                    "session_id": target, "utterance_id": "lock-test", "capture_id": "c1",
                    "recording_start_ms": "0", "recording_end_ms": "500",
                }, files={"file": ("recording.wav", wav_bytes(), "audio/wav")})
            assert response.status_code == 200, response.json()
            await heartbeat
        finally:
            release.set()
            await heartbeat

    try:
        asyncio.run(run())
        assert released_by_event_loop == [True]
        assert lookups == 2
    finally:
        release.set()
        if holder.ident is not None:
            holder.join(timeout=3)


def test_transcribe_then_chat_then_assess(service, policy_stub, evaluation_stub):
    policy_stub()
    response = upload().json()
    assert client.post("/api/chat", json=response).status_code == 200
    assert client.post("/api/chat", json=response).json()["turn_count"] == 1
    assert client.post("/api/assessment", json={"session_id": response["session_id"]}).status_code == 200
    history = client.get(f"/api/session/{response['session_id']}").json()["conversation_history"]
    assert history[0]["speech"] == response["speech"]
    assert evaluation_stub.inputs[0].dialogue_history[0].content == "没有。"


def test_timeout_does_not_release_running_model_slot():
    started, release = Event(), Event()

    def block():
        started.set()
        assert release.wait(3)

    service = TranscriptionService(
        ASRConfig(provider="sensevoice", timeout_seconds=0.05, max_pending=1),
        StubRecognizer(hook=block))

    async def run():
        await service.start()
        with pytest.raises(AudioError) as error:
            await service.transcribe(wav_bytes(), "audio/wav", 500)
        assert started.is_set() and error.value.code == "ASR_TIMEOUT"
        with pytest.raises(AudioError) as error:
            await service.transcribe(wav_bytes(), "audio/wav", 500)
        assert error.value.code == "ASR_BUSY"
        release.set()
        await asyncio.wrap_future(service._worker.submit(lambda: None))
        service._recognizer.hook = None
        assert await service.transcribe(wav_bytes(), "audio/wav", 500) == "没有。"

    try:
        asyncio.run(run())
    finally:
        release.set()
        service.close()


def test_tag_cleanup_preserves_negation_and_internal_text():
    assert clean_transcript(" <|zh|><|SAD|><|Speech|>我不想。  I am okay. <|withitn|> ") == (
        "我不想。  I am okay.")


def test_json_request_and_duplicate_multipart_fields_rejected(service):
    assert client.post("/api/audio/transcribe", json={}).status_code == 422
    metadata = [("session_id", (None, "s")), ("utterance_id", (None, "u")),
                ("capture_id", (None, "c")), ("recording_start_ms", (None, "0")),
                ("recording_end_ms", (None, "500")), ("capture_id", (None, "c2")),
                ("file", ("test.wav", wav_bytes(), "audio/wav"))]
    assert client.post("/api/audio/transcribe", files=metadata).status_code == 422


def test_chunked_request_is_bounded_without_content_length(service):
    service[0].config = replace(service[0].config, max_upload_bytes=256)
    def chunks():
        for _ in range(20):
            yield b"x" * 4096
    response = client.post("/api/audio/transcribe", content=chunks(), headers={
        "Content-Type": "multipart/form-data; boundary=test"})
    assert response.status_code == 413


@pytest.mark.parametrize("format_name,codec,mime", [
    ("webm", "libopus", "audio/webm"), ("ogg", "libopus", "audio/ogg"),
    ("mp4", "aac", "audio/mp4"), ("mp3", "mp3", "audio/mpeg"),
    ("flac", "flac", "audio/flac"),
])
def test_supported_compressed_formats_are_actually_decoded(service, format_name, codec, mime):
    buffer = BytesIO()
    with av.open(buffer, "w", format=format_name) as container:
        stream = container.add_stream(codec, rate=48000)
        stream.layout = "mono"
        for start in range(0, 24000, 960):
            t = np.arange(start, start+960) / 48000
            frame = av.AudioFrame.from_ndarray(
                (0.2*np.sin(2*np.pi*440*t)).astype(np.float32)[None, :],
                format="flt", layout="mono")
            frame.sample_rate = 48000
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    response = upload(buffer.getvalue(), mime=mime)
    assert response.status_code == 200, response.json()
    assert service[1].calls[0].ndim == 1
    assert abs(service[1].calls[0].size / 16 - 500) < 100


def test_large_accepted_upload_stays_in_memory(service, monkeypatch):
    import tempfile
    def fail_rollover(_):
        raise AssertionError("Raw audio should never spill to disk")
    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", fail_rollover)
    response = upload(wav_bytes(seconds=8), fields={"recording_end_ms": "20000"})
    assert response.status_code == 200


def test_queued_timeouts_remain_bounded_until_worker_drains():
    started, release = Event(), Event()
    def block():
        started.set()
        assert release.wait(3)
    recognizer = StubRecognizer(hook=block)
    instance = TranscriptionService(
        ASRConfig(provider="sensevoice", timeout_seconds=0.1, max_pending=2), recognizer)
    async def run():
        await instance.start()
        running = asyncio.create_task(instance.transcribe(wav_bytes(), "audio/wav", 500))
        assert await asyncio.to_thread(started.wait, 1)
        with pytest.raises(AudioError) as error:
            await instance.transcribe(wav_bytes(), "audio/wav", 500)
        assert error.value.code == "ASR_TIMEOUT"
        with pytest.raises(AudioError):
            await running
        # Both the running and the abandoned queued item still hold their slots.
        with pytest.raises(AudioError) as error:
            await instance.transcribe(wav_bytes(), "audio/wav", 500)
        assert error.value.code == "ASR_BUSY"
        release.set()
        await asyncio.wrap_future(instance._worker.submit(lambda: None))
        assert len(recognizer.calls) == 1  # abandoned queued inference was skipped
        recognizer.hook = None
        assert await instance.transcribe(wav_bytes(), "audio/wav", 500) == "没有。"
    try:
        asyncio.run(run())
    finally:
        release.set()
        instance.close()


@pytest.mark.parametrize("cancel_upload", [False, True])
def test_busy_upload_does_not_read_body_and_capacity_recovers(service, cancel_upload):
    session_id = session_manager.create_session().session_id
    metadata = {"session_id": session_id, "utterance_id": "upload-1", "capture_id": "c1",
                "recording_start_ms": "0", "recording_end_ms": "500"}
    request = httpx.Request("POST", "http://test/api/audio/transcribe", data=metadata,
                           files={"file": ("recording.wav", wav_bytes(), "audio/wav")})
    body = request.read()

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed_body():
            entered.set()
            await release.wait()
            yield body

        async def unread_body():
            raise AssertionError("A rejected upload must not read any request body")
            yield b""

        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test") as async_client:
            first = asyncio.create_task(async_client.post(
                "/api/audio/transcribe", content=delayed_body(), headers=request.headers))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                busy = await asyncio.wait_for(async_client.post(
                    "/api/audio/transcribe", content=unread_body(), headers=request.headers), 1)
                assert busy.status_code == 503 and busy.json()["error"]["code"] == "ASR_BUSY"
                if cancel_upload:
                    first.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await first
                else:
                    release.set()
                    assert (await first).status_code == 200
                recovered = await async_client.post(
                    "/api/audio/transcribe", content=body, headers=request.headers)
                assert recovered.status_code == 200, recovered.json()
            finally:
                release.set()
                if not first.done():
                    await first

    asyncio.run(run())


@pytest.mark.parametrize("lookup_number", [1, 2])
def test_busy_before_body_read_while_session_lookup_waits(service, monkeypatch, lookup_number):
    target = session_manager.create_session().session_id
    unrelated = session_manager.create_session().session_id
    lock_entered, lookup_entered, release = Event(), Event(), Event()

    def hold_lock(session):
        lock_entered.set()
        assert release.wait(3)

    holder = Thread(target=lambda: session_manager.modify_session(unrelated, hold_lock))

    def start_holder():
        holder.start()
        assert lock_entered.wait(1)

    real_lookup = session_manager.get_session
    lookups = 0

    def checked_lookup(session_id):
        nonlocal lookups
        lookups += 1
        if lookups == lookup_number:
            lookup_entered.set()
        return real_lookup(session_id)

    monkeypatch.setattr(session_manager, "get_session", checked_lookup)
    if lookup_number == 1:
        start_holder()
    else:
        service[1].hook = start_holder

    async def unread_body():
        raise AssertionError("Busy requests must be rejected before reading audio")
        yield b""

    async def run():
        async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test") as async_client:
            first = asyncio.create_task(async_client.post("/api/audio/transcribe", data={
                "session_id": target, "utterance_id": "lock-1", "capture_id": "c1",
                "recording_start_ms": "0", "recording_end_ms": "500",
            }, files={"file": ("recording.wav", wav_bytes(), "audio/wav")}))
            try:
                assert await asyncio.to_thread(lookup_entered.wait, 1)
                for _ in range(7):
                    busy = await asyncio.wait_for(async_client.post(
                        "/api/audio/transcribe", content=unread_body(),
                        headers={"Content-Type": "multipart/form-data; boundary=test"}), 1)
                    assert busy.status_code == 503
                    assert busy.json()["error"]["code"] == "ASR_BUSY"
                assert not first.done() and lookups == lookup_number
                release.set()
                assert (await first).status_code == 200
            finally:
                release.set()
                await first

    try:
        asyncio.run(run())
        service[1].hook = None
        assert upload().status_code == 200
    finally:
        release.set()
        holder.join(timeout=3)


@pytest.mark.parametrize("failure", ["form", "session", "decode", "model", "late_session"])
def test_failed_upload_releases_capacity(service, failure):
    if failure == "form":
        response = client.post("/api/audio/transcribe", json={})
        assert response.status_code == 422
    elif failure == "session":
        assert upload(fields={"session_id": "missing"}).status_code == 404
    elif failure == "decode":
        assert upload(b"broken audio").status_code == 422
    elif failure == "model":
        def fail():
            raise RuntimeError("model failure")
        service[1].hook = fail
        assert upload().status_code == 503
    else:
        session_id = session_manager.create_session().session_id
        service[1].hook = lambda: session_manager.delete_session(session_id)
        assert upload(fields={"session_id": session_id}).status_code == 404
    service[1].hook = None
    assert upload().status_code == 200


def test_submit_failure_releases_capacity(service, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("worker unavailable")

    async def run():
        with monkeypatch.context() as context:
            context.setattr(service[0]._worker, "submit", fail)
            with pytest.raises(RuntimeError, match="worker unavailable"):
                await service[0].transcribe(wav_bytes(), "audio/wav", 500)
        assert await service[0].transcribe(wav_bytes(), "audio/wav", 500) == "没有。"

    asyncio.run(run())


def test_cancelled_running_and_queued_work_keep_capacity_until_drained():
    started, release = Event(), Event()

    def block():
        started.set()
        assert release.wait(3)

    recognizer = StubRecognizer(hook=block)
    instance = TranscriptionService(
        ASRConfig(provider="sensevoice", max_pending=2), recognizer)

    async def run():
        await instance.start()
        running = asyncio.create_task(instance.transcribe(wav_bytes(), "audio/wav", 500))
        assert await asyncio.to_thread(started.wait, 1)
        queued = asyncio.create_task(instance.transcribe(wav_bytes(), "audio/wav", 500))
        await asyncio.sleep(0)  # Let the second request submit before cancellation.
        for task in (queued, running):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(AudioError) as error:
                await instance.transcribe(wav_bytes(), "audio/wav", 500)
            assert error.value.code == "ASR_BUSY"
        release.set()
        await asyncio.wrap_future(instance._worker.submit(lambda: None))
        assert len(recognizer.calls) == 1
        recognizer.hook = None
        assert await instance.transcribe(wav_bytes(), "audio/wav", 500) == "没有。"

    try:
        asyncio.run(run())
    finally:
        release.set()
        instance.close()
