"""共享枚举类型。三人协作中所有模块统一引用，不得各自定义字符串字面量。"""

from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DimensionStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COVERED = "covered"


class SessionStage(str, Enum):
    EXPLORATION = "exploration"       # 实时对话闭环
    CRISIS = "crisis"                 # 危机干预模式
    ASSESSMENT = "assessment"         # 多模态综合评估中
    COMPLETED = "completed"           # 评估完成


class AssessmentDimension(str, Enum):
    """心理评估维度，对应目标图「心理评估维度」。"""
    MOOD = "mood"                     # 情绪
    PRESSURE = "pressure"             # 压力
    INTERPERSONAL = "interpersonal"   # 人际关系
    SELF_COGNITION = "self_cognition" # 自我认知
    STUDY_LIFE = "study_life"         # 学习生活
    DURATION = "duration"             # 持续时间


class RecommendationCategory(str, Enum):
    EMOTION_REGULATION = "emotion_regulation"  # 情绪调节
    STUDY_LIFE = "study_life"                  # 学习生活
    HELP_RESOURCE = "help_resource"            # 求助资源/转介


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
