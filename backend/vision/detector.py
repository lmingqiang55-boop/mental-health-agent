"""Single-frame facial state extraction behind the VisionState contract."""

import io
import os
from threading import Lock

from backend.models.states import VisionState


class MockVisionDetector:
    """Offline placeholder. It never invents an observed facial state."""

    def analyze_frame(self, frame: bytes) -> VisionState:
        return VisionState(face_detected=False)


class EmotiEffLibVisionDetector:
    """Extract facial expression and valence/arousal from one image."""

    _emotion_names = {
        "anger": "angry", "contempt": "contempt", "disgust": "disgust",
        "fear": "fearful", "happiness": "happy", "neutral": "neutral",
        "sadness": "sad", "surprise": "surprised",
    }

    def __init__(self, model_name: str = "enet_b0_8_va_mtl",
                 engine: str = "onnx") -> None:
        try:
            import cv2
            from emotiefflib.facial_analysis import EmotiEffLibRecognizer
        except ImportError as exc:
            raise RuntimeError(
                "视觉模型依赖未安装，请执行 pip install -r requirements-vision.txt"
            ) from exc

        self._cv2 = cv2
        self._cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        if self._cascade.empty():
            raise RuntimeError("人脸检测模型加载失败")
        self._recognizer = EmotiEffLibRecognizer(engine=engine, model_name=model_name)
        self._model_name = model_name
        self._lock = Lock()

    def analyze_frame(self, frame: bytes) -> VisionState:
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(frame)) as image:
            rgb = np.asarray(image.convert("RGB"))

        # The cascade and recognizer are shared across requests.
        with self._lock:
            gray = self._cv2.cvtColor(rgb, self._cv2.COLOR_RGB2GRAY)
            faces = self._cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
            )
            if len(faces) == 0:
                return VisionState(face_detected=False)
            x, y, width, height = max(faces, key=lambda box: box[2] * box[3])
            face = rgb[y:y + height, x:x + width]
            emotions, scores = self._recognizer.predict_emotions(face, logits=False)

        if not emotions or len(scores) == 0:
            raise RuntimeError("视觉模型未返回有效结果")
        score_row = scores[0]
        emotion_count = 7 if "_7" in self._model_name else 8
        probabilities = score_row[:emotion_count]
        confidence = float(max(probabilities)) if len(probabilities) else None
        valence = arousal = None
        if "_mtl" in self._model_name and len(score_row) >= emotion_count + 2:
            valence = self._clip(float(score_row[-2]), -1.0, 1.0)
            arousal = self._clip((float(score_row[-1]) + 1.0) / 2.0, 0.0, 1.0)
        label = str(emotions[0]).lower()
        return VisionState(
            emotion=self._emotion_names.get(label, label),
            emotion_confidence=confidence,
            valence=valence,
            arousal=arousal,
            face_detected=True,
        )

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return round(max(low, min(high, value)), 4)


_detector: MockVisionDetector | EmotiEffLibVisionDetector | None = None
_detector_lock = Lock()


def get_detector() -> MockVisionDetector | EmotiEffLibVisionDetector:
    """Load the configured detector on first use; Mock needs no extra package."""
    global _detector
    with _detector_lock:
        if _detector is None:
            provider = os.getenv("VISION_PROVIDER", "mock").strip().lower()
            if provider == "mock":
                _detector = MockVisionDetector()
            elif provider == "emotiefflib":
                _detector = EmotiEffLibVisionDetector(
                    model_name=os.getenv("VISION_MODEL", "enet_b0_8_va_mtl"),
                    engine=os.getenv("VISION_ENGINE", "onnx"),
                )
            else:
                raise RuntimeError(f"未知视觉模型提供者: {provider}")
        return _detector
