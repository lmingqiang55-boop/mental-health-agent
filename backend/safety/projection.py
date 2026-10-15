# -*- coding: utf-8 -*-
"""SafetyVerdict -> 评估报告 RiskResult 的单向投影。

【为什么需要这一层】
最终心理评估的 ``EvaluationResult.risk`` 是 ``RiskResult``（low/medium/high +
risk_score），它已经写进 SQLite、管理端预警列表与报告生成器
（``report_builder.py`` / ``memory_store.py`` / teacher API / admin 前端）。
按已确认决策，评估报告保留自己的报告词汇，由新版 Safety 结论**单向投影**填充。

【这不是安全结论】
``RiskResult`` 在这里只是**评估报告字段**。系统的安全结论始终是
:class:`~backend.safety.schemas.SafetyVerdict`；对话是否继续、是否进入
安全支持模式，只看 SafetyVerdict，不看这个投影结果。

【为什么方向只有一个】
旧口径是「旧 RiskResult -> 新安全结论」，那会污染安全判定，已明确禁止。
这里只允许 SafetyVerdict -> RiskResult，用于把安全结论呈现进评估报告。
**不得**实现反方向函数。
"""

from __future__ import annotations

from backend.models.enums import RiskLevel
from backend.models.states import RiskResult
from backend.safety.schemas import SafetyLevel, SafetyVerdict

__all__ = [
    "project_to_risk_result",
    "SAFETY_TO_REPORT_LEVEL",
    "SAFETY_LEVEL_ORDER",
    "safety_level_priority",
    "verdict_is_more_severe",
    "most_severe_verdict",
]


#: 安全等级序，用于比较「哪份结论更严重」。**唯一**的比较口径。
#: 刻意放在 ``schemas.py`` 之外：等级比较是消费方口径，不改动安全结论本身。
SAFETY_LEVEL_ORDER: dict[SafetyLevel, int] = {
    SafetyLevel.NORMAL: 0,
    SafetyLevel.UNCERTAIN: 1,
    SafetyLevel.HIGH: 2,
    SafetyLevel.IMMINENT: 3,
}


#: 安全等级 -> 评估报告等级。逐项显式列出，覆盖全部枚举值。
SAFETY_TO_REPORT_LEVEL: dict[SafetyLevel, RiskLevel] = {
    SafetyLevel.NORMAL: RiskLevel.LOW,
    SafetyLevel.UNCERTAIN: RiskLevel.MEDIUM,
    SafetyLevel.HIGH: RiskLevel.HIGH,
    SafetyLevel.IMMINENT: RiskLevel.HIGH,
}

#: 报告用风险分。仅用于报告排序与预警分级，不代表概率。
_REPORT_SCORE: dict[SafetyLevel, float] = {
    SafetyLevel.NORMAL: 0.1,
    SafetyLevel.UNCERTAIN: 0.5,
    SafetyLevel.HIGH: 0.8,
    SafetyLevel.IMMINENT: 1.0,
}

_REPORT_TYPE: dict[SafetyLevel, str] = {
    SafetyLevel.NORMAL: "未发现安全风险线索",
    SafetyLevel.UNCERTAIN: "安全信息不充分",
    SafetyLevel.HIGH: "存在安全风险线索",
    SafetyLevel.IMMINENT: "存在即时安全风险",
}


def safety_level_priority(verdict: SafetyVerdict) -> int:
    """单个安全结论的等级序，用于比较「新的结论是否更严重」。"""
    return SAFETY_LEVEL_ORDER[verdict.risk_level]


def verdict_is_more_severe(left: SafetyVerdict, right: SafetyVerdict) -> bool:
    return safety_level_priority(left) > safety_level_priority(right)


def most_severe_verdict(*verdicts: SafetyVerdict | None) -> SafetyVerdict | None:
    """取最严重的一份结论；同级时保留先出现的那份；全为 None 时返回 None。

    用于把「本轮结论」与「会话已有状态」合并：安全状态只允许变严，
    不允许被一条较温和的新结论冲淡。
    """
    best: SafetyVerdict | None = None
    for verdict in verdicts:
        if verdict is None:
            continue
        if best is None or safety_level_priority(verdict) > safety_level_priority(best):
            best = verdict
    return best


def project_to_risk_result(verdict: SafetyVerdict) -> RiskResult:
    """把安全结论投影成评估报告使用的 RiskResult。

    注意：``requires_intervention`` 在 UNCERTAIN 及以上为 True，
    以便管理端预警列表与后续跟进状态（``memory_store``）能覆盖到需要人工确认的学生。
    """
    level = verdict.risk_level
    reasons: list[str] = []
    if verdict.rationale:
        reasons.append(verdict.rationale)
    if verdict.model_status.value != "ok":
        reasons.append(f"安全判定服务状态：{verdict.model_status.value}")

    return RiskResult(
        risk_level=SAFETY_TO_REPORT_LEVEL[level],
        risk_score=_REPORT_SCORE[level],
        risk_reasons=reasons,
        risk_types=[_REPORT_TYPE[level]],
        key_evidence=list(verdict.evidence_quotes),
        requires_intervention=level is not SafetyLevel.NORMAL,
    )
