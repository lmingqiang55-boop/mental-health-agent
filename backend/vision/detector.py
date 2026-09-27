"""视觉检测器。

B 模块的内部实现，对外只输出 ``VisionState``。
A/C 不直接调用检测器，只通过 API 或对话流程读取 VisionState。

替换真实模型（OpenFace / MediaPipe / 自训练）时，实现 ``VisionDetector``
接口即可，不得修改 dialogue_manager / states 字段。
"""

import random
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


_detector: VisionDetector | None = None


def get_detector() -> VisionDetector:
    """返回当前视觉检测器实例（框架阶段使用 Mock）。"""
    global _detector
    if _detector is None:
        _detector = MockVisionDetector()
    return _detector


def set_detector(detector: VisionDetector) -> None:
    """注入自定义检测器（B 接入真实模型时使用）。"""
    global _detector
    _detector = detector
