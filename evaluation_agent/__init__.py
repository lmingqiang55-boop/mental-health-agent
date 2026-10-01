# -*- coding: utf-8 -*-
"""Evaluation Agent 包。

当前阶段包含：

- 最终输出 Schema v1.0 与基础校验（``evaluation_agent.schemas``）；
- 11 个底层小项 -> 五维画像 -> concern_index -> OverallLevel 的确定性计算规则
  （``evaluation_agent.scoring``）；
- 输入契约 ``EvaluationInput``（``evaluation_agent.inputs``）；
- 大模型原始产出 Schema ``RawLLMAssessment``（``evaluation_agent.raw_assessment``）；
- 归一化层与 evidence/reason 后台记录（``evaluation_agent.normalization``）。

**不包含**大模型 API 调用、小项评分 rubric / Prompt、视觉一致性判定、
趋势判定、建议生成、safety module（自伤 / 自杀等安全风险信号），
也不包含任何安全风险相关字段。
"""

from .base import (
    MAX_ITEM_SCORE,
    MIN_ITEM_SCORE,
    ItemScore,
    LenientSchemaBase,
    NonEmptyStr,
    Score0To100,
    StrictSchemaBase,
    UpstreamSchemaBase,
    ValueStrEnum,
)
from .inputs import DialogueMessage, DialogueRole, EvaluationInput, SELF_REPORT_ROLES
from .multimodal import SessionVisionSummary, VisionState
from .normalization import (
    ItemAssessmentDetails,
    ItemAssessmentRecord,
    ItemScoreNormalizationError,
    build_item_details,
    extract_item_scores,
    normalize_item_score,
)
from .raw_assessment import (
    RESPONSE_SCHEMA_NAME,
    EvidenceList,
    ItemAssessment,
    ModelReplyParseError,
    RawItemScore,
    RawLLMAssessment,
    build_response_json_schema,
    extract_json_object,
    wrap_evidence,
)
from .rubric import (
    FUNCTIONAL_ANCHORS,
    ITEM_RUBRICS,
    RUBRIC_BY_ITEM,
    SYMPTOM_ANCHORS,
    ItemCategory,
    ItemRubric,
    anchors_for,
    get_item_rubric,
)
from .prompt import (
    PROMPT_VERSION,
    ROLE_LABELS_ZH,
    build_messages,
    build_system_prompt,
    build_user_prompt,
    render_prompt_document,
)
from .llm_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    STAGE_DOWNGRADE,
    STAGE_EMPTY_RESPONSE,
    STAGE_NORMALIZE,
    STAGE_PARSE,
    STAGE_TRANSPORT,
    STAGE_VALIDATE,
    ApiStyle,
    AssessmentTrace,
    AttemptTrace,
    EvaluationLLMClient,
    HttpRequest,
    HttpResponse,
    HttpTransport,
    LLMAssessmentResult,
    LLMAuthenticationError,
    LLMConfig,
    LLMConfigurationError,
    LLMError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMRetryableError,
    LLMRetryExhaustedError,
    LLMTransportError,
    StructuredOutputMode,
    TokenUsage,
    UrllibHttpTransport,
    load_env_file,
)
from .service import AssessmentClient, EvaluationService, ScoredAssessment, default_assessment_id
from .schemas import (
    MAX_KEY_FINDINGS,
    MAX_SUGGESTIONS,
    MIN_KEY_FINDINGS,
    MIN_SUGGESTIONS,
    SCHEMA_VERSION,
    DIMENSION_LABELS,
    DIMENSIONS,
    FUNCTIONAL_ITEMS,
    ITEM_KEYS,
    SYMPTOM_ITEMS,
    AssessmentItemScores,
    ConsistencyLevel,
    EvaluationMetadata,
    EvaluationOutput,
    KeyFinding,
    MultimodalObservation,
    OverallLevel,
    OverallStatus,
    PrimaryConcern,
    PsychologicalDimension,
    PsychologicalProfile,
    TrendAndSuggestions,
    TrendDirection,
)
from .scoring import (
    DIMENSION_ITEMS,
    LEVEL_BANDS,
    LEVEL_LABELS_ZH,
    MAX_WEIGHT,
    MEAN_WEIGHT,
    calculate_concern_index,
    calculate_psychological_profile,
    derive_overall_status,
    get_level_label_zh,
    get_overall_level,
    round_half_up,
)

