"""数据模型层统一导出。所有模块通过 ``backend.models`` 引用公共数据结构。"""

from backend.models.assessment import (
    CommunicationMessage,
    CounselorNote,
)
from backend.models.dialogue import (
    DialogueAgentRequest,
    DialogueAgentResponse,
    DialogueCurrentUserInput,
    DialogueDecision,
    DialogueHistoryMessage,
    DialogueUserMemory,
    DialogueVisual,
)
from backend.models.evaluation import EvaluationRecord, EvaluationResult
from backend.models.heal import FocusSession, HabitRecord, HealContent, MoodEntry
from backend.models.enums import (
    ConsentStatus,
    FollowUpStatus,
    MessageRole,
    ModalityType,
    RiskLevel,
    SessionStage,
)
from backend.models.requests import (
    AudioUpsertRequest,
    ChatRequest,
    ConsentRequest,
    FocusLogRequest,
    HabitCheckinRequest,
    SaveMoodRequest,
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
    FocusListResponse,
    FocusLogResponse,
    GrowthResponse,
    HabitCheckinResponse,
    HabitListResponse,
    HealContentsResponse,
    HistoryListResponse,
    MoodListResponse,
    SaveMoodResponse,
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
    "ConsentStatus",
    "FollowUpStatus", "MessageRole", "ModalityType",
    "RiskLevel", "SessionStage",
    # states
    "AudioState", "ConsentRecord", "Message", "RiskResult",
    "SessionAudioSummary", "SessionState", "SessionVisionSummary",
    "VisionState",
    # assessment
    "CommunicationMessage", "CounselorNote",
    "EvaluationRecord", "EvaluationResult",
    # heal journal
    "MoodEntry", "HabitRecord", "FocusSession", "HealContent",
    # requests
    "AudioUpsertRequest", "ChatRequest", "ConsentRequest",
    "SaveMoodRequest", "HabitCheckinRequest", "FocusLogRequest",
    "SendCommunicationRequest", "TriggerAssessmentRequest",
    "VisionUpsertRequest",
    # responses
    "AssessmentResponse", "ChatResponse", "CommunicationListResponse",
    "ConsentResponse", "CreateSessionResponse", "DialogueResponsePayload",
    "ErrorDetail", "ErrorResponse", "HistoryListResponse",
    "SaveMoodResponse", "MoodListResponse", "HabitCheckinResponse",
    "HabitListResponse", "FocusLogResponse", "FocusListResponse",
    "HealContentsResponse", "GrowthResponse",
    "SendCommunicationResponse", "StateUpsertResponse",
    # dialogue agent schemas
    "DialogueVisual", "DialogueHistoryMessage", "DialogueUserMemory",
    "DialogueDecision", "DialogueCurrentUserInput",
    "DialogueAgentRequest", "DialogueAgentResponse",
]
