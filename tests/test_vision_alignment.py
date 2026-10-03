"""Real API boundaries with controlled model output, not synthetic frame timestamps."""
import base64
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.api import vision
from backend.core.multimodal_fusion import build_vision_summary
from backend.core.session_manager import session_manager
from backend.main import app
from backend.models.states import VisionState, _now

client = TestClient(app)
image = BytesIO()
Image.new("RGB", (64, 64)).save(image, format="JPEG")
FRAME = base64.b64encode(image.getvalue()).decode()


@pytest.fixture
def detector(monkeypatch):
    class Controlled:
        state = VisionState(face_detected=True, valence=0.2)
        calls = 0

        def analyze_frame(self, frame):
            self.calls += 1
            return self.state.model_copy(deep=True)
    value = Controlled()
    monkeypatch.setattr(vision, "get_detector", lambda: value)
    return value


def session():
    return client.post("/api/session").json()["session_id"]


def capture(sid, cap="capture", generation=1, active=True):
    return client.post("/api/vision/capture", json={
        "session_id": sid, "capture_id": cap, "generation": generation, "active": active})


def frame(sid, at, cap="capture", frame_id=None):
    return client.post("/api/vision/frame", json={
        "session_id": sid, "image_base64": FRAME, "capture_id": cap,
        "frame_id": frame_id or str(uuid4()), "captured_at_ms": at})


def segment(sid, start=10, end=40, utterance="u1", cap="capture"):
    return client.post("/api/vision/segment", json={
        "session_id": sid, "utterance_id": utterance, "capture_id": cap,
        "start_ms": start, "end_ms": end})


def test_interval_boundaries_missing_values_and_capture_isolation(detector):
    sid = session()
    capture(sid, "other")
    frame(sid, 20, "other")
    capture(sid, generation=2)
    frame(sid, 9)
    detector.state = VisionState(face_detected=True, emotion="sad", valence=-1, arousal=0.2)
    frame(sid, 10)
    detector.state = VisionState(face_detected=True, emotion="sad", valence=0)
    frame(sid, 20)
    detector.state = VisionState(face_detected=False, valence=1)
    frame(sid, 30)
    frame(sid, 40)
    result = segment(sid).json()
    assert result["frame_count"] == 3 and result["valid_frame_count"] == 2
    assert result["vision_snapshot"]["valence"] == -0.5
    assert result["vision_snapshot"]["arousal"] == 0.2
    assert result["vision_snapshot"]["engagement"] is None
    assert result["vision_snapshot"]["emotion"] == "sad"
    assert segment(sid, 100, 200, "missing").json()["vision_snapshot"] is None
    no_face = segment(sid, 30, 40, "noface").json()["vision_snapshot"]
    assert no_face["face_detected"] is False and no_face["valence"] is None


def test_freeze_retry_late_frames_and_conflicting_interval(detector, policy_stub):
    policy_stub()
    sid = session()
    capture(sid)
    frame(sid, 20)
    original = segment(sid).json()
    detector.state = VisionState(face_detected=True, valence=-0.8)
    frame(sid, 30)
    assert segment(sid).json() == original
    assert segment(sid, end=41).status_code == 409
    body = {"session_id": sid, "utterance_id": "u1", "text": "最近还好",
            "vision_snapshot": original["vision_snapshot"], "speech": {
                "capture_id": "capture", "recording_start_ms": 10, "recording_end_ms": 40}}
    first = client.post("/api/chat", json=body)
    assert first.status_code == 200
    assert client.post("/api/chat", json=body).json() == first.json()
    changed = {**body, "vision_snapshot": {"face_detected": True, "valence": -0.8}}
    assert client.post("/api/chat", json=changed).status_code == 409


def test_frame_retry_and_conflict_do_not_double_count(detector):
    sid = session()
    capture(sid)
    original = frame(sid, 20, frame_id="frame1")
    assert frame(sid, 20, frame_id="frame1").json() == original.json()
    assert detector.calls == 1
    assert frame(sid, 21, frame_id="frame1").status_code == 409
    assert segment(sid).json()["frame_count"] == 1


