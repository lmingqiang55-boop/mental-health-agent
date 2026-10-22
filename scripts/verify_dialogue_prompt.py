"""离线检查决策目标、评分细则和访谈表达要求，不调用模型。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.models.dialogue import DialogueAgentRequest
from backend.policy.prompt import POLICY_SYSTEM_PROMPT
from backend.prompts.dialogue_prompt import build_dialogue_user_prompt
from evaluation_agent.rubric import ITEM_RUBRICS


def main() -> int:
    goal = "学生已说明入睡困难，补充过去两周的发生频率"
    request = DialogueAgentRequest.model_validate({
        "conversation_history": [{"role": "assistant", "content": "最近睡眠怎么样？"}],
        "decision": {"target_item": "sleep_disturbance", "question_goal": goal},
        "current_user_input": {"text": "晚上很久才睡着"},
    })
    prompt = build_dialogue_user_prompt(request)
    assert "target_item: sleep_disturbance" in prompt
    assert f"question_goal: {goal}" in prompt
    assert "actions：" not in prompt
    assert prompt.count("晚上很久才睡着") == 1
    for rubric in ITEM_RUBRICS:
        assert rubric.definition in POLICY_SYSTEM_PROMPT
        assert all(value in POLICY_SYSTEM_PROMPT for value in rubric.exclusions)

    request.current_user_input.text = "这部分我不想聊了"
    assert "明确拒绝时只接纳，不追问" in build_dialogue_user_prompt(request)
    request.finish_screening = True
    request.decision.target_item = None
    request.decision.question_goal = "结束访谈"
    closing = build_dialogue_user_prompt(request)
    assert "本轮只收尾，不提出任何问题" in closing

    output = Path(__file__).resolve().parent / "_prompt_samples"
    output.mkdir(exist_ok=True)
    (output / "user_prompt_sample.txt").write_text(prompt, encoding="utf-8")
    print("PASS: target and goal preserved, actual rubrics supplied, refusal and closing boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
