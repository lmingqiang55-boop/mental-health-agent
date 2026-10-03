"""视觉检测器。

B 模块的内部实现，对外只输出 ``VisionState``。
A/C 不直接调用检测器，只通过 API 或对话流程读取 VisionState。

替换真实模型（OpenFace / MediaPipe / 自训练）时，实现 ``VisionDetector``
接口即可，不得修改 dialogue_manager / states 字段。
"""

import io
import os
import random
import math
from threading import RLock
from abc import ABC, abstractmethod
from typing import Any

from backend.models.states import VisionState


class VisionDetector(ABC):
    """视觉检测接口。帧的格式由具体实现决定，不暴露给 A/C。"""

    @abstractmethod
    def analyze_frame(self, frame: Any | None = None) -> VisionState:
        """处理一帧画面，输出句级 VisionState。"""


class MockVisionDetector(VisionDetector):
    """无摄像头时的 Mock 实现，返回稳定的示例状态。

    用于 A/C 并行开发和无摄像头环境测试，不会导致后端崩溃。
    """

    def __init__(self, face_detected: bool = True) -> None:
        self._face_detected = face_detected

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
        try:
            import cv2
            cascade_type = getattr(cv2, "CascadeClassifier", None)
            if cascade_type is None:
                raise RuntimeError("OpenCV 人脸检测不可用。")
            else:
                self._face_cascade = cascade_type(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
                if self._face_cascade.empty():
                    raise RuntimeError("OpenCV 人脸检测权重加载失败。")
        except ImportError:
            raise RuntimeError("OpenCV 未安装，请先激活项目环境，再执行 python -m pip install -r requirements.txt。")

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

    def _crop_largest_face(self, image):
        if self._face_cascade is None:
            raise RuntimeError("人脸检测不可用，不能将整张场景图作为人脸。")
        import cv2

        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48)
        )
        # Browser frames are commonly 640-960 px wide; retry with a smaller
        # minimum face size when the strict pass misses a face.
        if len(faces) == 0:
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.05, minNeighbors=3, minSize=(24, 24)
            )
        if len(faces) == 0:
            return None
        x, y, width, height = max(faces, key=lambda box: box[2] * box[3])
        pad_x = int(width * 0.15)
        pad_y = int(height * 0.15)
        left = max(0, x - pad_x)
        top = max(0, y - pad_y)
        right = min(image.shape[1], x + width + pad_x)
        bottom = min(image.shape[0], y + height + pad_y)
        return image[top:bottom, left:right]


_detector: VisionDetector | None = None
_detector_lock = RLock()


def get_detector() -> VisionDetector:
    """按 ``VISION_PROVIDER`` 返回检测器，默认是 Mock。"""
    global _detector
    with _detector_lock:
        if _detector is None:
            provider = os.getenv("VISION_PROVIDER", "mock").strip().lower()
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
