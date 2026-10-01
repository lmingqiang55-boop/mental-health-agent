"""未成年人评估提示词的关键边界。"""

from evaluation_agent.prompt import PROMPT_VERSION, build_system_prompt
from evaluation_agent.rubric import ITEM_RUBRICS


def test_minor_prompt_uses_student_report_without_vision_scoring() -> None:
    prompt = build_system_prompt()
    assert PROMPT_VERSION == "1.2"
    assert "上游必须确认“用户”角色就是被评估学生" in prompt
    assert "`user_memory` 仅提供背景" in prompt
    assert "句级视觉指标与会话级视觉汇总不用于这 11 项评分" in prompt
    assert "视觉信息缺失不等于状态正常" in prompt

    psychomotor = next(item for item in ITEM_RUBRICS
                       if item.item == "psychomotor_change")
    mood = next(item for item in ITEM_RUBRICS
                if item.item == "depressed_mood")
    assert all("视觉" not in signal for signal in psychomotor.signals)
    assert any("视觉指标" in exclusion for exclusion in psychomotor.exclusions)
    assert any("烦躁" in signal for signal in mood.signals)
