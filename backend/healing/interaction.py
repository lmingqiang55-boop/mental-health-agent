"""Conversation style and goal tracking, separate from knowledge eligibility.

UNICEF's three conversation-starter articles inform listening/wording only.
Parent roles and source ages are never transferred to the assistant or methods.
"""

import re

from backend.core.text_signals import predicate_is_negated
from backend.models.healing import HealingBackground, HealingMemory, Scene, SupportGoal

SCENE_WORDS = {
    "study_stress": ("考试", "测验", "考前", "紧张", "学习压力", "作业", "课业", "成绩", "复习", "升学", "压力"),
    "sleep": ("睡", "失眠", "熬夜", "晚睡", "早醒", "犯困", "很困"),
    "relationships": ("朋友", "同学", "同桌", "舍友", "关系", "争吵", "吵架", "孤独", "排斥", "人际", "冲突"),
    "low_mood": ("低落", "难过", "伤心", "沮丧", "烦躁", "心情差", "提不起劲", "开心不起来", "情绪", "兴趣", "没动力"),
}
SCENE_LABELS = {"study_stress": "学习或考试的压力", "sleep": "睡觉的困扰",
                "relationships": "和别人相处的烦恼", "low_mood": "心情的变化"}
WEAK_WORDS = {"紧张", "压力", "情绪", "兴趣"}
TOPIC_WORDS = sorted({word for words in SCENE_WORDS.values() for word in words} |
                     {"睡眠", "学习", "焦虑", "相处", "社交"}, key=lambda word: (-len(word), word))
TOPIC_PHRASE = r"(?:(?:" + "|".join(map(re.escape, TOPIC_WORDS)) + r")|的|和|与|或|方面|之间|相关|任何|什么){1,8}"
DENIED_CONCERNS = [
    re.compile(r"(?:并非|不是|并没有|没有|不存在|并无|没)(?:关于|有关|因为)?" +
               TOPIC_PHRASE + r"(?:问题|困扰|烦恼|矛盾)"),
    re.compile(TOPIC_PHRASE + r"(?:并没有|没有|不存在|并无|没)(?:任何|什么|明显|太大)?(?:问题|困扰|烦恼|矛盾|压力)"),
    re.compile(r"(?:不是|并非)(?:因为|关于)?" + TOPIC_PHRASE + r"(?=$|[，,。！？；\n]|而是|但是|但|可是)"),
    re.compile(r"(?:不想|不愿意|不愿|不要|不)(?:先|再)?(?:聊聊|聊|谈|讨论|关注|处理|解决)(?:一下|关于)?" + TOPIC_PHRASE),
    re.compile(r"(?:并不|不再|并非|不是|并没有|没有|不|没)(?:(?:觉得|感到|感觉|那么|特别|很|太|再|有)){0,3}"
               r"(?:学习压力|紧张|焦虑|低落|难过|伤心|沮丧|烦躁|孤独|失眠|压力)"),
]
STYLE_INSTRUCTIONS = {
    "simple": "用短句和日常词，从学生说过的一件具体小事接话；一次只问一件容易回答的事。"
              "避免抽象术语、长段解释、说教和夸张表扬。不扮演父母，不假称能现实陪伴。",
    "conversational": "像自然聊天一样承认感受，尊重学生的看法；避免连环审问、与别人比较、"
                      "评判或替学生归责。用一个简短问题了解自己的想法或开始的困难。",
    "autonomous": "尊重自主性和学生明确的优先方向，用开放而简短的问题澄清其含义。"
                  "避免争辩、控制讨论、命令或替学生决定。允许学生不回答或暂停。",
    "unknown": "年龄与学段未知。用简洁通俗的话，接住学生已经说出的经历；不猜年龄、年级或发育情况。",
}


def communication_style(background: HealingBackground) -> str:
    if background.age is not None:
        return "simple" if background.age <= 10 else "conversational" if background.age <= 13 else "autonomous"
    return {"primary": "simple", "middle": "conversational", "high": "autonomous"}.get(background.school_stage, "unknown")


def positive_concern_text(text: str) -> str:
    """Mask explicit denials, preserving offsets and actual difficulties.

    Missing sleep/friends and unresolved problems still count as concerns;
    only denied problems, feelings or discussion requests are removed.
    """
    spans = []
    for pattern in DENIED_CONCERNS:
        for match in pattern.finditer(text):
            if not re.search(r"(?:不是|并非)$", text[:match.start()].rstrip()):
                spans.append((match.start(), match.end()))
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def mentioned_scenes(text: str) -> list[Scene]:
    text = positive_concern_text(text)
    scores = {scene: sum(text.count(word) * (1 if word in WEAK_WORDS else 2) for word in words)
              for scene, words in SCENE_WORDS.items()}
    # "关系很紧张" is a relationship concern, not automatically exam anxiety.
    strong = [scene for scene, words in SCENE_WORDS.items()
              if any(word in text for word in words if word not in WEAK_WORDS)]
    eligible = strong or [scene for scene, score in scores.items() if score]
    return sorted(eligible, key=lambda scene: -scores[scene])


