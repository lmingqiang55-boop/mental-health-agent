"""Conservative checks for answered questions and resolved method references."""

import re

from backend.core.text_signals import predicate_is_negated
from backend.healing.execution import feedback_targets, unresolved_feedback


def question_intent(question):
    if re.search(r"(?:开始|尝试前|执行前|准备).{0,18}(?:困难|难处|顾虑|担心|卡住|最难|不知道怎么办)", question):
        return "starting_difficulty"
    if re.search(r"(?:这件事|眼下|此刻).{0,14}最.{0,4}(?:在意|关心)", question):
        return "current_priority"
    return None


def question_problem(question, text, previous, *, goal_changed=False):
    if not question or previous is None:
        return None
    if not goal_changed:
        already_said = re.search(r"(?:已经|刚才|之前)(?:说过|说清楚|告诉过)", text)
        exhausted = re.search(r"不知道(?:还|再)?能(?:补充|说)(?:什么|啥)|没有(?:什么)?(?:可|能)(?:补充|说)", text)
        if (already_said and exhausted and not predicate_is_negated(text, already_said.start())
                and not predicate_is_negated(text, exhausted.start())):
            return "学生已经说明没有可补充的信息，不继续追问；承接当前回答或无问题暂停"
    if re.search(r"(?:哪(?:一)?个|哪(?:一)?条|哪(?:一)?种).{0,6}(?:方法|建议)|(?:方法|建议).{0,6}(?:哪(?:一)?个|哪(?:一)?条)", question):
        references = previous.suggestions
        ordinal = r"第[一二三四五六七八九十\d]+(?:个|条|种)"
        explicit = re.search(ordinal + r"|两个.{0,5}都|全部|所有", text) or any(
            item.title and item.title in text for item in references)
        if explicit and not unresolved_feedback(text, references) and (
                feedback_targets(text, text, references) or re.search(ordinal, text)):
            return "方法指向已经明确，不要再次询问是哪一个方法"
    if not goal_changed and question_intent(question) in {"starting_difficulty", "current_priority"}:
        answers = [text]
        # Only a substantive answer immediately following this question intent
        # establishes an answered slot. Unknown/refused answers do not.
        for index, message in enumerate(previous.messages[:-1]):
            following = previous.messages[index + 1]
            if message.role == "assistant" and following.role == "user" and question_intent(message.content):
                answers.append(following.content)
        for answer in answers:
            for match in re.finditer(r"(?:最担心|最怕|最难(?:的)?(?:是|就是)|困难是|难处是|卡在|顾虑是).{1,}|"
                    r"(?:已经|刚才|之前|都)(?:说过|告诉过)|(?:没有|没)(?:腾出|留出|抽出)?时间(?:来)?(?:试|尝试|用|开始|做)", answer):
                if not predicate_is_negated(answer, match.start()) and not re.fullmatch(
                        r"(?:最担心|最怕|最难(?:的)?(?:是|就是)|困难是|难处是|卡在|顾虑是)(?:的|是|就是|：|:|\s)*(?:不知道|不清楚)[。！？!?]*", match.group()):
                    return "开始前的困难已经回答，不要换措辞重复追问；承接具体困难或自然收尾"
    return None
