from dataclasses import dataclass


@dataclass(frozen=True)
class ItemDefinition:
    item_id: str
    label: str
    question: str
    clues: tuple[str, ...]


# Prototype prompts explain the measured concepts. They are not a validated
# Chinese translation and must be replaced before a formal administration.
ITEMS = (
    ItemDefinition("item_01", "情绪低落或易怒", "过去两周，你有多少天感到情绪低落、烦躁或没有希望？", ("心情低落", "情绪低落", "难过", "烦躁", "绝望", "心情")),
    ItemDefinition("item_02", "兴趣或愉悦感减退", "过去两周，你有多少天对平时喜欢的事情提不起兴趣？", ("没兴趣", "兴趣", "开心不起来", "提不起兴趣", "不喜欢")),
    ItemDefinition("item_03", "睡眠变化", "过去两周，你有多少天入睡困难、睡不安稳或睡得过多？", ("睡眠", "睡不着", "失眠", "睡不好", "早醒", "睡得过多")),
    ItemDefinition("item_04", "食欲变化", "过去两周，你有多少天食欲不好，或比平时吃得多？", ("食欲", "胃口", "吃不下", "吃得多", "暴食")),
    ItemDefinition("item_05", "疲倦或精力不足", "过去两周，你有多少天感到疲倦或精力不足？", ("精力", "疲倦", "疲惫", "很累", "乏力", "没精神")),
    ItemDefinition("item_06", "自我评价下降", "过去两周，你有多少天觉得自己不好、失败，或让家人失望？", ("失败", "没用", "自责", "让家人失望", "讨厌自己")),
    ItemDefinition("item_07", "注意力下降", "过去两周，你有多少天难以集中注意力，例如学习或阅读时？", ("注意力", "专注", "集中", "走神", "学习不进去")),
    ItemDefinition("item_08", "动作或说话变化", "过去两周，你有多少天动作或说话明显变慢，或坐立不安？", ("变慢", "迟缓", "坐立不安", "动作慢", "说话慢")),
    ItemDefinition("item_09", "自伤相关想法", "过去两周，你有多少天觉得不如死去，或想伤害自己？", ("不如死", "不想活", "自伤", "自杀", "伤害自己", "结束生命")),
)

BY_ID = {item.item_id: item for item in ITEMS}
CATEGORY_SCORE = {
    "not_at_all": 0,
    "several_days": 1,
    "more_than_half_days": 2,
    "nearly_every_day": 3,
}
ANSWER_OPTIONS = "完全没有、有几天、超过一半的天数，还是几乎每天？"
#: The same four options as a list, for a question that must contain exactly one
#: question mark (see question_generator.ensure_single_question).
ANSWER_CHOICES = "完全没有／有几天／超过一半的天数／几乎每天"
