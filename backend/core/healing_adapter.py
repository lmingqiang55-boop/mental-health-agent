"""The orchestration layer reads actual records; the healing agent never opens a DB."""

import re

from backend.models.healing import HealingBackground, HealingBackgroundInput, HealingMemory, SchoolStage
from backend.models.evaluation import EvaluationRecord
from backend.models.states import RiskResult, SessionState

RISK_FIELDS = {"risk_level", "risk_score", "requires_intervention"}


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


def support_record(payload: dict) -> tuple[EvaluationRecord, list[str]]:
    """Defaults are only a parsing placeholder; issues block ordinary support."""
    payload = {**payload, "result": dict(payload["result"])}
    raw = payload["result"].get("risk")
    issues = []
    if not isinstance(raw, dict):
        issues.append("assessment_risk_missing")
        raw = {}
    missing = RISK_FIELDS - raw.keys()
    recorded_fields = payload.get("risk_input_fields")
    if recorded_fields is not None:
        missing |= RISK_FIELDS - set(recorded_fields)
    issues.extend("assessment_risk_field_missing:" + field for field in sorted(missing))
    try:
        risk = RiskResult.model_validate(raw)
    except ValueError:
        issues.append("assessment_risk_invalid")
        risk = RiskResult()
    payload["result"]["risk"] = risk.model_dump(mode="json")
    return EvaluationRecord.model_validate(payload), issues


def build_healing_memory(session: SessionState, store, background: HealingBackgroundInput) -> HealingMemory:
    inspected = [support_record(payload) for payload in
                 store.list_payloads_by_student(session.student_ref or session.session_id)]
    records = [record for record, _ in inspected]
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
        risk_input_issues=inspected[-1][1],
        current_session_messages=[message.content for message in session.conversation_history
                                  if message.role.value == "user"][-20:],
        provenance={
            "assessment": "persistent_evaluation_record",
            "risk": "serialized_assessment_fields_inspected_before_defaults; missing_blocks_support",
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