def test_capture_generations_ignore_old_commands_and_reject_old_frames(detector):
    sid = session()
    capture(sid)
    frame(sid, 20)
    capture(sid, "new", 3)
    assert capture(sid, "capture", 2, False).json()["capture_id"] == "new"
    assert capture(sid, "capture", 1).json()["capture_id"] == "new"
    assert frame(sid, 30).status_code == 409
    assert frame(sid, 30, "new").status_code == 200
    assert capture(sid, "new", 3, False).status_code == 409
    capture(sid, "new", 4, False)
    assert frame(sid, 35, "new").status_code == 409
    assert client.get(f"/api/session/{sid}").json()["latest_vision_state"] is None


def test_closing_during_inference_does_not_repopulate_state(monkeypatch):
    sid = session()
    capture(sid)
    class Closing:
        def analyze_frame(self, raw):
            assert capture(sid, generation=2, active=False).status_code == 200
            return VisionState(face_detected=True, valence=-0.9)
    monkeypatch.setattr(vision, "get_detector", lambda: Closing())
    assert frame(sid, 20).status_code == 409
    state = client.get(f"/api/session/{sid}").json()
    assert state["latest_vision_state"] is None and state["vision_state_log"] == []


def test_unknown_session_is_checked_before_inference(detector):
    assert client.post("/api/vision/frame", json={
        "session_id": "missing", "image_base64": FRAME}).status_code == 404
    assert detector.calls == 0


@pytest.mark.parametrize("timing", [
    {"capture_id": "capture"},
    {"capture_id": "capture", "frame_id": "f", "captured_at_ms": "NaN"},
    {"capture_id": "capture", "frame_id": "f", "captured_at_ms": -1},
    {"capture_id": "capture", "frame_id": "f", "captured_at_ms": 1, "captured_time": 2},
])
def test_invalid_frame_timing_rejected(timing):
    assert client.post("/api/vision/frame", json={
        "session_id": session(), "image_base64": FRAME, **timing}).status_code == 422


def test_expired_or_explicitly_missing_vision_is_not_borrowed(policy_stub):
    policy_stub()
    sid = session()
    client.post("/api/vision", json={"session_id": sid, "state": {
        "face_detected": True, "valence": -0.9, "engagement": 0.1,
        "timestamp": (_now() - timedelta(seconds=10)).isoformat()}})
    assert client.post("/api/chat", json={"session_id": sid, "text": "还好"}).json()["risk"]["risk_score"] == 0.1
    client.post("/api/vision", json={"session_id": sid, "state": {
        "face_detected": True, "valence": -0.9, "engagement": 0.1, "timestamp": _now().isoformat()}})
    assert client.post("/api/chat", json={"session_id": sid, "text": "还好",
                                        "vision_snapshot": None}).json()["risk"]["risk_score"] == 0.1
    capture(sid, active=False)
    assert client.post("/api/chat", json={"session_id": sid, "text": "还好"}).json()["risk"]["risk_score"] == 0.1


@pytest.mark.parametrize("full", [False, True])
def test_bound_visuals_survive_assessment_and_summary_counts_turns(
        detector, policy_stub, evaluation_stub, full):
    policy_stub()
    sid = session()
    capture(sid)
    for number, valence in enumerate((-0.6, 0.2)):
        detector.state = VisionState(face_detected=True, valence=valence)
        start = number * 1000 + 10
        frame(sid, start + 1)
        frame(sid, start + 2)
        snap = segment(sid, start, start + 100, f"u{number}").json()["vision_snapshot"]
        assert client.post("/api/chat", json={"session_id": sid, "utterance_id": f"u{number}",
            "text": "最近睡不好", "vision_snapshot": snap}).status_code == 200
    history = client.get(f"/api/session/{sid}").json()["conversation_history"]
    body = {"session_id": sid}
    if full:
        body["evaluation_input"] = {"dialogue_history": [
            {"role": m["role"], "content": m["content"]} for m in history]}
    response = client.post("/api/assessment", json=body)
    assert response.status_code == 200, response.json()
    received = evaluation_stub.inputs[-1]
    assert received.dialogue_history[0].vision_snapshot.valence == -0.6
    assert received.vision_summary.sample_count == 2
    assert received.vision_summary.mean_valence == -0.2
    assert received.vision_summary.valence_trend == [-0.6, 0.2]
    assert client.get(f"/api/session/{sid}").json()["conversation_history"] == history


