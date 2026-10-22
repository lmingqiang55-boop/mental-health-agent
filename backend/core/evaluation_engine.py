"""接收逐句视觉快照与整段视觉汇总，交给评估服务。"""

from typing import Iterable, Protocol

from evaluation_agent.demographics import extract_age_grade
from evaluation_agent.inputs import DialogueRole, EvaluationInput
from evaluation_agent.llm_client import EvaluationLLMClient, LLMConfig
from evaluation_agent.service import EvaluationService, ScoredAssessment

from backend.core.report_builder import build_report
from backend.llm.config import DEFAULT_ENV_FILE
from backend.models.enums import MessageRole, RiskLevel
from backend.models.evaluation import EvaluationResult
from backend.models.states import RiskResult, SessionState, _now
from backend.safety.agent import evaluate_safety
from backend.safety.projection import (
    most_severe_verdict,
    project_to_risk_result,
    verdict_is_more_severe,
)
from backend.safety.schemas import SafetyVerdict

RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}

#: 直接提交转写文本时，最多补做多少次安全判定。
#: 保留历史 35 轮会话的补判范围，不随普通聊天上限缩短。
MAX_SAFETY_BACKFILL = 35


class AssessmentService(Protocol):
    def evaluate(self, input_data: EvaluationInput) -> ScoredAssessment: ...


def input_from_session(session: SessionState) -> EvaluationInput:
    """当前文本会话的适配器；只转发已经与消息绑定的视觉快照。"""
    if not any(message.role == MessageRole.USER for message in session.conversation_history):
        raise ValueError("至少需要一条用户消息才能评估")
    return EvaluationInput.model_validate({
        "dialogue_history": [
            # safety 必须排除：评估输入契约明确不含安全信号
            # （evaluation_agent/inputs.py 的设计约定），安全结论只用于
            # 后端投影出报告的风险字段，不交给评估模型。
            message.model_dump(mode="json", exclude={"audio_snapshot", "safety"})
            for message in session.conversation_history
        ],
        # 不把按时间间隔采样的 vision_state_log 冒充为逐句数据。
        "vision_summary": (
            session.vision_summary.model_dump(mode="json")
            if session.vision_summary is not None else None
        ),
    })


def _higher(left: RiskResult, right: RiskResult) -> RiskResult:
    """取风险更高的一份（先比等级，再比分数）。"""
    if (RISK_ORDER[right.risk_level], right.risk_score) > (
            RISK_ORDER[left.risk_level], left.risk_score):
        return right
    return left


def _screen_user_messages(input_data: EvaluationInput) -> list[SafetyVerdict]:
    """对提交的对话逐条做**新版 Safety** 判定，返回结论列表。"""
    verdicts: list[SafetyVerdict] = []
    history: list[tuple[str, str]] = []
    for message in input_data.dialogue_history:
        if message.role == DialogueRole.USER:
            if len(history) >= 2 * MAX_SAFETY_BACKFILL:
                break
            verdicts.append(evaluate_safety(message.content, history))
        history.append((message.role.value, message.content))
    return verdicts


def safety_verdicts(session: SessionState) -> list[SafetyVerdict]:
    """会话里可用于评估的全部安全结论。

    优先复用 ``/api/chat`` 已经算好的 ``Message.safety`` 与 ``latest_safety``
    （不重复判定）；对没有安全结论的用户消息（例如直接导入的转写文本）补做
    判定，**不得**默认当作低风险放行。
    """
    found = [message.safety for message in session.conversation_history
             if message.role == MessageRole.USER and message.safety is not None]
    if session.latest_safety is not None:
        found.append(session.latest_safety)
    missing = any(
        message.role == MessageRole.USER and message.safety is None
        for message in session.conversation_history
    )
    if missing:
        found.extend(_screen_user_messages(input_from_session(session)))
    return found


