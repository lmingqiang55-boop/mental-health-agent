"""Conservative support-stage routing; this does not replace crisis assessment."""

import re

from backend.core.multimodal_fusion import fuse_turn
from backend.core.risk_engine import _has_signal, assess_risk
from backend.core.text_signals import predicate_is_negated
from backend.models.enums import RiskLevel
from backend.models.states import RiskResult

ESSENTIAL_RISK_FIELDS = {"risk_level", "risk_score", "requires_intervention"}
UNCERTAIN_REASON = "风险信息不完整或存在冲突，需要由可信成人或专业人员确认"
SEVERE_SIGNAL = re.compile(
    r"(?:完全|已经|一直|连续|现在).{0,8}(?P<impairment>无法|不能|没法)(?:上学|吃饭|进食|生活)|"
    r"连续.{0,5}(?:天|周).{0,6}(?:没吃|不吃|没睡|不睡)|"
    r"越来越.{0,8}(?:撑不住|严重|糟糕|难受)")
SEVERE_NEGATION = re.compile(
    r"(?:并不|并没有|并非|不是|没有|并未|从未|不再)"
    r"(?:(?:现在|已经|一直|完全|连续|越来越|变得|感到|觉得|出现|发生)\s*)*$")
PLAN_CUE = re.compile(r"今晚|明天|现在|已经|准备|打算|计划|想要|想|要")
PLAN_ACTION = re.compile(r"跳楼|跳下去|割腕|吞药|吃完.{0,5}药|结束生命")


def severe_is_negated(clause, signal):
    # Check only modifiers attached to this predicate. An unrelated earlier
    # denial must not suppress it, nor a denied first signal hide a later one.
    start = signal.start("impairment") if signal.group("impairment") else signal.start()
    return SEVERE_NEGATION.search(clause[:start].rstrip()) is not None


def guard_risk(memory, text="", session_risk=None, crisis_mode=False):
    contexts = [text, memory.background.current_concern or "", *memory.current_session_messages,
                *memory.background.important_events]
    risks = [memory.assessment.risk]
    if session_risk is not None:
        risks.append(session_risk)
    risks.extend(assess_risk(fuse_turn(context, None, None)) for context in contexts if context)
    uncertainty = list(memory.risk_input_issues)
    if not ESSENTIAL_RISK_FIELDS <= memory.assessment.risk.model_fields_set:
        uncertainty.append("assessment_risk_default_fields")
    # Risk objects returned by assess_risk may omit only explanatory empty arrays.
    if session_risk is not None and session_risk.model_fields_set and not ESSENTIAL_RISK_FIELDS <= session_risk.model_fields_set:
        uncertainty.append("session_risk_incomplete")
    order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
    urgent = []
    for risk in risks:
        evidence = "\n".join([*risk.risk_reasons, *risk.risk_types, *risk.key_evidence])
        evidence_risk = assess_risk(fuse_turn(evidence, None, None))
        contradictions = (risk.risk_score >= .8 and risk.risk_level != RiskLevel.HIGH or
                          risk.risk_level == RiskLevel.HIGH and not risk.requires_intervention or
                          risk.risk_level == RiskLevel.LOW and risk.requires_intervention or
                          evidence_risk.requires_intervention and risk.risk_level != RiskLevel.HIGH or
                          risk.risk_level == RiskLevel.LOW and any("自伤" in kind or "自杀" in kind for kind in risk.risk_types))
        if contradictions:
            uncertainty.append("risk_fields_conflict")
        if risk.requires_intervention or risk.risk_level == RiskLevel.HIGH or evidence_risk.requires_intervention:
            urgent.append(max([risk, evidence_risk], key=lambda value: (order[value.risk_level], value.risk_score)))
    for context in contexts:
        # Plans may lack the literal word 自杀. Check complete positive clauses.
        for clause in re.split(r"[，,。！？；\n]", context):
            for action in PLAN_ACTION.finditer(clause):
                cues = [cue for cue in PLAN_CUE.finditer(clause, 0, action.start())
                        if action.start() - cue.end() <= 18]
                if not cues:
                    continue
                cue = cues[-1]
                if not (predicate_is_negated(clause, action.start()) or
                        predicate_is_negated(clause, cue.start())):
                    urgent.append(RiskResult(risk_level=RiskLevel.HIGH, risk_score=.9, requires_intervention=True,
                                      risk_reasons=["出现明确的自伤行动计划表述"],
                                      key_evidence=[clause[cue.start():action.end()]]))
            for severe in SEVERE_SIGNAL.finditer(clause):
                if not severe_is_negated(clause, severe):
                    urgent.append(RiskResult(risk_level=RiskLevel.MEDIUM, risk_score=.7, requires_intervention=True,
                                      risk_reasons=["出现日常功能严重受影响或持续恶化的表述"], key_evidence=[severe.group(0)]))
        threats = tuple(match.group(0) for match in re.finditer(r"被.{0,8}(?:威胁|殴打|勒索)|欺凌|霸凌|校园暴力", context))
        if _has_signal(context, threats):
            urgent.append(RiskResult(risk_level=RiskLevel.MEDIUM, risk_score=.7, requires_intervention=True,
                              risk_reasons=["出现欺凌或威胁表述，请由可信成人跟进"]))
    # Choose only after every context is checked; a medium signal cannot hide a plan.
    if urgent or crisis_mode:
        chosen = max(urgent or risks, key=lambda risk: (order[risk.risk_level], risk.risk_score)).model_copy(deep=True)
        chosen.requires_intervention = True
        if chosen.risk_level == RiskLevel.LOW:
            chosen.risk_level, chosen.risk_score = RiskLevel.MEDIUM, max(.5, chosen.risk_score)
            chosen.risk_reasons.append(UNCERTAIN_REASON)
        if crisis_mode and chosen.risk_level != RiskLevel.HIGH:
            chosen.risk_level, chosen.risk_score = RiskLevel.HIGH, max(.8, chosen.risk_score)
            chosen.risk_reasons.append("会话已进入危机处理，请由现实中的支持人员跟进")
        return chosen
    if uncertainty:
        return RiskResult(risk_level=RiskLevel.MEDIUM, risk_score=.5, requires_intervention=True,
                          risk_reasons=[UNCERTAIN_REASON])
    return None


def referral_text(risk, crisis_text):
    if UNCERTAIN_REASON in risk.risk_reasons:
        return "目前可读取的安全信息还不完整或有冲突，我先暂停具体方法建议。请让身边可信任的成人或专业人员帮助确认；这不表示已经判断你有危机。"
    if risk.risk_level != RiskLevel.HIGH:
        return "我听到了你现在遇到的困难。请联系身边可信任的成人或专业人员，帮助处理此刻的处境；这轮先暂停普通方法建议。"
    return crisis_text