def test_assessment_cannot_rewrite_frozen_visuals(policy_stub, evaluation_stub):
    policy_stub()
    sid = session()
    client.post("/api/chat", json={"session_id": sid, "utterance_id": "u1", "text": "还好",
        "vision_snapshot": {"face_detected": True, "valence": -0.4}})
    history = client.get(f"/api/session/{sid}").json()["conversation_history"]
    history[0]["vision_snapshot"]["valence"] = 0.9
    response = client.post("/api/assessment", json={"session_id": sid,
        "evaluation_input": {"dialogue_history": history}})
    assert response.status_code == 409 and evaluation_stub.inputs == []


def test_frame_buffers_are_bounded(detector, monkeypatch):
    monkeypatch.setattr(vision, "MAX_FRAME_OBSERVATIONS", 3)
    sid = session()
    capture(sid)
    for at in range(5):
        frame(sid, at)
    stored = session_manager.get_session(sid)
    assert [f.captured_at_ms for f in stored.vision_frames] == [2, 3, 4]
    assert len(stored.vision_state_log) == 3


def test_no_face_samples_do_not_claim_visual_evidence_in_report(detector, policy_stub, evaluation_stub):
    policy_stub()
    sid = session()
    capture(sid)
    detector.state = VisionState(face_detected=False)
    frame(sid, 20)
    snapshot = segment(sid).json()["vision_snapshot"]
    assert client.post("/api/chat", json={"session_id": sid, "utterance_id": "u1",
        "text": "最近睡不好", "vision_snapshot": snapshot}).status_code == 200
    assessed = client.post("/api/assessment", json={"session_id": sid})
    assert assessed.status_code == 200
    assert "没有可用的视觉信息" in assessed.json()["result"]["report"]["multimodal_observation"]["summary"]
    assert evaluation_stub.inputs[0].vision_summary.mean_valence is None
    assert evaluation_stub.inputs[0].vision_summary.face_present_ratio == 0.0
    assert evaluation_stub.inputs[0].vision_summary.sample_count == 1


def test_empty_visual_summary_keeps_face_ratio_missing():
    summary = build_vision_summary([])
    assert summary.sample_count == 0
    assert summary.face_present_ratio is None
    assert summary.mean_valence is None


@pytest.mark.parametrize("summary_field", [{}, {"vision_summary": None}])
def test_replacing_history_without_vision_clears_previous_summary(evaluation_stub, summary_field):
    sid = session()
    first = client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": "第一段对话"}],
        "vision_summary": {"mean_valence": -0.8, "face_present_ratio": 1.0, "sample_count": 1},
    }})
    assert first.status_code == 200
    second = client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": "没有视觉的另一段对话"}],
        **summary_field,
    }})
    assert second.status_code == 200
    assert evaluation_stub.inputs[-1].vision_summary is None
    assert evaluation_stub.inputs[-1].dialogue_history[0].vision_snapshot is None
    assert client.get(f"/api/session/{sid}").json()["vision_summary"] is None
    assert "没有可用的视觉信息" in second.json()["result"]["report"]["multimodal_observation"]["summary"]


@pytest.mark.parametrize("full_input", [False, True])
def test_unchanged_history_keeps_explicit_upstream_summary(evaluation_stub, full_input):
    sid = session()
    history = [{"role": "user", "content": "同一段对话"}]
    assert client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": history,
        "vision_summary": {"mean_valence": -0.8, "face_present_ratio": 1.0, "sample_count": 1},
    }}).status_code == 200
    body = {"session_id": sid}
    if full_input:
        body["evaluation_input"] = {"dialogue_history": history}
    assert client.post("/api/assessment", json=body).status_code == 200
    assert evaluation_stub.inputs[-1].vision_summary.mean_valence == -0.8


def test_replacing_history_rebuilds_summary_from_new_snapshots(evaluation_stub):
    sid = session()
    assert client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": "旧对话"}],
        "vision_summary": {"mean_valence": -0.8, "sample_count": 10},
    }}).status_code == 200
    response = client.post("/api/assessment", json={"session_id": sid, "evaluation_input": {
        "dialogue_history": [{"role": "user", "content": "新对话",
            "vision_snapshot": {"face_detected": True, "valence": 0.4}}],
    }})
    assert response.status_code == 200
    summary = evaluation_stub.inputs[-1].vision_summary
    assert summary.mean_valence == 0.4 and summary.sample_count == 1
    assert summary.face_present_ratio == 1.0