__all__ = [
    # Schema（正式输出契约）
    "SCHEMA_VERSION",
    "MIN_KEY_FINDINGS",
    "MAX_KEY_FINDINGS",
    "MIN_SUGGESTIONS",
    "MAX_SUGGESTIONS",
    "OverallLevel",
    "PsychologicalDimension",
    "ConsistencyLevel",
    "TrendDirection",
    "DIMENSIONS",
    "DIMENSION_LABELS",
    "Score0To100",
    "NonEmptyStr",
    "ItemScore",
    "SYMPTOM_ITEMS",
    "FUNCTIONAL_ITEMS",
    "ITEM_KEYS",
    "AssessmentItemScores",
    "EvaluationMetadata",
    "OverallStatus",
    "PsychologicalProfile",
    "PrimaryConcern",
    "KeyFinding",
    "MultimodalObservation",
    "TrendAndSuggestions",
    "EvaluationOutput",
    # 计算规则（纯函数）
    "MEAN_WEIGHT",
    "MAX_WEIGHT",
    "DIMENSION_ITEMS",
    "LEVEL_BANDS",
    "LEVEL_LABELS_ZH",
    "round_half_up",
    "calculate_psychological_profile",
    "calculate_concern_index",
    "get_overall_level",
    "get_level_label_zh",
    "derive_overall_status",
    # 输入契约
    "DialogueRole",
    "DialogueMessage",
    "EvaluationInput",
    "SELF_REPORT_ROLES",
    # 上游多模态（两级视觉）
    "VisionState",
    "SessionVisionSummary",
    "UpstreamSchemaBase",
    # 大模型原始产出
    "RawItemScore",
    "EvidenceList",
    "wrap_evidence",
    "ItemAssessment",
    "RawLLMAssessment",
    "ModelReplyParseError",
    "extract_json_object",
    "build_response_json_schema",
    "RESPONSE_SCHEMA_NAME",
    # 评分 rubric
    "ItemCategory",
    "ItemRubric",
    "ITEM_RUBRICS",
    "RUBRIC_BY_ITEM",
    "SYMPTOM_ANCHORS",
    "FUNCTIONAL_ANCHORS",
    "anchors_for",
    "get_item_rubric",
    # Prompt 构建
    "PROMPT_VERSION",
    "ROLE_LABELS_ZH",
    "build_system_prompt",
    "build_user_prompt",
    "build_messages",
    "render_prompt_document",
    # DeepSeek 客户端与配置
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "ApiStyle",
    "StructuredOutputMode",
    "STAGE_TRANSPORT",
    "STAGE_EMPTY_RESPONSE",
    "STAGE_PARSE",
    "STAGE_VALIDATE",
    "STAGE_NORMALIZE",
    "STAGE_DOWNGRADE",
    "LLMError",
    "LLMConfigurationError",
    "LLMAuthenticationError",
    "LLMRequestRejectedError",
    "LLMTransportError",
    "LLMResponseError",
    "LLMRetryableError",
    "LLMRetryExhaustedError",
    "LLMConfig",
    "load_env_file",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "UrllibHttpTransport",
    "TokenUsage",
    "AttemptTrace",
    "AssessmentTrace",
    "LLMAssessmentResult",
    "EvaluationLLMClient",
    # 评估服务
    "AssessmentClient",
    "EvaluationService",
    "ScoredAssessment",
    "default_assessment_id",
    # 归一化与后台明细
    "MIN_ITEM_SCORE",
    "MAX_ITEM_SCORE",
    "ItemScoreNormalizationError",
    "normalize_item_score",
    "extract_item_scores",
    "ItemAssessmentRecord",
    "ItemAssessmentDetails",
    "build_item_details",
    # 公共基类与字段类型
    "ValueStrEnum",
    "StrictSchemaBase",
    "LenientSchemaBase",
]

__version__ = "1.0.0"
