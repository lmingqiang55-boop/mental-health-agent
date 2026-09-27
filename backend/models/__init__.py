"""数据模型层统一导出。所有模块通过 ``backend.models`` 引用公共数据结构。"""

from backend.models.assessment import (
    AssessmentRecord,
    AssessmentResult,
    CommunicationMessage,
    CounselorNote,
    DimensionScore,
    Recommendation,
)
from backend.models.enums import (
    AssessmentDimension,
    ConsentStatus,
    DimensionStatus,
    FollowUpStatus,
    MessageRole,
    ModalityType,
    RecommendationCategory,
    RiskLevel,
    SessionStage,
)
from backend.models.requests import (
    AudioUpsertRequest,
    ChatRequest,
    ConsentRequest,
    SendCommunicationRequest,
    TriggerAssessmentRequest,
    VisionUpsertRequest,
)
from backend.models.responses import (
    AssessmentResponse,
    ChatResponse,
    CommunicationListResponse,
    ConsentResponse,
    CreateSessionResponse,
    DialogueResponsePayload,
    ErrorDetail,
    ErrorResponse,
    HistoryListResponse,
    SendCommunicationResponse,
    StateUpsertResponse,
)
from backend.models.states import (
    AudioState,
    ConsentRecord,
    Message,
    RiskResult,
    SessionAudioSummary,
    SessionState,
    SessionVisionSummary,
    VisionState,
)

__all__ = [
    # enums
    "AssessmentDimension", "ConsentStatus", "DimensionStatus",
    "FollowUpStatus", "MessageRole", "ModalityType",
    "RecommendationCategory", "RiskLevel", "SessionStage",
    # states
    "AudioState", "ConsentRecord", "Message", "RiskResult",
    "SessionAudioSummary", "SessionState", "SessionVisionSummary",
    "VisionState",
    # assessment
    "AssessmentRecord", "AssessmentResult", "CommunicationMessage",
    "CounselorNote", "DimensionScore", "Recommendation",
    # requests
    "AudioUpsertRequest", "ChatRequest", "ConsentRequest",
    "SendCommunicationRequest", "TriggerAssessmentRequest",
    "VisionUpsertRequest",
    # responses
    "AssessmentResponse", "ChatResponse", "CommunicationListResponse",
    "ConsentResponse", "CreateSessionResponse", "DialogueResponsePayload",
    "ErrorDetail", "ErrorResponse", "HistoryListResponse",
    "SendCommunicationResponse", "StateUpsertResponse",
]
