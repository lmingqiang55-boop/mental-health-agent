"""视觉检测器。

B 模块的内部实现，对外只输出 ``VisionState``。
A/C 不直接调用检测器，只通过 API 或对话流程读取 VisionState。

替换真实模型（OpenFace / MediaPipe / 自训练）时，实现 ``VisionDetector``
接口即可，不得修改 dialogue_manager / states 字段。
"""

import io
import logging
import os
import random
import math
from threading import RLock
from abc import ABC, abstractmethod
from typing import Any

from dotenv import load_dotenv

from backend.llm.config import DEFAULT_ENV_FILE
from backend.models.states import VisionState
from backend.vision.face_weights import create_face_detector

logger = logging.getLogger(__name__)


class VisionDetector(ABC):
    """视觉检测接口。帧的格式由具体实现决定，不暴露给 A/C。"""
    is_simulated = False

    @abstractmethod
    def analyze_frame(self, frame: Any | None = None) -> VisionState:
        """处理一帧画面，输出句级 VisionState。"""


class MockVisionDetector(VisionDetector):
    """无摄像头时的 Mock 实现，返回稳定的示例状态。

    用于 A/C 并行开发和无摄像头环境测试，不会导致后端崩溃。
    """

    def __init__(self, face_detected: bool = True) -> None:
        self._face_detected = face_detected

    is_simulated = True

    def analyze_frame(self, frame: Any | None = None) -> VisionState:
        if not self._face_detected:
            return VisionState(face_detected=False)
        return VisionState(
            emotion="neutral",
            emotion_confidence=0.78,
            valence=round(random.uniform(-0.2, 0.1), 2),
            arousal=round(random.uniform(0.25, 0.45), 2),
            engagement=round(random.uniform(0.55, 0.75), 2),
            attention_score=round(random.uniform(0.5, 0.7), 2),
            gaze_focus=round(random.uniform(0.5, 0.75), 2),
            micro_expression_intensity=round(random.uniform(0.1, 0.3), 2),
            face_detected=True,
        )