def resolve_goal(text: str, memory: HealingMemory | None = None,
                 previous: SupportGoal | None = None) -> SupportGoal:
    positive_text = positive_concern_text(text)
    scenes = mentioned_scenes(positive_text)
    # Limit to the prioritized clause; later background must not outvote it.
    priority = re.search(r"(?:最(?:让我)?(?:困扰|烦恼|担心|想解决|想聊|在意|难受)(?:的)?(?:是)?|"
                         r"(?:现在|目前)?(?:更想|只想|优先|先)(?:聊聊|聊|谈|解决|处理|关注)(?:一下)?|"
                         r"(?:换成|改聊|想聊的是))\s*[：:]?([^，。；！？\n]+)", positive_text)
    if priority:
        matches = mentioned_scenes(priority.group(1))
        if matches:
            chosen = min(matches, key=lambda scene: min(
                (priority.group(1).find(word) for word in SCENE_WORDS[scene] if word in priority.group(1)),
                default=10000))
            return SupportGoal(scene=chosen, mentioned_scenes=list(dict.fromkeys([*scenes, chosen])),
                               evidence=priority.group(0))
    if previous and previous.needs_confirmation:
        if len(scenes) == 1:
            return SupportGoal(scene=scenes[0], mentioned_scenes=previous.mentioned_scenes, evidence=text)
        return previous.model_copy(deep=True)
    if previous and previous.scene != "general":
        # Mentioning sleep as context for an exam does not silently change goals.
        return previous.model_copy(deep=True)
    if len(scenes) > 1:
        return SupportGoal(mentioned_scenes=scenes, needs_confirmation=True)
    if scenes:
        return SupportGoal(scene=scenes[0], mentioned_scenes=scenes, evidence=text)
    if memory is not None:
        denied = {scene for scene, words in SCENE_WORDS.items()
                  if any(word in text for word in words) and not any(word in positive_text for word in words)}
        profile = memory.assessment.psychological_profile
        if "sleep" not in denied and profile.sleep_energy > 0 and memory.assessment.report.primary_concern.dimension.value == "sleep_energy":
            return SupportGoal(scene="sleep")
        if "low_mood" not in denied and (profile.emotion > 0 or profile.interest_motivation > 0):
            return SupportGoal(scene="low_mood")
    return SupportGoal()


def confirmation_question(goal: SupportGoal) -> str:
    labels = "、".join(SCENE_LABELS[scene] for scene in goal.mentioned_scenes if scene in SCENE_LABELS)
    return f"你提到了{labels}，眼下最想先聊哪一件？"


def ending_requested(text: str) -> bool:
    """A refused topic is not an exit; an explicit exit still takes effect.

    Require a clause boundary after a general refusal to talk. A following
    object such as 睡眠 or 昨天的事 limits the refusal to that topic, regardless
    of whether resolve_goal recognizes it or switches the current scene.
    """
    boundary = r"(?=\s*(?:$|[，,。！？!?；;\n]))"
    ending = re.compile(
        r"(?:不想|不愿意|不愿)(?:再|继续)?(?:聊天|聊|说话|说|对话|陪伴)(?:下去)?了?" + boundary +
        r"|不想继续了?" + boundary + r"|不聊了|结束吧|(?:先到这里|先这样)" + boundary + r"|再见")
    return any(not predicate_is_negated(text, match.start()) for match in ending.finditer(text))


def pause_signal(text: str) -> bool | None:
    """Honor the latest pause request or retraction in the original answer."""
    requested = None
    denial = re.compile(r"(?:不用|不必|不需要|无需)(?:(?:再|现在|今天|立刻|马上)\s*)*$")
    for match in re.finditer("先暂停", text):
        negated = predicate_is_negated(text, match.start())
        additional_denial = denial.search(text[:match.start()].rstrip())
        if additional_denial and not predicate_is_negated(text, additional_denial.start()):
            negated = True
        requested = not negated
    return requested


def uninformative_answer(text: str) -> bool:
    canonical = re.sub(r"[\s，。！？!?,.]", "", text)
    small = {"不知道", "不清楚", "没什么", "嗯", "不知道说什么", "没啥", "随便"}
    return canonical in small


def repeated_answer(text: str, messages) -> bool:
    """Pause on consecutive non-informative answers, including synonyms."""
    if not uninformative_answer(text):
        return False
    users = [message.content for message in messages if message.role == "user"]
    return bool(users and uninformative_answer(users[-1]))
