"""共享枚举类型。三人协作中所有模块统一引用，不得各自定义字符串字面量。"""

from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SessionStage(str, Enum):
    EXPLORATION = "exploration"       # 实时对话闭环
    CRISIS = "crisis"                 # 危机干预模式
    ASSESSMENT = "assessment"         # 多模态综合评估中
    COMPLETED = "completed"           # 评估完成


class ConsentStatus(str, Enum):
    NOT_PROVIDED = "not_provided"
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


class FollowUpStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class ModalityType(str, Enum):
    VISION = "vision"
    AUDIO = "audio"
    TEXT = "text"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    COUNSELOR = "counselor"  # 心理老师人工消息，与 AI 消息区分
    SYSTEM = "system"