class EmotiEffLibVisionDetector(VisionDetector):
    """EmotiEffLib adapter; the dependency and model are loaded on demand."""

    _emotion_names = {
        "anger": "angry", "angry": "angry", "contempt": "contempt",
        "disgust": "disgust", "fear": "fearful", "happiness": "happy",
        "happy": "happy", "neutral": "neutral", "sadness": "sad",
        "sad": "sad", "surprise": "surprised",
    }

    def __init__(self, model_name: str = "enet_b0_8_va_mtl",
                 engine: str = "onnx") -> None:
        try:
            from emotiefflib.facial_analysis import EmotiEffLibRecognizer
        except ImportError as exc:
            raise RuntimeError(
                "EmotiEffLib 未安装，请先激活项目环境，再执行 python -m pip install -r requirements.txt"
            ) from exc
        self.model_name = model_name
        self._inference_lock = RLock()
        self._recognizer = EmotiEffLibRecognizer(engine=engine, model_name=model_name)
        # 人脸检测用 YuNet（见 backend.vision.face_weights）。换掉 Haar 的原因：
        # 它在暗光、侧脸、小脸场景漏检严重（同机实测暗光下 YuNet 187 张 vs
        # Haar 9 张），且不输出置信度、只能靠放宽 minNeighbors 硬凑，反而引入误检。
        #
        # YuNet 权重需要一次性联网下载，所以留一条降级路：拿不到权重时回退 Haar，
        # 保证离线机器上整条视觉链路仍然能起来。降级只在"YuNet 完全不可用"时发生，
        # 不做逐帧补检——实测 YuNet 全面优于 Haar，而在无脸帧上补一次 Haar 更可能
        # 带来误检，误检比漏检更脏（会把不存在的表情喂进一致性计算）。
        self._face_detector = None
        self._cascade = None
        try:
            self._face_detector = create_face_detector()
        except RuntimeError as exc:
            try:
                import cv2
            except ImportError as import_exc:
                # create_face_detector 会把"没装 OpenCV"也包成 RuntimeError；降级
                # 路径自己也要 import cv2，这里不兜住就会把那句引导报错盖成
                # ModuleNotFoundError，让排障的人以为只是某个可选依赖缺失。
                raise RuntimeError(
                    "OpenCV 未安装，请先激活项目环境，再执行 "
                    "python -m pip install -r requirements.txt"
                ) from import_exc
            logger.warning("YuNet 人脸检测不可用（%s），降级为 Haar 级联", exc)
            self._cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
            if self._cascade.empty():
                raise RuntimeError(f"人脸检测不可用，且 Haar 级联也加载失败：{exc}") from exc

    def analyze_frame(self, frame: Any | None = None) -> VisionState:
        # Haar cascade and lazy model state must not be shared concurrently.
        with self._inference_lock:
            return self._analyze_frame(frame)

    def _analyze_frame(self, frame: Any | None = None) -> VisionState:
        image = self._decode_frame(frame)
        if image is None:
            return VisionState(face_detected=False)
        face = self._crop_largest_face(image)
        if face is None:
            return VisionState(face_detected=False)
        emotions, scores = self._recognizer.predict_emotions(face, logits=False)
        emotion = emotions[0] if emotions else None
        scores = scores[0]
        emotion_count = 7 if "_7" in self.model_name else 8
        emotion_scores = scores[:emotion_count]
        confidence = float(max(emotion_scores)) if len(emotion_scores) else None
        valence = None
        arousal = None
        if "_mtl" in self.model_name and len(scores) >= emotion_count + 2:
            valence = self._clip(float(scores[-2]), -1.0, 1.0)
            arousal = self._clip((float(scores[-1]) + 1.0) / 2.0, 0.0, 1.0)
        # Engagement needs EmotiEffLib's 128-frame temporal window. Until that
        # pipeline exists, leave temporal and gaze metrics unavailable.
        return VisionState(
            emotion=self._emotion_names.get(str(emotion).lower(), str(emotion).lower())
            if emotion else None,
            emotion_confidence=confidence,
            valence=valence,
            arousal=arousal,
            engagement=None,
            attention_score=None,
            face_detected=True,
        )

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        if not math.isfinite(value):
            raise ValueError("视觉模型返回非有限数值。")
        return round(max(low, min(high, value)), 4)

    @staticmethod
    def _decode_frame(frame: Any | None):
        if frame is None:
            return None
        if not isinstance(frame, (bytes, bytearray)):
            return frame
        try:
            import numpy as np
            from PIL import Image

            with Image.open(io.BytesIO(frame)) as image:
                return np.asarray(image.convert("RGB"))
        except (OSError, ValueError):
            return None

    def _yunet_face_box(self, image, width, height):
        """YuNet 给出的最大人脸框 ``(x, y, w, h)``；没检出返回 ``None``。"""
        import cv2

        # YuNet 走 OpenCV 自带的 dnn，输入必须三通道 BGR：送灰度会报
        # "Number of input channels should be multiple of 3"，送 RGB 不报错但会
        # 静默丢掉大部分人脸。它也不按第一帧推断尺寸，每帧都要 setInputSize。
        self._face_detector.setInputSize((width, height))
        _, faces = self._face_detector.detect(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        # detect 的 retval 恒为 1，判断有没有检出只能看 faces 本身。
        if faces is None or len(faces) == 0:
            return None
        return tuple(
            int(round(value)) for value in
            max(faces, key=lambda face: face[2] * face[3])[:4]
        )

    def _haar_face_box(self, image):
        """降级路径：Haar 级联两档参数重试，取面积最大的框。"""
        import cv2

        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        for scale, neighbors, size in ((1.1, 5, (48, 48)), (1.05, 3, (24, 24))):
            boxes = self._cascade.detectMultiScale(
                gray, scaleFactor=scale, minNeighbors=neighbors, minSize=size)
            if len(boxes):
                return tuple(
                    int(value) for value in
                    max(boxes, key=lambda box: box[2] * box[3])
                )
        return None

    def _crop_largest_face(self, image):
        height, width = image.shape[:2]
        if self._face_detector is not None:
            box = self._yunet_face_box(image, width, height)
        elif self._cascade is not None:
            box = self._haar_face_box(image)
        else:
            raise RuntimeError("人脸检测不可用，不能将整张场景图作为人脸。")
        if box is None:
            return None
        x, y, box_width, box_height = box
        pad_x = int(box_width * 0.15)
        pad_y = int(box_height * 0.15)
        left = max(0, x - pad_x)
        top = max(0, y - pad_y)
        right = min(width, x + box_width + pad_x)
        bottom = min(height, y + box_height + pad_y)
        if right <= left or bottom <= top:
            return None
        return image[top:bottom, left:right]


_detector: VisionDetector | None = None
_detector_lock = RLock()


def real_vision_detector_active() -> bool:
    """Report the detector that actually produced frames, not only env settings."""
    with _detector_lock:
        return _detector is not None and not _detector.is_simulated


def describe_vision_status() -> dict:
    """Report configuration without downloading or initializing model weights."""
    load_dotenv(DEFAULT_ENV_FILE, override=False)
    configured = os.getenv("VISION_PROVIDER", "emotiefflib").strip().lower()
    with _detector_lock:
        if _detector is not None:
            provider = "mock" if _detector.is_simulated else (
                "emotiefflib" if isinstance(_detector, EmotiEffLibVisionDetector) else "custom")
            state = "simulated" if _detector.is_simulated else "ready"
        else:
            provider = configured
            state = "simulated" if configured == "mock" else "not_loaded"
        return {"provider": provider, "state": state,
                "real_analysis": state == "ready" and provider in {"emotiefflib", "custom"}}


def get_detector() -> VisionDetector:
    """按 ``VISION_PROVIDER`` 返回检测器，真实识别失败不会退回 Mock。"""
    global _detector
    with _detector_lock:
        if _detector is None:
            load_dotenv(DEFAULT_ENV_FILE, override=False)
            provider = os.getenv("VISION_PROVIDER", "emotiefflib").strip().lower()
            if provider == "emotiefflib":
                _detector = EmotiEffLibVisionDetector(
                    model_name=os.getenv("VISION_MODEL", "enet_b0_8_va_mtl"),
                    engine=os.getenv("VISION_ENGINE", "onnx"),
                )
            elif provider == "mock":
                _detector = MockVisionDetector()
            else:
                raise ValueError("Unsupported VISION_PROVIDER")
        return _detector


def set_detector(detector: VisionDetector) -> None:
    """注入自定义检测器（B 接入真实模型时使用）。"""
    global _detector
    with _detector_lock:
        _detector = detector
