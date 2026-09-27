"""对话 Agent（A 模块核心）。

负责「问什么」：六维状态机、提问策略、情感支持引导、危机识别。
不负责「怎么表达」（LLMClient）、不直接调用视觉/音频模型、不负责页面。

流程对应目标图「实时对话闭环（边聊边感知·动态引导）」：
    用户文本 + 句级 VisionState/AudioState
        → 多模态融合
        → 风险评估
        → 六维状态机决定策略
        → RAG + LLM 生成回复
"""

from backend.core.multimodal_fusion import fuse_turn
from backend.core.risk_engine import assess_risk
from backend.llm.client import get_llm_client
from backend.models.enums import (
    AssessmentDimension,
    DimensionStatus,
    SessionStage,
)
from backend.models.responses import DialogueResponsePayload
from backend.models.states import SessionState
from backend.rag.retriever import retrieve

MAX_CLARIFY = 2  # 同一维度最多澄清次数，超过后强制推进

VAGUE_ANSWERS = {"嗯", "哦", "好", "好的", "不知道", "不清楚", "还行", "还好",
                 "对", "是", "不是", "没有", "yes", "no"}

TOPIC_CLUES: dict[str, tuple[str, ...]] = {
    AssessmentDimension.MOOD.value: ("心情", "情绪", "低落", "难过", "开心"),
    AssessmentDimension.PRESSURE.value: ("压力", "焦虑", "紧张", "负担"),
    AssessmentDimension.INTERPERSONAL.value: (
        "人际", "同学", "朋友", "家人", "关系", "孤独"),
    AssessmentDimension.SELF_COGNITION.value: (
        "自我", "否定", "自卑", "没用", "价值", "自信"),
    AssessmentDimension.STUDY_LIFE.value: (
        "学习", "生活", "精力", "睡眠", "疲惫", "累", "睡"),
    AssessmentDimension.DURATION.value: (
        "多久", "持续", "周", "个月", "开始", "星期"),
}

DIMENSION_LABELS = {dim.value: label for dim, label in zip(
    AssessmentDimension,
    ("情绪", "压力", "人际关系", "自我认知", "学习生活", "持续时间"),
)}


class DialogueManager:
    def __init__(self) -> None:
        self._llm = get_llm_client()

    def process_turn(self, user_text: str,
                     session: SessionState) -> DialogueResponsePayload:
        fused = fuse_turn(
            user_text, session.latest_vision_state, session.latest_audio_state)
        risk = assess_risk(fused)
        session.latest_risk = risk

        # 危机模式：高风险后不再推进评估维度
        if risk.requires_intervention:
            session.crisis_mode = True
            session.current_stage = SessionStage.CRISIS
            return self._reply(session, "crisis_support", risk)
        if session.crisis_mode:
            return self._reply(session, "crisis_support", risk)

        if session.current_stage == SessionStage.COMPLETED:
            return self._reply(session, "post_assessment", risk)

        strategy = self._advance_state_machine(user_text, session)
        return self._reply(session, strategy, risk)

    # -- 状态机 ----------------------------------------------------------

    def _advance_state_machine(self, user_text: str,
                               session: SessionState) -> str:
        active = self._find_active(session)
        is_vague = user_text.strip().lower() in VAGUE_ANSWERS

        if active and is_vague:
            if session.clarify_count < MAX_CLARIFY:
                session.clarify_count += 1
                return "clarify_answer"
            # 澄清次数用尽，强制推进
            session.assessment_state[active] = DimensionStatus.COVERED
            session.clarify_count = 0
        elif active:
            session.assessment_state[active] = DimensionStatus.COVERED
            session.clarify_count = 0

        # 第一轮自发回答可同时覆盖多个明确提到的维度
        if session.turn_count == 0:
            for dimension, clues in TOPIC_CLUES.items():
                if (session.assessment_state[dimension]
                        is DimensionStatus.PENDING
                        and any(clue in user_text for clue in clues)):
                    session.assessment_state[dimension] = DimensionStatus.COVERED

        next_dimension = next(
            (name for name, status in session.assessment_state.items()
             if status is DimensionStatus.PENDING), None)

        if next_dimension:
            session.assessment_state[next_dimension] = (
                DimensionStatus.IN_PROGRESS)
            return f"explore_{next_dimension}"

        session.current_stage = SessionStage.COMPLETED
        return "finish_assessment"

    @staticmethod
    def _find_active(session: SessionState) -> str | None:
        return next(
            (name for name, status in session.assessment_state.items()
             if status is DimensionStatus.IN_PROGRESS), None)

    # -- 回复生成 --------------------------------------------------------

    def _reply(self, session: SessionState, strategy: str,
               risk) -> DialogueResponsePayload:
        context = retrieve(f"{strategy}")
        reply = self._llm.generate_reply(
            "", strategy, context, session.conversation_history)
        return DialogueResponsePayload(
            reply=reply,
            next_strategy=strategy,
            current_stage=session.current_stage.value,
            risk=risk,
        )