def risk_from_verdicts(verdicts: Iterable[SafetyVerdict], initial: RiskResult) -> RiskResult:
    """把安全结论单向投影成报告风险字段，取其中最高的一份。"""
    best = initial
    for verdict in verdicts:
        best = _higher(best, project_to_risk_result(verdict))
    return best


def risk_from_input(input_data: EvaluationInput, initial: RiskResult) -> RiskResult:
    """直接提交的对话也经过**新版 Safety Agent** 判定，避免绕过安全检测。

    新旧区别：判定不再来自关键词规则引擎，而是 `backend/safety` 的 LLM 判定；
    LLM 判定失败时新版 Safety 返回 UNCERTAIN/需人工复核，因此这里是
    fail-safe（偏保守），不会静默降级成低风险。
    """
    return risk_from_verdicts(_screen_user_messages(input_data), initial)


def risk_from_session(session: SessionState) -> RiskResult:
    """从会话已有的逐条安全结论投影出评估报告的风险字段。

    优先复用 ``/api/chat`` 已经算好的 ``Message.safety``（不重复判定）；
    对没有安全结论的用户消息（例如直接导入的转写文本）补做判定，
    **不得**默认当作低风险放行。
    """
    return risk_from_verdicts(safety_verdicts(session), RiskResult())


def record_safety_conclusion(session: SessionState, verdicts: Iterable[SafetyVerdict]) -> None:
    """把最严重的安全结论回写到会话，安全结论只能变严、不能被冲淡。

    为什么必须回写：Healing 等入口的守卫只看**会话上的安全状态**
    （``latest_safety`` / ``safety_halted`` / ``safety_stage``）。如果只走
    ``/api/assessment`` 直接提交转写，安全判定此前只进了报告字段，
    会话上没有任何安全状态，那些入口会把高危会话当作普通会话继续 —— 安全空窗。
    这里回写的是 :class:`SafetyVerdict` 本身（不是反向还原的 RiskResult），
    因此单向投影的约定不被破坏。
    """
    worst = most_severe_verdict(*verdicts)
    if worst is None:
        return
    if session.latest_safety is None or verdict_is_more_severe(worst, session.latest_safety):
        session.latest_safety = worst.model_copy(deep=True)


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
        if not any(message.role == DialogueRole.USER for message in data.dialogue_history):
            raise ValueError("至少需要一条用户消息才能评估")
        age, grade = extract_age_grade(data)
        service = self._service
        if service is None:
            config = LLMConfig.from_env(env_file=DEFAULT_ENV_FILE)
            service = EvaluationService(client=EvaluationLLMClient(config=config))
        scored = service.evaluate(data)
        # 安全判定只做一次，两处使用：
        # 1) 单向投影成报告的 risk 字段；
        # 2) 把最严重的结论回写到会话安全状态，供 Healing 等入口的守卫读取。
        verdicts = (safety_verdicts(session) if input_data is None
                    else _screen_user_messages(data))
        risk = risk_from_verdicts(verdicts, RiskResult())
        record_safety_conclusion(session, verdicts)
        created_at = _now()
        sources = ["text"]
        if any(message.speech is not None for message in session.conversation_history):
            sources.append("audio_transcription")
        if any(message.vision_snapshot is not None for message in session.conversation_history):
            sources.append("vision_analysis")
        return EvaluationResult(
            result_id=scored.assessment_id,
            session_id=session.session_id,
            student_ref=session.student_ref,
            age=age,
            grade=grade,
            psychological_profile=scored.psychological_profile,
            concern_index=scored.concern_index,
            overall_level=scored.overall_level,
            risk=risk,
            report=build_report(
                assessment_id=scored.assessment_id,
                profile=scored.psychological_profile,
                concern_index=scored.concern_index,
                overall_level=scored.overall_level,
                input_data=data,
                risk=risk,
                generated_at=created_at,
                item_scores=getattr(scored, "item_scores", None),
            ),
            data_sources=sources,
            consent_version=session.consent.version,
            created_at=created_at,
        )


evaluation_engine = EvaluationEngine()
