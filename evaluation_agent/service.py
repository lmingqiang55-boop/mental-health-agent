# -*- coding: utf-8 -*-
"""评估服务：把一次真实对话跑成完整的内部评估结果。

完整链路::

    EvaluationInput
            ↓
    EvaluationLLMClient          （DeepSeek 调用 + 解析 + 归一化）
            ↓
    RawLLMAssessment             （11 项 score / evidence / reason）
            ↓
    extract_item_scores
            ↓
    AssessmentItemScores
            ↓
    calculate_psychological_profile
            ↓
    PsychologicalProfile         （五维 0-100）
            ↓
    calculate_concern_index
            ↓
    get_overall_level
            ↓
    ScoredAssessment             （本模块的返回值）

**分工必须清楚**：

- **大模型 = 语义判断层**：只输出 11 个小项的 0-3 分与依据理由；
- **代码 = 数值计算层**：五维分数、``concern_index``、关注等级全部由纯函数算出，
  模型无权决定。

本模块**不生成**最终用户报告（``summary`` / ``key_findings`` /
``multimodal_observation`` / ``trend_and_suggestions``），那些属于下一阶段。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from pydantic import Field, model_validator

from .base import NonEmptyStr, StrictSchemaBase
from .inputs import EvaluationInput
from .llm_client import AssessmentTrace, EvaluationLLMClient, LLMAssessmentResult
from .normalization import ItemAssessmentDetails, build_item_details
from .raw_assessment import RawLLMAssessment
from .schemas import (
    AssessmentItemScores,
    OverallLevel,
    PsychologicalProfile,
)
from .scoring import (
    calculate_concern_index,
    calculate_psychological_profile,
    get_level_label_zh,
    get_overall_level,
)

__all__ = ["ScoredAssessment", "EvaluationService", "default_assessment_id"]

logger = logging.getLogger("evaluation_agent.service")


def default_assessment_id(now: datetime | None = None) -> str:
    """生成一个评估标识，例如 ``asmt-20250318T143205-9f3c1a2b``。

    带随机后缀是为了避免同一秒内的多次评估撞号。
    """
    moment = now or datetime.now(timezone.utc)
    stamp = moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"asmt-{stamp}-{uuid4().hex[:8]}"


class AssessmentClient(Protocol):
    """服务依赖的客户端协议（便于测试时注入假客户端，完全不联网）。"""

    def assess_with_trace(
        self, input_data: EvaluationInput
    ) -> LLMAssessmentResult:  # pragma: no cover - 协议
        ...


class ScoredAssessment(StrictSchemaBase):
    """一次真实评估的**完整内部结果**。

    这是后端内部数据，**不是**用户最终报告协议
    （用户可见报告是 :class:`evaluation_agent.schemas.EvaluationOutput`，
    由下一阶段生成）。

    保留全部中间结果的目的：出问题时可以回答"这个 53 分是怎么来的"——
    从模型原始判断、归一化分数、后台明细，一路到五维与指数。
    """

    assessment_id: NonEmptyStr = Field(..., description="本次评估的标识。")
    raw_assessment: RawLLMAssessment = Field(
        ..., description="模型原始产出（未归一化，含 evidence / reason）。"
    )
    item_scores: AssessmentItemScores = Field(
        ..., description="归一化后的 11 个小项分数（0-3）。"
    )
    item_details: ItemAssessmentDetails = Field(
        ..., description="后台明细记录：11 项的 score / raw_score / evidence / reason。"
    )
    psychological_profile: PsychologicalProfile = Field(
        ..., description="五维画像（0-100，由代码计算）。"
    )
    concern_index: int = Field(..., ge=0, le=100, description="关注指数（0-100，由代码计算）。")
    overall_level: OverallLevel = Field(..., description="关注等级（由代码分档）。")
    trace: AssessmentTrace = Field(..., description="模型调用的后台审计信息。")

    @property
    def level_label_zh(self) -> str:
        """界面展示用的中文等级名（不属于内部数据本身）。"""
        return get_level_label_zh(self.overall_level)

    @model_validator(mode="after")
    def _check_derived_values_are_consistent(self) -> "ScoredAssessment":
        """再验一次派生关系：任何一处接线错误都会在这里暴露。

        这些值本来就是由纯函数算出来的，这里重新推一遍是**廉价的冗余校验**：
        一旦将来有人拼接了不一致的组合（例如手工构造对象、或换了 profile），
        会立刻报错而不是把矛盾的分数写进后台。
        """
        expected_index = calculate_concern_index(self.psychological_profile)
        if self.concern_index != expected_index:
            raise ValueError(
                f"concern_index={self.concern_index} 与五维推导值 {expected_index} 不一致"
            )

        expected_level = get_overall_level(self.concern_index)
        if self.overall_level is not expected_level:
            raise ValueError(
                f"overall_level={self.overall_level.value} 与 concern_index="
                f"{self.concern_index} 的分档结果 {expected_level.value} 不一致"
            )

        detail_scores = {record.item: record.score for record in self.item_details.items}
        mismatch = {
            item: (self.item_scores.model_dump()[item], detail_scores.get(item))
            for item in detail_scores
            if self.item_scores.model_dump()[item] != detail_scores.get(item)
        }
        if mismatch:
            raise ValueError(f"item_scores 与后台明细分数不一致：{mismatch}")

        if self.item_details.assessment_id != self.assessment_id:
            raise ValueError(
                "item_details.assessment_id 与 ScoredAssessment.assessment_id 不一致"
            )
        return self


class EvaluationService:
    """编排一次完整评估：模型判断 → 归一化 → 五维 → 指数 → 等级。

    用法::

        service = EvaluationService()            # 默认从环境变量构造客户端
        result = service.evaluate(evaluation_input)
        result.concern_index, result.overall_level

    也可以在构造时注入任意实现了 ``assess_with_trace`` 的客户端
    （测试就靠这一点完全避开网络）。
    """

    def __init__(
        self,
        client: AssessmentClient | None = None,
        *,
        assessment_id_factory=None,
    ) -> None:
        self._client = client if client is not None else EvaluationLLMClient()
        self._assessment_id_factory = assessment_id_factory or default_assessment_id

    def evaluate(self, input_data: EvaluationInput) -> ScoredAssessment:
        """跑完一次完整评估。

        :param input_data: 评估输入（对话记录 + 可选视觉摘要 + 可选用户记忆）。
        :returns: 含全部中间结果与审计信息的内部结果。
        :raises LLMRetryExhaustedError: 模型调用重试后仍失败。
        :raises LLMAuthenticationError: 认证失败（不重试）。
        :raises LLMConfigurationError: 配置错误（不重试）。
        """
        assessment_id = self._assessment_id_factory()
        logger.info(
            "evaluation started: assessment_id=%s model=%s prompt_version=%s",
            assessment_id,
            getattr(getattr(self._client, "config", None), "model", "unknown"),
            self._prompt_version(),
        )

        result = self._client.assess_with_trace(input_data)
        raw = result.raw_assessment
        item_scores = result.item_scores

        # 代码负责的数值层：五维 -> 指数 -> 等级。模型不参与这三步。
        profile = calculate_psychological_profile(item_scores)
        concern_index = calculate_concern_index(profile)
        overall_level = get_overall_level(concern_index)

        # 后台明细：evidence / reason 与分数一起留存，供审计。
        details = build_item_details(raw, assessment_id)

        scored = ScoredAssessment(
            assessment_id=assessment_id,
            raw_assessment=raw,
            item_scores=item_scores,
            item_details=details,
            psychological_profile=profile,
            concern_index=concern_index,
            overall_level=overall_level,
            trace=result.trace,
        )

        logger.info(
            "evaluation finished: assessment_id=%s attempts=%d concern_index=%d level=%s",
            assessment_id,
            result.trace.attempts,
            scored.concern_index,
            scored.overall_level.value,
        )
        return scored

    def _prompt_version(self) -> str:
        from .prompt import PROMPT_VERSION

        return PROMPT_VERSION
