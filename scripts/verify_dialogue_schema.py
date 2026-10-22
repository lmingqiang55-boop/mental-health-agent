"""离线检查访谈目标契约，不调用模型。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError
from backend.models.dialogue import DialogueAgentRequest, DialogueDecision
from evaluation_agent.schemas import ITEM_KEYS


def main() -> int:
    for item in ITEM_KEYS:
        request = DialogueAgentRequest.model_validate({
            "conversation_history": [],
            "decision": {"target_item": item, "question_goal": "补充过去两周的频率"},
            "current_user_input": {"text": "一周三四次"},
        })
        assert request.decision.target_item == item
        assert set(request.decision.model_dump()) == {"target_item", "question_goal"}
    ending = DialogueDecision(target_item=None, question_goal="结束访谈")
    assert ending.is_finished
    for value in (
        {"actions": ["睡眠"]},
        {"target_item": "unknown", "question_goal": "了解表现"},
        {"target_item": None, "question_goal": "继续了解"},
        {"target_item": "sleep_disturbance", "question_goal": "结束访谈"},
        {"target_item": "sleep_disturbance", "question_goal": " "},
    ):
        try:
            DialogueDecision.model_validate(value)
        except ValidationError:
            continue
        raise AssertionError(f"Invalid decision was accepted: {value!r}")
    print("PASS: 11 targets, exact two-field contract, closing pair and invalid output rejection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
