"""访谈决策契约：只规划一个评估小项，或明确结束访谈。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evaluation_agent.rubric import get_item_rubric
from evaluation_agent.schemas import ITEM_KEYS

AssessmentItem = Literal[*ITEM_KEYS]
MAX_INTERVIEW_TURNS = 35
END_INTERVIEW = "结束访谈"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_item: AssessmentItem | None
    question_goal: str = Field(min_length=1, max_length=1000, strict=True)

    @field_validator("question_goal")
    @classmethod
    def nonblank_goal(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question_goal must not be blank")
        return value

    @model_validator(mode="after")
    def valid_ending(self) -> "PolicyDecision":
        if (self.target_item is None) != (self.question_goal == END_INTERVIEW):
            raise ValueError('结束时必须同时返回 target_item=null 和 question_goal="结束访谈"')
        return self

    @property
    def is_finished(self) -> bool:
        return self.target_item is None

    @property
    def target_label(self) -> str:
        return (END_INTERVIEW if self.target_item is None
                else get_item_rubric(self.target_item).label_zh)
