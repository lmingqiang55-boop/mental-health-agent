"""把已计算的评估分数整理为面向页面的初步报告。"""

from datetime import datetime

from evaluation_agent.inputs import EvaluationInput
from evaluation_agent.rubric import RUBRIC_BY_ITEM
from evaluation_agent.schemas import (
    AssessmentItemScores,
    DIMENSION_LABELS,
    DIMENSIONS,
    SCHEMA_VERSION,
    ConsistencyLevel,
    EvaluationMetadata,
    EvaluationOutput,
    KeyFinding,
    MultimodalObservation,
    OverallLevel,
    OverallStatus,
    PrimaryConcern,
    PsychologicalDimension,
    PsychologicalProfile,
    TrendAndSuggestions,
    TrendDirection,
)
from evaluation_agent.scoring import DIMENSION_ITEMS, get_level_label_zh

from backend.models.enums import RiskLevel
from backend.models.states import RiskResult


_SUGGESTIONS = {
    "emotion": "可以把最近的情绪变化告诉一位信任的成年人或学校心理老师。",
    "interest_motivation": "可以和信任的人聊聊最近哪些活动变得难以投入，以及这对生活的影响。",
    "sleep_energy": "可以记录几天的睡眠与白天精力变化，再和信任的成年人讨论。",
    "attention_thinking": "可以留意专注困难主要出现在哪些场景，并和老师讨论需要的支持。",
    "social_daily": "可以和信任的成年人谈谈学习、同伴相处或日常活动中的具体困难。",
}


def build_report(
    *,
    assessment_id: str,
    profile: PsychologicalProfile,
    concern_index: int,
    overall_level: OverallLevel,
    input_data: EvaluationInput,
    risk: RiskResult,
    generated_at: datetime,
    item_scores: AssessmentItemScores | None = None,
) -> EvaluationOutput:
    """生成可展示的报告；没有纵向证据时如实标为趋势不明确。"""
    values = profile.model_dump()
    ranked = sorted(DIMENSIONS, key=lambda key: values[key], reverse=True)
    primary = ranked[0]
    primary_label = DIMENSION_LABELS[primary]

    urgent_risk = risk.requires_intervention or risk.risk_level == RiskLevel.HIGH
    if urgent_risk:
        summary = (
            "本次对话出现需要立即关注的安全风险信号；请优先寻求身边可信任的"
            "成年人和专业帮助。五维关注指数不能替代安全风险判断。"
        )
        primary_description = (
            "安全风险由独立模块提示；五维结果仅供后续沟通参考，"
            f"其中{primary_label}是当前分数最高的方面。"
        )
    elif concern_index == 0 and risk.risk_level == RiskLevel.MEDIUM:
        summary = (
            "五维关注指数较低，但对话中仍出现值得进一步关注的表述；"
            "请同时查看独立的风险提示。"
        )
        primary_description = "五个维度都没有明确的关注信号，暂以情绪状态作为继续沟通的起点。"
    elif concern_index == 0:
        summary = "本次对话中暂未识别到明显的关注信号；一次对话的信息可能有限。"
        primary_description = "五个维度都没有明确的关注信号，暂以情绪状态作为继续沟通的起点。"
    else:
        summary = (
            f"本次初步筛查显示“{get_level_label_zh(overall_level)}”。"
            f"{primary_label}方面的线索相对更突出，可进一步了解具体情况。"
        )
        primary_description = (
            f"{primary_label}在五个维度中的关注分数最高（{values[primary]}/100），"
            "适合作为后续沟通时优先了解的方面。"
        )

    findings = []
    if urgent_risk:
        findings.append(KeyFinding(
            title="安全提示",
            description="对话中出现需要及时关注的安全风险表述，应优先联系可信任的成年人。",
        ))
    for key in ranked[:2]:
        label = DIMENSION_LABELS[key]
        score = values[key]
        item_label = label
        if item_scores is not None and score > 0:
            items = DIMENSION_ITEMS[PsychologicalDimension(key)]
            strongest = max(items, key=lambda item: getattr(item_scores, item))
            if getattr(item_scores, strongest) > 0:
                item_label = RUBRIC_BY_ITEM[strongest].label_zh
        description = (
            f"本次对话在{item_label}方面有值得继续了解的线索；"
            "这个分数只反映当前对话，不代表诊断。"
            if score > 0 else
            f"本次对话没有提供足够的{label}相关线索，不能据此排除困扰。"
        )
        findings.append(KeyFinding(title=item_label, description=description))

    has_vision = any(
        message.vision_snapshot is not None
        and message.vision_snapshot.face_detected
        for message in input_data.dialogue_history
    ) or bool(
        input_data.vision_summary is not None
        and input_data.vision_summary.sample_count > 0
    )
    multimodal_summary = (
        "本次提供了与对话相关的视觉数据；视觉线索只作辅助，"
        "当前没有可靠的一致性计算结果。"
        if has_vision else
        "本次没有可用的视觉信息，仅依据对话文字作初步整理；"
        "无法判断语言与视觉信息的一致性。"
    )

    trend_summary = "一次对话缺少可靠的前后对比，暂无法判断状态变化方向。"
    if input_data.vision_summary is not None:
        valences = input_data.vision_summary.valence_trend
        if len(valences) >= 2:
            trend_summary = (
                f"会话中的视觉效价记录从 {valences[0]:.2f} 变化到"
                f" {valences[-1]:.2f}；这一观察不能单独说明心理状态改善或恶化。"
            )

    suggestions = [_SUGGESTIONS[primary]]
    if urgent_risk:
        suggestions.insert(
            0, "如果现在有伤害自己的想法，请立即告诉身边可信任的成年人，"
            "并寻求当地急救或专业危机支持。",
        )
    else:
        suggestions.append(
            "如果这些困扰持续存在或影响学习、生活，可以请家长或学校心理老师"
            "协助联系专业人员进一步评估。"
        )

    return EvaluationOutput(
        overall_status=OverallStatus(
            level=overall_level, concern_index=concern_index, summary=summary,
        ),
        psychological_profile=profile,
        primary_concern=PrimaryConcern(
            dimension=PsychologicalDimension(primary),
            description=primary_description,
        ),
        key_findings=findings,
        multimodal_observation=MultimodalObservation(
            consistency_score=None,
            consistency_level=ConsistencyLevel.UNKNOWN,
            summary=multimodal_summary,
        ),
        trend_and_suggestions=TrendAndSuggestions(
            trend=TrendDirection.UNCLEAR,
            trend_summary=trend_summary,
            suggestions=suggestions,
        ),
        metadata=EvaluationMetadata(
            schema_version=SCHEMA_VERSION,
            assessment_id=assessment_id,
            generated_at=generated_at,
        ),
    )
