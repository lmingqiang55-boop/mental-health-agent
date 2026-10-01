"""接收逐句视觉快照与整段视觉汇总，交给评估服务。"""

from typing import Protocol

from evaluation_agent.inputs import DialogueRole, EvaluationInput
from evaluation_agent.llm_client import EvaluationLLMClient, LLMConfig
from evaluation_agent.service import EvaluationService, ScoredAssessment

from backend.core.multimodal_fusion import fuse_turn
from backend.core.risk_engine import assess_risk
from backend.llm.config import DEFAULT_ENV_FILE
from backend.models.enums import RiskLevel
from backend.models.evaluation import EvaluationResult
from backend.models.states import RiskResult, SessionState, VisionState

RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


class AssessmentService(Protocol):
    def evaluate(self, input_data: EvaluationInput) -> ScoredAssessment: ...


def input_from_session(session: SessionState) -> EvaluationInput:
    """当前文本会话的适配器；只转发已经与消息绑定的视觉快照。"""
    if not session.conversation_history:
        raise ValueError("至少需要一条对话消息才能评估")
    return EvaluationInput.model_validate({
        "dialogue_history": [
            message.model_dump(mode="json", exclude={"audio_snapshot"})
            for message in session.conversation_history
        ],
        # 不把按时间间隔采样的 vision_state_log 冒充为逐句数据。
        "vision_summary": (
            session.vision_summary.model_dump(mode="json")
            if session.vision_summary is not None else None
        ),
    })


def risk_from_input(input_data: EvaluationInput, initial: RiskResult) -> RiskResult:
    """直接提交的对话也经过现有风险识别，避免绕过危机提示。"""
    best = initial
    for message in input_data.dialogue_history:
        if message.role != DialogueRole.USER:
            continue
        vision = (
            VisionState.model_validate(
                message.vision_snapshot.model_dump(mode="json", exclude_none=True)
            )
            if message.vision_snapshot is not None else None
        )
        candidate = assess_risk(fuse_turn(message.content, vision))
        if (
            RISK_ORDER[candidate.risk_level], candidate.risk_score
        ) > (
            RISK_ORDER[best.risk_level], best.risk_score
        ):
            best = candidate
    return best


class EvaluationEngine:
    """评估编排接口；默认按项目根目录的配置调用 DeepSeek。"""

    def __init__(self, service: AssessmentService | None = None) -> None:
        self._service = service

    def set_service(self, service: AssessmentService | None) -> None:
        self._service = service

    def assess(
        self, session: SessionState, input_data: EvaluationInput | None = None
    ) -> EvaluationResult:
        data = input_data if input_data is not None else input_from_session(session)
        service = self._service
        if service is None:
            config = LLMConfig.from_env(env_file=DEFAULT_ENV_FILE)
            service = EvaluationService(client=EvaluationLLMClient(config=config))
        scored = service.evaluate(data)
        return EvaluationResult(
            result_id=scored.assessment_id,
            session_id=session.session_id,
            student_ref=session.student_ref,
            psychological_profile=scored.psychological_profile,
            concern_index=scored.concern_index,
            overall_level=scored.overall_level,
            risk=risk_from_input(data, session.latest_risk),
        )


evaluation_engine = EvaluationEngine()
