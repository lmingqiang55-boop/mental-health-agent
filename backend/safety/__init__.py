# -*- coding: utf-8 -*-
"""新 Safety：系统唯一的心理安全检测入口。

对外主要成员：
- :class:`~backend.safety.schemas.SafetyVerdict` —— 安全结论（唯一安全状态来源）
- :func:`~backend.safety.agent.evaluate_safety` —— 同步判定入口
- :func:`~backend.safety.agent.get_safety_agent` —— 异步判定 Agent
- :func:`~backend.safety.hotlines.load_hotlines` —— 已核实热线（按部署地区）
- :func:`~backend.safety.projection.project_to_risk_result` —— 评估报告字段投影
"""

from backend.safety.schemas import (
    ModelStatus,
    SafetyAgentError,
    SafetyLevel,
    SafetyRoute,
    SafetySignal,
    SafetyStage,
    SafetyVerdict,
    assemble_verdict,
    build_failed_verdict,
    derive_risk_detected,
    derive_route,
)

__all__ = [
    "ModelStatus",
    "SafetyAgentError",
    "SafetyLevel",
    "SafetyRoute",
    "SafetySignal",
    "SafetyStage",
    "SafetyVerdict",
    "assemble_verdict",
    "build_failed_verdict",
    "derive_risk_detected",
    "derive_route",
]
