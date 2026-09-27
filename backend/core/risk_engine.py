"""风险识别引擎（A 模块）。

框架阶段为规则式 Demo，不是临床风险评估：
1. 文本关键词匹配，带简单否定词窗口，避免「我不想自杀」误判。
2. 多模态信号（效价、能量、停顿等）作为辅助调整。
真实模型/量表接入时保持 ``assess_risk`` 接口。
"""

from backend.core.multimodal_fusion import FusedTurn
from backend.models.enums import RiskLevel
from backend.models.states import RiskResult

HIGH_SIGNALS = (
    "想自杀", "要自杀", "不想活了", "结束生命", "伤害自己", "自残",
    "活不下去", "去死", "suicide", "kill myself",
)
MEDIUM_SIGNALS = (
    "绝望", "活着没意思", "撑不下去", "崩溃", "没有希望", "没意义",
    "hopeless",
)
NEGATORS = ("不", "没有", "没", "别", "从未", "从来没", "不会")
NEGATION_WINDOW = 4  # 关键词前 N 个字符内出现否定词则视为否定


def _has_signal(text: str, signals: tuple[str, ...]) -> str | None:
    """返回命中的信号词；若被否定词修饰则返回 None。"""
    lowered = text.lower()
    for signal in signals:
        idx = lowered.find(signal)
        while idx != -1:
            window = lowered[max(0, idx - NEGATION_WINDOW):idx]
            if not any(neg in window for neg in NEGATORS):
                return signal
            idx = lowered.find(signal, idx + 1)
    return None


def assess_risk(fused: FusedTurn) -> RiskResult:
    """基于文本 + 多模态融合结果给出初步风险提示。"""
    text = fused.user_text
    high_hit = _has_signal(text, HIGH_SIGNALS)
    medium_hit = _has_signal(text, MEDIUM_SIGNALS)

    # 多模态困扰信号计数（仅作辅助，不单独触发高危）
    multimodal_concerns: list[str] = []
    if fused.valence is not None and fused.valence <= -0.5:
        multimodal_concerns.append(f"视觉效价偏低({fused.valence})")
    if fused.energy is not None and fused.energy <= 0.25:
        multimodal_concerns.append(f"语音能量偏低({fused.energy})")
    if fused.pause_ratio is not None and fused.pause_ratio >= 0.5:
        multimodal_concerns.append(f"停顿占比偏高({fused.pause_ratio})")
    if fused.engagement is not None and fused.engagement <= 0.3:
        multimodal_concerns.append(f"参与度偏低({fused.engagement})")

    if high_hit:
        return RiskResult(
            risk_level=RiskLevel.HIGH, risk_score=0.9,
            risk_reasons=["检测到明确的自伤相关表述"],
            risk_types=["自伤倾向"],
            key_evidence=[high_hit],
            requires_intervention=True,
        )

    if medium_hit:
        result = RiskResult(
            risk_level=RiskLevel.MEDIUM, risk_score=0.5,
            risk_reasons=["检测到值得进一步关注的表述"],
            key_evidence=[medium_hit],
        )
        if multimodal_concerns:
            result.risk_score = min(0.75, result.risk_score + 0.1)
            result.risk_reasons.append("多模态状态与文字表述一致偏低")
            result.key_evidence.extend(multimodal_concerns)
        return result

    if len(multimodal_concerns) >= 2:
        return RiskResult(
            risk_level=RiskLevel.MEDIUM, risk_score=0.4,
            risk_reasons=["多模态状态显示多项偏低，建议进一步关注"],
            key_evidence=multimodal_concerns,
        )

    score = 0.1
    if multimodal_concerns:
        score = 0.2
    return RiskResult(risk_level=RiskLevel.LOW, risk_score=score,
                      key_evidence=multimodal_concerns)
