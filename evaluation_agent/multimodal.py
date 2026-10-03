# -*- coding: utf-8 -*-
"""上游 B 模块（视觉）产出的**两级**多模态状态。

字段名与取值范围对齐上游仓库 ``mental-health-agent`` 的
``backend/models/states.py``，目的是让上游的对象能近乎直接地喂进来，
而不是在这里再造一套字段名。

两级的分工是上游刻意的设计，不是我们的选择：

- **句级** :class:`VisionState` —— 挂在每条消息上的 ``vision_snapshot``，
  描述"学生说这句话的那一刻"的状态（效价、唤醒、注视、微表情……）；
- **会话级** :class:`SessionVisionSummary` —— 整段对话结束后由全部句级状态
  聚合而成（均值、逐句趋势、出现占比、采样数）。

**两者都要送进 Prompt，缺一不可**：只给会话级就看不出"趋势"（比如效价一直
在往下掉），只给句级就看不出"整体水平"。这也是之前那个自造的
``visual_summary: str`` 最根本的问题——它既没有句级也没有会话级，
只是一句没人负责的散文，却能把 ``psychomotor_change`` 从 0 抬到 1。

关于 `None`：上游的每个指标都可能是 `None`（没检测到人脸、模型不输出该指标），
所以这里全部可选。**`None` 不等于 0**——"没测到"和"测到是零"是两回事，
Prompt 里也按这个口径说明。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import (
    NonNegativeCount,
    SignedUnitFloat,
    UnitFloat,
    UpstreamSchemaBase,
)

__all__ = [
    "VisionState",
    "SessionVisionSummary",
    "VISION_STATE_FIELDS",
    "SESSION_VISION_SUMMARY_FIELDS",
]


class VisionState(UpstreamSchemaBase):
    """句级视觉状态：学生说某一句话时的瞬时视觉指标。

    对应上游 ``Message.vision_snapshot``。只保留评估用得上的字段语义，
    但字段名与上游完全一致。
    """

    emotion: str | None = Field(default=None, description="情绪类别，如 neutral/sad/happy")
    emotion_confidence: UnitFloat | None = Field(
        default=None, description="情绪识别置信度 0~1"
    )
    valence: SignedUnitFloat | None = Field(
        default=None, description="情绪效价：-1 极消极 ~ 1 极积极"
    )
    arousal: UnitFloat | None = Field(default=None, description="情绪唤醒度 0~1")
    engagement: UnitFloat | None = Field(default=None, description="参与度 0~1")
    attention_score: UnitFloat | None = Field(
        default=None, description="眼动注意力分布得分 0~1"
    )
    gaze_focus: UnitFloat | None = Field(default=None, description="注视点稳定度 0~1")
    micro_expression_intensity: UnitFloat | None = Field(
        default=None, description="微表情强度 0~1"
    )
    face_detected: bool = Field(default=False, description="该句是否检测到人脸")
    timestamp: datetime | None = Field(default=None, description="采样时间（本阶段不参与评估）")


class SessionVisionSummary(UpstreamSchemaBase):
    """会话级视觉汇总：整段对话结束时由全部句级状态聚合而成。

    对应上游 ``SessionState.vision_summary``。
    """

    dominant_emotion: str | None = Field(default=None, description="主导情绪类别")
    mean_valence: SignedUnitFloat | None = Field(
        default=None, description="平均效价 -1~1"
    )
    mean_arousal: UnitFloat | None = Field(default=None, description="平均唤醒度 0~1")
    mean_engagement: UnitFloat | None = Field(default=None, description="平均参与度 0~1")
    mean_attention: UnitFloat | None = Field(default=None, description="平均注意力 0~1")
    valence_trend: list[float] = Field(
        default_factory=list,
        description="逐句效价序列（按时间顺序），用于判断情绪走向",
    )
    face_present_ratio: UnitFloat | None = Field(
        default=None, description="句级视觉样本中有效人脸的比例 0~1"
    )
    sample_count: NonNegativeCount = Field(default=0, description="参与聚合的句级样本数")


#: 上游 ``VisionState`` 的字段清单。测试用它盯住"上游加了字段我们没跟上"。
VISION_STATE_FIELDS: frozenset[str] = frozenset(VisionState.model_fields)

#: 上游 ``SessionVisionSummary`` 的字段清单，同上。
SESSION_VISION_SUMMARY_FIELDS: frozenset[str] = frozenset(
    SessionVisionSummary.model_fields
)
