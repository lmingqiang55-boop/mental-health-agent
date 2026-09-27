from backend.models.states import RiskResult


HIGH_SIGNALS = ("想自杀", "我要自杀", "不想活了", "结束生命", "伤害自己", "自残", "suicide", "kill myself")
MEDIUM_SIGNALS = ("绝望", "活着没意思", "撑不下去", "崩溃", "hopeless")


def assess_risk(text: str) -> RiskResult:
    """Demo keyword prompt only; it is not a clinical risk assessment."""
    lowered = text.lower()
    if any(term in lowered for term in HIGH_SIGNALS):
        return RiskResult(risk_level="high", risk_score=0.9,
                          risk_reasons=["检测到明确的自伤相关表述"], requires_intervention=True)
    if any(term in lowered for term in MEDIUM_SIGNALS):
        return RiskResult(risk_level="medium", risk_score=0.5,
                          risk_reasons=["检测到值得进一步关注的表述"])
    return RiskResult(risk_level="low", risk_score=0.1)
