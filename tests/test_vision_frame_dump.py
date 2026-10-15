"""视觉片段落盘开关：默认关，打开后一个片段一行，重复冻结不写两遍。

这是给阈值重校留的数据口子（见 ``backend.core.vision_thresholds`` 的模块说明），
不是产品功能，所以默认必须完全不生效、写坏了也不能影响对话。
"""

import base64
import json
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.api import vision
from backend.core.vision_frame_dump import DUMP_DIR_ENV, dump_dir
from backend.main import app
from backend.models.states import VisionState

client = TestClient(app)
image = BytesIO()
Image.new("RGB", (64, 64)).save(image, format="JPEG")
FRAME = base64.b64encode(image.getvalue()).decode()


@pytest.fixture
def detector(monkeypatch):
    """固定输出的检测器，与 tests/test_vision_alignment.py 同一套做法。"""

    class Controlled:
        # 没有这个标记时 API 会把帧记成 mock（见 api/vision.py 里对 is_simulated
        # 的判断），而重校只看真实来源的帧，所以这里要装成真实检测器。
        is_simulated = False
        state = VisionState(face_detected=True, emotion="sad",
                            emotion_confidence=0.72, valence=-0.31)

        def analyze_frame(self, frame):
            return self.state.model_copy(deep=True)

    value = Controlled()
    monkeypatch.setattr(vision, "get_detector", lambda: value)
    return value


def session():
    return client.post("/api/session").json()["session_id"]


def frame(sid, at, cap="capture"):
    return client.post("/api/vision/frame", json={
        "session_id": sid, "image_base64": FRAME, "capture_id": cap,
        "frame_id": str(uuid4()), "captured_at_ms": at})


def segment(sid, start=10, end=40, utterance="u1", cap="capture"):
    return client.post("/api/vision/segment", json={
        "session_id": sid, "utterance_id": utterance, "capture_id": cap,
        "start_ms": start, "end_ms": end})


def prepare(sid):
    client.post("/api/vision/capture", json={
        "session_id": sid, "capture_id": "capture", "generation": 1, "active": True})
    frame(sid, 20)
    frame(sid, 30)


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_nothing_is_written_while_the_switch_is_off(detector, tmp_path, monkeypatch):
    """没设目录就是彻底不生效——连目录都不该被建出来。"""

    monkeypatch.delenv(DUMP_DIR_ENV, raising=False)
    assert dump_dir() is None
    sid = session()
    prepare(sid)
    assert segment(sid).status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_each_frozen_segment_becomes_one_line_with_its_frames(
        detector, tmp_path, monkeypatch):
    """打开后，一行一个片段，帧里带着重校真正要看的那些字段。"""

    monkeypatch.setenv(DUMP_DIR_ENV, str(tmp_path / "dump"))
    sid = session()
    prepare(sid)
    assert segment(sid).status_code == 200

    files = list((tmp_path / "dump").glob("*.jsonl"))
    assert len(files) == 1
    records = lines(files[0])
    assert len(records) == 1

    record = records[0]
    assert record["session_id"] == sid
    assert record["utterance_id"] == "u1"
    assert record["capture_id"] == "capture"
    assert record["start_ms"] == 10 and record["end_ms"] == 40
    assert record["frame_count"] == 2 and record["valid_frame_count"] == 2
    assert record["snapshot"]["valence"] == -0.31
    assert len(record["frames"]) == 2
    for item in record["frames"]:
        assert item["source"] == "real"
        assert item["state"]["emotion"] == "sad"
        assert item["state"]["emotion_confidence"] == 0.72
        assert item["state"]["valence"] == -0.31
        # 时间戳不进文件：重校只看片段内的相对位置。
        assert "timestamp" not in item["state"]


def test_refreezing_the_same_window_does_not_write_twice(
        detector, tmp_path, monkeypatch):
    """客户端重试会把同一个区间再冻一次，落盘只该有一条。"""

    monkeypatch.setenv(DUMP_DIR_ENV, str(tmp_path / "dump"))
    sid = session()
    prepare(sid)
    assert segment(sid).status_code == 200
    assert segment(sid).status_code == 200

    files = list((tmp_path / "dump").glob("*.jsonl"))
    assert len(lines(files[0])) == 1


def test_a_broken_dump_directory_never_breaks_the_dialogue(
        detector, tmp_path, monkeypatch):
    """目录建不出来时只记日志：真实对话不能因为校准数据写不下去而失败。"""

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv(DUMP_DIR_ENV, str(blocker / "dump"))

    sid = session()
    prepare(sid)
    assert segment(sid).status_code == 200
