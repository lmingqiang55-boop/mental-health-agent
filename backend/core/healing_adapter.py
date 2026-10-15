"""The orchestration layer reads actual records; the healing agent never opens a DB."""

import re

from backend.models.healing import HealingBackground, HealingBackgroundInput, HealingMemory, SchoolStage
from backend.models.evaluation import EvaluationRecord
from backend.models.states import RiskResult, SessionState


class HealingBackgroundInvalid(ValueError):
    """Recorded demographics cannot be used by the current support module."""


def grade_to_school_stage(grade: str | None) -> SchoolStage | None:
    """Map recognized grade labels only; never derive a numerical age."""
    if grade is None:
        return None
    grade = re.sub(r"\s+", "", grade)
    if re.fullmatch(r"(?:小学)?[一二三四五六1-6]年级", grade):
        return "primary"
    if re.fullmatch(r"初[一二三1-3]|初中[一二三1-3]年级|[七八九7-9]年级", grade):
        return "middle"
    if re.fullmatch(r"高[一二三1-3]|高中[一二三1-3]年级", grade):
        return "high"
    return None


def support_record(payload: dict) -> EvaluationRecord:
    """Persisted assessment record; its risk field is an **evaluation report** field.

    这里不判定安全：旧代码会检查持久记录的 risk 字段是否完整
    （``RISK_FIELDS`` / ``risk_input_fields``）并据此阻断普通支持，
    新版 Safety 之后治愈的安全输入只有 SafetyVerdict，是否继续普通治愈
    由 ``safety_blocks_normal_flow`` 决定，与报告字段是否缺失无关。
    缺失字段仍然要补齐，否则 EvaluationRecord 无法解析。
    """
    payload = {**payload, "result": dict(payload["result"])}
    raw = payload["result"].get("risk")
    try:
        risk = RiskResult.model_validate(raw)
    except ValueError:
        risk = RiskResult()
    payload["result"]["risk"] = risk.model_dump(mode="json")
    return EvaluationRecord.model_validate(payload)


def build_healing_memory(session: SessionState, store, background: HealingBackgroundInput) -> HealingMemory:
    records = [support_record(payload) for payload in
               store.list_payloads_by_student(session.student_ref or session.session_id)]
    if not records:
        raise ValueError("请先完成一次筛查，再进入心理支持陪伴。")
    latest = records[-1]
    recorded_stage = grade_to_school_stage(latest.result.grade)
    resolved = background.model_dump()
    resolved["age"] = latest.result.age
    if recorded_stage is not None:
        resolved["school_stage"] = recorded_stage
    try:
        resolved_background = HealingBackground.model_validate(resolved)
    except ValueError:
        raise HealingBackgroundInvalid(
            "评估记忆中的年龄或学段不适用于当前陪伴：年龄需为 6–18 岁，且与学段一致。请核对评估信息。"
        ) from None
    return HealingMemory(
        student_ref=latest.student_ref, session_id=session.session_id,
        assessment=latest.result.model_copy(deep=True),
        recent_assessments=[record.result.model_copy(deep=True) for record in records],
        background=resolved_background,
        # 安全输入是会话上的新版 Safety 结论本身，不做任何加工或降级。
        safety=session.latest_safety.model_copy(deep=True) if session.latest_safety is not None else None,
        current_session_messages=[message.content for message in session.conversation_history
                                  if message.role.value == "user"][-20:],
        provenance={
            "assessment": "persistent_evaluation_record",
            "risk": "assessment_report_field_only; safety_conclusion_comes_from_backend.safety",
            "safety": ("session.latest_safety_from_backend_safety_agent" if session.latest_safety is not None
                       else "session.latest_safety_absent; ordinary_flow_gated_by_safety_blocks_normal_flow"),
            "recent_assessments": "persistent_last_three_evaluation_records",
            "background": "explicit_caller_context; demographics_from_persistent_assessment",
            "background.age": "persistent_evaluation_record.age" if latest.result.age is not None else "unknown",
            "assessment.grade": "persistent_evaluation_record.grade" if latest.result.grade is not None else "unknown",
            "background.school_stage": (
                "persistent_evaluation_record.grade_to_school_stage" if recorded_stage is not None
                else "explicit_caller_input.school_stage" if background.school_stage is not None else "unknown"
            ),
            "current_session_messages": "current_process_last_20_user_messages; not_persistent; not_assessment_transcript",
            "multimodal_observation": "saved_report; unknown_consistency_is_not_an_emotion_conclusion",
        },
    )
