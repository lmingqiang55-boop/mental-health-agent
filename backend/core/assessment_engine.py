"""多模态心理评估 Agent（A+B 协同，目标图模块 2）。

对话闭环结束后被 API 层调用，负责：
- 综合完整对话内容（文本）
- 结合会话级 VisionState / AudioState
- 结合知识库与规则
- 输出各维度得分、风险判断、个性化建议

它不与学生直接交互（不是对话 Agent），也不负责存储（记忆库负责）。
"""

from uuid import uuid4

from backend.models.enums import (
    AssessmentDimension,
    RecommendationCategory,
    RiskLevel,
)
from backend.models.assessment import (
    AssessmentResult,
    DimensionScore,
    Recommendation,
)
from backend.models.states import (
    RiskResult,
    SessionAudioSummary,
    SessionState,
    SessionVisionSummary,
)
from backend.rag.retriever import retrieve

DIMENSION_LABELS = {
    AssessmentDimension.MOOD.value: "情绪",
    AssessmentDimension.PRESSURE.value: "压力",
    AssessmentDimension.INTERPERSONAL.value: "人际关系",
    AssessmentDimension.SELF_COGNITION.value: "自我认知",
    AssessmentDimension.STUDY_LIFE.value: "学习生活",
    AssessmentDimension.DURATION.value: "持续时间",
}

# 各维度的困扰关键词（规则式 Demo，后续由模型替换）
DIMENSION_KEYWORDS = {
    AssessmentDimension.MOOD.value: ("低落", "难过", "哭", "抑郁", "烦", "不开心"),
    AssessmentDimension.PRESSURE.value: ("压力", "焦虑", "紧张", "担心", "害怕"),
    AssessmentDimension.INTERPERSONAL.value: (
        "孤独", "吵架", "矛盾", "没人", "关系差", "孤立"),
    AssessmentDimension.SELF_COGNITION.value: (
        "没用", "自卑", "否定", "失败", "差劲", "没价值"),
    AssessmentDimension.STUDY_LIFE.value: (
        "失眠", "睡不着", "疲惫", "没精力", "学不进", "注意力差"),
    AssessmentDimension.DURATION.value: (
        "一个月", "两个月", "很久", "一直", "几个月", "周"),
}


class AssessmentEngine:
    def assess(self, session: SessionState) -> AssessmentResult:
        text_corpus = "\n".join(
            m.content for m in session.conversation_history if m.role.value == "user")

        dimension_scores = [
            self._score_dimension(dim.value, text_corpus,
                                  session.vision_summary,
                                  session.audio_summary)
            for dim in AssessmentDimension
        ]

        risk = self._combine_risk(session, dimension_scores)
        recommendations = self._build_recommendations(risk, dimension_scores)
        overall = round(max(
            risk.risk_score,
            max((s.score for s in dimension_scores), default=0.1)
        ), 3)

        key_concerns = [
            f"{s.dimension_label}：{s.score:.2f}"
            for s in dimension_scores if s.score >= 0.5
        ]

        return AssessmentResult(
            result_id=str(uuid4()),
            session_id=session.session_id,
            student_ref=session.student_ref,
            dimension_scores=dimension_scores,
            overall_score=overall,
            risk=risk,
            recommendations=recommendations,
            summary=self._build_summary(dimension_scores, risk),
            key_concerns=key_concerns,
            assessment_method="rule",
        )

    # -- 各维度打分 ------------------------------------------------------

    def _score_dimension(
        self,
        dimension: str,
        text_corpus: str,
        vision: SessionVisionSummary | None,
        audio: SessionAudioSummary | None,
    ) -> DimensionScore:
        evidence: list[str] = []
        score = 0.1

        hits = [kw for kw in DIMENSION_KEYWORDS[dimension] if kw in text_corpus]
        if hits:
            score = min(0.85, 0.35 + 0.15 * len(hits))
            evidence.append(f"文字提及：{ '、'.join(hits[:3]) }")

        # 多模态信号按维度映射
        if dimension == AssessmentDimension.MOOD.value and vision:
            if vision.mean_valence is not None:
                mv = vision.mean_valence
                mood_score = max(0.0, min(1.0, -mv))
                score = max(score, mood_score)
                evidence.append(f"会话平均效价：{mv}")
        if dimension == AssessmentDimension.STUDY_LIFE.value and audio:
            if audio.mean_energy is not None and audio.mean_energy < 0.4:
                score = max(score, 0.5)
                evidence.append(f"会话平均语音能量：{audio.mean_energy}")
        if dimension == AssessmentDimension.MOOD.value and vision:
            if vision.dominant_emotion in {"sad", "angry", "fearful"}:
                score = max(score, 0.55)
                evidence.append(f"主导情绪：{vision.dominant_emotion}")

        return DimensionScore(
            dimension=dimension,
            dimension_label=DIMENSION_LABELS[dimension],
            score=round(min(score, 1.0), 3),
            confidence=0.6 if evidence else 0.3,
            evidence=evidence,
        )

    # -- 风险与建议 ------------------------------------------------------

    def _combine_risk(self, session: SessionState,
                      scores: list[DimensionScore]) -> RiskResult:
        latest = session.latest_risk
        # 若对话中已识别高风险，直接沿用
        if latest.risk_level == RiskLevel.HIGH:
            return latest
        high_dims = [s for s in scores if s.score >= 0.6]
        if len(high_dims) >= 2:
            return RiskResult(
                risk_level=RiskLevel.MEDIUM,
                risk_score=round(max(s.score for s in high_dims), 3),
                risk_reasons=["多个评估维度得分偏高"],
                risk_types=[s.dimension_label for s in high_dims],
                key_evidence=[e for s in high_dims for e in s.evidence[:2]],
            )
        return latest

    def _build_recommendations(
        self, risk: RiskResult, scores: list[DimensionScore]
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []
        by_dim = {s.dimension: s for s in scores}

        if by_dim.get(AssessmentDimension.MOOD.value,
                      DimensionScore(dimension="mood",
                                     dimension_label="情绪", score=0)).score >= 0.5:
            recs.append(Recommendation(
                category=RecommendationCategory.EMOTION_REGULATION,
                content="可以尝试规律的深呼吸放松、适度运动，并记录每天的情绪变化。",
                priority=2))
        if by_dim.get(AssessmentDimension.STUDY_LIFE.value,
                      DimensionScore(dimension="study_life",
                                     dimension_label="学习生活", score=0)).score >= 0.5:
            recs.append(Recommendation(
                category=RecommendationCategory.STUDY_LIFE,
                content="建议固定作息时间，睡前减少电子设备使用，逐步恢复学习节奏。",
                priority=2))
        if risk.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH}:
            recs.append(Recommendation(
                category=RecommendationCategory.HELP_RESOURCE,
                content="建议尽快联系学校心理老师或专业心理服务机构，获取进一步支持。",
                priority=1))
        if not recs:
            recs.append(Recommendation(
                category=RecommendationCategory.EMOTION_REGULATION,
                content="继续保持规律作息和良好的社交活动，关注自身情绪变化。",
                priority=3))
        return recs

    def _build_summary(self, scores: list[DimensionScore],
                       risk: RiskResult) -> str:
        top = sorted(scores, key=lambda s: s.score, reverse=True)[:2]
        desc = "、".join(f"{s.dimension_label}({s.score:.2f})" for s in top)
        return (f"本次初步筛查中，相对需要关注的方面为：{desc}。"
                f"风险等级为{risk.risk_level.value}，结果仅作初步提示，不构成临床诊断。")


assessment_engine = AssessmentEngine()
