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
from conftest import create_consented_session
from PIL import Image

from backend.api import vision
from backend.core import vision_frame_dump
from backend.core.session_manager import session_manager
from backend.core.vision_frame_dump import DUMP_DIR_ENV, dump_dir
from backend.vision import detector as detector_module
from backend.vision.detector import describe_loaded_vision_detector
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
    return create_consented_session(client)


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


def test_a_serialization_failure_never_breaks_the_dialogue(
        detector, tmp_path, monkeypatch):
    """抛的不是 OSError 也不能把对话带崩。

    只兜 OSError 时，"写盘失败绝不影响一次真实对话"是句空话：模型将来多一个
    datetime / enum 字段，json.dumps 就会抛 TypeError。
    """

    monkeypatch.setenv(DUMP_DIR_ENV, str(tmp_path / "dump"))
    monkeypatch.setattr(vision_frame_dump, "_serialize",
                        lambda payload: (_ for _ in ()).throw(TypeError("不能序列化")))

    sid = session()
    prepare(sid)
    assert segment(sid).status_code == 200
    assert not list((tmp_path / "dump").glob("*.jsonl"))


def test_a_payload_build_failure_never_breaks_the_dialogue(
        detector, tmp_path, monkeypatch):
    """构造那一行内容时抛错，也不能把对话带崩。

    兜底原先只包住"序列化 + 写文件"，payload 的构造在 try 之外；而调用点
    （/api/vision/segment）不包异常，于是构造一旦抛错就是一次 500，
    "任何失败都不该让一次真实对话失败"就成了空话。这里让描述检测器那条路抛错。
    """

    monkeypatch.setenv(DUMP_DIR_ENV, str(tmp_path / "dump"))
    monkeypatch.setattr(vision_frame_dump, "describe_loaded_vision_detector",
                        lambda: (_ for _ in ()).throw(RuntimeError("描述炸了")))

    sid = session()
    prepare(sid)
    assert segment(sid).status_code == 200
    assert not list((tmp_path / "dump").glob("*.jsonl"))


def test_the_dump_records_which_chain_produced_it(detector, tmp_path, monkeypatch):
    """每行都要带来源字段：不同 provider / 模型 / 人脸检测后端不能混着算分位数。

    这里注入的假检测器没走检测器单例（测试直接替换了 ``vision.get_detector``），
    所以字段是空的——真实链路上每个片段落盘前都至少取过一帧，单例早就加载好了。
    """

    monkeypatch.setenv(DUMP_DIR_ENV, str(tmp_path / "dump"))

    sid = session()
    prepare(sid)
    assert segment(sid).status_code == 200

    record = lines(list((tmp_path / "dump").glob("*.jsonl"))[0])[0]
    assert isinstance(record["detector"], dict)


def test_loaded_detector_description_is_honest_and_never_loads(monkeypatch):
    """没加载过就说"不知道"；加载过就报模型与人脸检测后端；describe 抛错也不能炸。"""

    monkeypatch.setattr(detector_module, "_detector", None)
    assert describe_loaded_vision_detector() == {}

    class Described:
        is_simulated = False

        def describe(self):
            return {"provider": "emotiefflib", "model": "enet_b0_8_va_mtl",
                    "face_detector": "haar"}

    monkeypatch.setattr(detector_module, "_detector", Described())
    assert describe_loaded_vision_detector() == {
        "provider": "emotiefflib", "model": "enet_b0_8_va_mtl", "face_detector": "haar"}

    class Broken:
        is_simulated = False

        def describe(self):
            raise RuntimeError("描述炸了")

    monkeypatch.setattr(detector_module, "_detector", Broken())
    assert describe_loaded_vision_detector() == {"provider": "custom"}


def test_the_dump_does_not_run_inside_the_session_lock(
        detector, tmp_path, monkeypatch):
    """写盘必须在会话锁之外。

    落盘会真的写磁盘；留在 session_manager 的全局锁里，一次慢写（网络盘、杀软扫描）
    就会把所有会话的对话卡住。这条用 RLock 的持有状态钉住调用点。
    """

    monkeypatch.setenv(DUMP_DIR_ENV, str(tmp_path / "dump"))
    lock = session_manager._lock
    is_owned = getattr(lock, "_is_owned", None)
    if is_owned is None:  # pragma: no cover - 非 CPython 实现上跳过这条断言
        pytest.skip("当前解释器的 RLock 不暴露持有状态")

    seen: list[bool] = []
    original = vision_frame_dump.dump_segment

    def spy(session_id, utterance_id, seg):
        seen.append(bool(is_owned()))
        return original(session_id, utterance_id, seg)

    monkeypatch.setattr(vision, "dump_segment", spy)

    sid = session()
    prepare(sid)
    assert segment(sid).status_code == 200
    assert seen == [False]
