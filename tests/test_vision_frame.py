import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from backend.api import vision as vision_api
from backend.main import app
from backend.models.states import VisionState


client = TestClient(app)


def _frame(size: tuple[int, int] = (32, 32), format: str = "JPEG") -> str:
    output = BytesIO()
    Image.new("RGB", size, color=(120, 140, 160)).save(output, format=format)
    return base64.b64encode(output.getvalue()).decode()


def _session_id() -> str:
    return client.post("/api/session").json()["session_id"]


def test_frame_returns_facial_state_and_clears_it_when_no_face(monkeypatch) -> None:
    class SequenceDetector:
        def __init__(self) -> None:
            self.states = iter([
                VisionState(emotion="sad", emotion_confidence=0.8,
                            valence=-0.4, arousal=0.3, face_detected=True),
                VisionState(face_detected=False),
            ])

        def analyze_frame(self, frame: bytes) -> VisionState:
            assert frame.startswith(b"\xff\xd8")
            return next(self.states)

    # Keep one detector instance so the second frame represents the next snapshot.
    detector = SequenceDetector()
    monkeypatch.setattr(vision_api, "get_detector", lambda: detector)
    session_id = _session_id()
    payload = {"session_id": session_id, "speech_segment_id": "utterance-1",
               "image_base64": "data:image/jpeg;base64," + _frame()}

    first = client.post("/api/vision/frame", json=payload)
    assert first.status_code == 200
    assert first.json()["vision_state"]["emotion"] == "sad"
    assert first.json()["vision_state"]["face_detected"] is True
    assert first.json()["speech_segment_id"] == "utterance-1"

    second = client.post("/api/vision/frame", json=payload)
    assert second.status_code == 200
    state = second.json()["vision_state"]
    assert state["face_detected"] is False
    assert state["emotion"] is None
    assert client.get(f"/api/session/{session_id}").json()["latest_vision_state"] == state


def test_frame_rejects_invalid_image_and_preserves_session() -> None:
    session_id = _session_id()
    for image_base64 in (
        "!" * 40,
        base64.b64encode(b"not an image" * 5).decode(),
        _frame((1921, 1080)),
        "data:image/gif;base64," + _frame(),
    ):
        response = client.post("/api/vision/frame", json={
            "session_id": session_id, "image_base64": image_base64,
        })
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_FRAME"
    assert client.get(f"/api/session/{session_id}").json()["latest_vision_state"] is None


def test_frame_checks_session_before_detector(monkeypatch) -> None:
    def unexpected_detector():
        raise AssertionError("model must not load for an unknown session")

    monkeypatch.setattr(vision_api, "get_detector", unexpected_detector)
    response = client.post("/api/vision/frame", json={
        "session_id": "missing", "image_base64": _frame(),
    })
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_frame_reports_unavailable_model(monkeypatch) -> None:
    def unavailable_detector():
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(vision_api, "get_detector", unavailable_detector)
    session_id = _session_id()
    response = client.post("/api/vision/frame", json={
        "session_id": session_id, "image_base64": _frame(),
    })
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VISION_UNAVAILABLE"
    assert client.get(f"/api/session/{session_id}").json()["latest_vision_state"] is None
