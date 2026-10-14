"""YuNet 权重的获取与加载。

这些用例不下载、不联网，也不加载 EmotiEffLib 的情绪模型——只盯住三件事：
权重校验、非 ASCII 路径下能创建检测器、没人脸时如实返回 None。
"""

import numpy as np
import pytest

from backend.vision import face_weights
from backend.vision.detector import EmotiEffLibVisionDetector


@pytest.fixture(scope="module")
def yunet():
    cv2 = pytest.importorskip("cv2")
    if not hasattr(cv2, "FaceDetectorYN"):
        pytest.skip("当前 OpenCV 没有 FaceDetectorYN")
    if face_weights.sha256_of(face_weights.default_weights_path()) != face_weights.YUNET_SHA256:
        pytest.skip("本机没有 YuNet 权重；用例不做网络请求")
    return face_weights.create_face_detector()


@pytest.fixture
def detector(yunet):
    """绕过 __init__：只装人脸检测器，不构造 EmotiEffLib 识别器。"""
    instance = object.__new__(EmotiEffLibVisionDetector)
    instance._face_detector = yunet
    instance._cascade = None
    return instance


def test_broken_weights_are_rejected(tmp_path, monkeypatch):
    """半截的下载比没有权重更危险，存在也要校验。"""
    broken = tmp_path / face_weights.YUNET_FILENAME
    broken.write_bytes(b"not an onnx file")
    monkeypatch.setenv("VISION_YUNET_MODEL", str(broken))
    with pytest.raises(RuntimeError, match="缺少 YuNet 权重"):
        face_weights.ensure_yunet_weights(allow_download=False)


def test_lfs_pointer_is_recognized():
    """raw.githubusercontent.com 对 LFS 文件只回 131 字节指针文本。"""
    pointer = (
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4\n"
    )
    assert face_weights._looks_like_lfs_pointer(pointer)
    assert not face_weights._looks_like_lfs_pointer(b"\x08\x01onnx-bytes")


def test_default_weights_path_follows_env(tmp_path, monkeypatch):
    override = tmp_path / "custom.onnx"
    monkeypatch.setenv("VISION_YUNET_MODEL", str(override))
    assert face_weights.default_weights_path() == override


def test_detector_loads_from_non_ascii_path(yunet):
    """本项目目录含中文，OpenCV 的窄字符 fopen 打不开 onnx；buffer 加载必须可用。"""
    assert yunet is not None


def test_crop_returns_none_when_no_face(detector):
    """detect 的 retval 恒为 1，不能用它判断有没有脸。"""
    blank = np.zeros((240, 320, 3), dtype=np.uint8)
    assert detector._crop_largest_face(blank) is None


def test_detector_degrades_to_haar_without_weights(monkeypatch):
    """拿不到 YuNet 权重（离线机器）时，不该让整条视觉链路起不来。"""
    cv2 = pytest.importorskip("cv2")
    import emotiefflib.facial_analysis as facial_analysis

    def _no_weights(**kwargs):
        raise RuntimeError("缺少 YuNet 权重")

    monkeypatch.setattr("backend.vision.detector.create_face_detector", _no_weights)
    monkeypatch.setattr(facial_analysis, "EmotiEffLibRecognizer", lambda **kwargs: object())

    instance = EmotiEffLibVisionDetector()
    assert instance._face_detector is None
    assert not instance._cascade.empty()
    blank = np.zeros((240, 320, 3), dtype=np.uint8)
    assert instance._crop_largest_face(blank) is None


def test_missing_opencv_keeps_the_setup_hint(monkeypatch):
    """没装 OpenCV 时，降级路径自己的 import 不能把引导报错盖成 ModuleNotFoundError。"""
    import sys

    import emotiefflib.facial_analysis as facial_analysis

    def _no_opencv(**kwargs):
        raise RuntimeError("OpenCV 未安装")

    monkeypatch.setattr("backend.vision.detector.create_face_detector", _no_opencv)
    monkeypatch.setattr(facial_analysis, "EmotiEffLibRecognizer", lambda **kwargs: object())
    # sys.modules 里放 None 会让随后的 ``import cv2`` 抛 ImportError。
    monkeypatch.setitem(sys.modules, "cv2", None)

    with pytest.raises(RuntimeError, match="请先激活项目环境"):
        EmotiEffLibVisionDetector()


def test_haar_fallback_retries_then_crops_the_largest_box():
    """降级路径保留原来的两档重试与 15% padding。"""
    pytest.importorskip("cv2")
    instance = object.__new__(EmotiEffLibVisionDetector)
    instance._face_detector = None

    class Cascade:
        def __init__(self):
            self.calls = []

        def detectMultiScale(self, gray, **kwargs):
            self.calls.append((kwargs["scaleFactor"], kwargs["minNeighbors"]))
            if len(self.calls) == 1:
                return np.empty((0, 4), dtype=int)
            return np.array([[1, 2, 10, 10], [30, 40, 60, 80]])

        def empty(self):
            return False

    instance._cascade = Cascade()
    crop = instance._crop_largest_face(np.zeros((200, 200, 3), dtype=np.uint8))
    assert instance._cascade.calls == [(1.1, 5), (1.05, 3)]
    # 取面积最大的框 (30, 40, 60, 80)，四边各加 15% padding。
    assert crop.shape == (104, 78, 3)
