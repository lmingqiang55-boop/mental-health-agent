from enum import Enum


class DialogueAction(str, Enum):
    OTHER = "其它"
    EMPATHY = "共情安慰"
    MENTAL_STATUS = "精神状态"
    SLEEP = "睡眠"
    MOOD = "情绪"
    SUICIDE = "自杀倾向"
    SOMATIC = "躯体症状"
    APPETITE = "食欲"
    SOCIAL_FUNCTION = "社会功能"
    INTEREST = "兴趣"
    SCREENING = "筛查"
