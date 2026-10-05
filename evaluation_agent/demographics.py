"""Read explicitly stated age and grade from the first user answer."""

import re

from evaluation_agent.inputs import DialogueRole, EvaluationInput


_AGE = re.compile(r"(?<!\d)(\d{1,2})(?:周)?岁")
_AGE_WITH_LABEL = re.compile(r"(?:年龄|今年)\s*(?:是|为)?\s*(\d{1,2})(?!\d)")
_GRADE = re.compile(
    r"小学[一二三四五六1-6]年级|初中[一二三1-3]年级|高中[一二三1-3]年级|"
    r"[一二三四五六七八九1-9]年级|初[一二三1-3]|高[一二三1-3]|大[一二三四1-4]"
)


def extract_age_grade(input_data: EvaluationInput) -> tuple[int | None, str | None]:
    """Use the first self-report only; never infer age from grade or vice versa."""
    first_answer = next(
        (item.content for item in input_data.dialogue_history
         if item.role == DialogueRole.USER),
        "",
    )
    age_match = _AGE.search(first_answer) or _AGE_WITH_LABEL.search(first_answer)
    grade_match = _GRADE.search(first_answer.replace(" ", ""))
    age = int(age_match.group(1)) if age_match else None
    return age if age and age <= 99 else None, grade_match.group(0) if grade_match else None
