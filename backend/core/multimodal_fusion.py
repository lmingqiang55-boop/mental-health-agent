"""多模态融合（B 模块）。

两个职责：
1. ``fuse_turn``：句级融合，把当前轮的 vision/audio 状态整理给风险引擎和对话 Agent。
2. ``build_vision_summary`` / ``build_audio_summary``：会话级汇总，
   对话结束后聚合全部句级状态，供多模态综合评估 Agent 使用。

A/C 不直接调用视觉/音频模型，只读这里的融合结果。
"""

from pydantic import BaseModel

from backend.models.states import (
    AudioState,
    SessionAudioSummary,
    SessionVisionSummary,
    VisionState,
)


class FusedTurn(BaseModel):
    """单轮多模态融合结果。"""
    user_text: str
    vision_available: bool
    audio_available: bool
    # 直接透传句级状态，供风险/对话策略使用
    valence: float | None = None
    arousal: float | None = None
    engagement: float | None = None
    attention_score: float | None = None
    emotion: str | None = None
    energy: float | None = None
    speech_rate: float | None = None
    pause_ratio: float | None = None
    pitch_mean: float | None = None


def fuse_turn(user_text: str,
              vision_state: VisionState | None = None,
              audio_state: AudioState | None = None) -> FusedTurn:
    vision_ok = bool(vision_state and vision_state.face_detected)
    audio_ok = bool(audio_state and audio_state.audio_available)
    return FusedTurn(
        user_text=user_text,
        vision_available=vision_ok,
        audio_available=audio_ok,
        valence=vision_state.valence if vision_ok else None,
        arousal=vision_state.arousal if vision_ok else None,
        engagement=vision_state.engagement if vision_ok else None,
        attention_score=vision_state.attention_score if vision_ok else None,
        emotion=vision_state.emotion if vision_ok else None,
        energy=audio_state.energy if audio_ok else None,
        speech_rate=audio_state.speech_rate if audio_ok else None,
        pause_ratio=audio_state.pause_ratio if audio_ok else None,
        pitch_mean=audio_state.pitch_mean if audio_ok else None,
    )


def build_vision_summary(states: list[VisionState]) -> SessionVisionSummary:
    """聚合整段对话的句级视觉状态 → 会话级视觉汇总。"""
    valid = [s for s in states if s.face_detected]
    if not valid:
        return SessionVisionSummary(sample_count=len(states))

    def avg(values: list[float | None]) -> float | None:
        nums = [v for v in values if v is not None]
        return round(sum(nums) / len(nums), 3) if nums else None

    emotions = [s.emotion for s in valid if s.emotion]
    dominant = max(set(emotions), key=emotions.count) if emotions else None
    return SessionVisionSummary(
        dominant_emotion=dominant,
        mean_valence=avg([s.valence for s in valid]),
        mean_arousal=avg([s.arousal for s in valid]),
        mean_engagement=avg([s.engagement for s in valid]),
        mean_attention=avg([s.attention_score for s in valid]),
        valence_trend=[s.valence for s in valid if s.valence is not None],
        face_present_ratio=round(len(valid) / len(states), 3) if states else 0.0,
        sample_count=len(states),
    )


def build_audio_summary(states: list[AudioState]) -> SessionAudioSummary:
    """聚合整段对话的句级音频状态 → 会话级音频汇总。"""
    valid = [s for s in states if s.audio_available]
    if not valid:
        return SessionAudioSummary(sample_count=len(states))

    def avg(values: list[float | None]) -> float | None:
        nums = [v for v in values if v is not None]
        return round(sum(nums) / len(nums), 3) if nums else None

    return SessionAudioSummary(
        mean_speech_rate=avg([s.speech_rate for s in valid]),
        mean_pause_ratio=avg([s.pause_ratio for s in valid]),
        mean_energy=avg([s.energy for s in valid]),
        mean_pitch=avg([s.pitch_mean for s in valid]),
        energy_trend=[s.energy for s in valid if s.energy is not None],
        audio_present_ratio=round(len(valid) / len(states), 3) if states else 0.0,
        sample_count=len(states),
    )
