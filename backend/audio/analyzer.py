"""音频分析器。

B 模块内部实现，对外只输出 ``AudioState``（含 ASR 文本与副语言特征）。
替换真实 ASR/声学模型时实现 ``AudioAnalyzer`` 接口即可。
"""

import random
from abc import ABC, abstractmethod
from typing import Any

from backend.models.states import AudioState


class AudioAnalyzer(ABC):
    @abstractmethod
    def analyze_audio(self, audio_chunk: Any | None = None,
                      text: str | None = None) -> AudioState:
        """处理一段音频，输出句级 AudioState。"""


class MockAudioAnalyzer(AudioAnalyzer):
    """无麦克风时的 Mock 实现。"""

    def __init__(self, audio_available: bool = True) -> None:
        self._audio_available = audio_available

    def analyze_audio(self, audio_chunk: Any | None = None,
                      text: str | None = None) -> AudioState:
        if not self._audio_available:
            return AudioState(audio_available=False)
        return AudioState(
            text=text,
            speech_rate=round(random.uniform(0.55, 0.8), 2),
            pause_ratio=round(random.uniform(0.2, 0.4), 2),
            energy=round(random.uniform(0.35, 0.55), 2),
            pitch_mean=round(random.uniform(0.4, 0.6), 2),
            pitch_variability=round(random.uniform(0.2, 0.4), 2),
            audio_available=True,
        )


_analyzer: AudioAnalyzer | None = None


def get_analyzer() -> AudioAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = MockAudioAnalyzer()
    return _analyzer


def set_analyzer(analyzer: AudioAnalyzer) -> None:
    global _analyzer
    _analyzer = analyzer
