"""治愈工具箱的心情词表与内容卡片展示字段。

这两件事以前没有测试，而它们都是"错了也不会报错、只会静默筛空"的那一类：

- ``MOOD_LEVEL_TAGS``（按心情档位分组）与 ``MOOD_TAGS``（学生端多选的候选词）
  曾经分散在两个文件里各写一份，漂移了没人发现；
- ``HealContent.category / tags / summary`` 由 ``tag / moods / desc`` 推导，
  推导失效时学生端"按此刻的心情看看"会筛不出任何内容。
"""

from __future__ import annotations

from backend.core.heal_store import HEAL_CONTENTS, recommend_contents
from backend.models.heal import MOOD_LEVEL_TAGS, MOOD_TAGS, HealContent


def test_every_level_tag_is_a_candidate_tag() -> None:
    """档位分组里的词必须都在候选表里，否则那个档位筛不出内容。"""

    candidates = set(MOOD_TAGS)
    assert sorted(MOOD_LEVEL_TAGS) == [1, 2, 3, 4, 5]
    for level, tags in MOOD_LEVEL_TAGS.items():
        assert tags, f"档位 {level} 没有任何标签"
        assert set(tags) <= candidates, sorted(set(tags) - candidates)


def test_every_content_exposes_tags_the_frontend_can_filter_on() -> None:
    """内容卡片的 ``tags`` 必须落在候选表里，否则它永远不会被筛出来。"""

    candidates = set(MOOD_TAGS)
    for content in HEAL_CONTENTS:
        assert content.tags, content.id
        assert set(content.tags) <= candidates, (content.id, sorted(set(content.tags) - candidates))


def test_heal_content_fills_the_fields_the_student_page_reads() -> None:
    """分类取 ``tag``、简介取 ``desc``、标签由 ``moods`` 推导。"""

    derived = HealContent(
        id="hc_test", title="测试", tag="呼吸", type="breath",
        cover="doc", desc="跟着做三分钟。", moods=[1, 2],
    )
    assert derived.category == "呼吸"
    assert derived.summary == "跟着做三分钟。"
    assert derived.tags == list(MOOD_LEVEL_TAGS[1]) + [
        word for word in MOOD_LEVEL_TAGS[2] if word not in MOOD_LEVEL_TAGS[1]
    ]

    explicit = HealContent(
        id="hc_test2", title="测试", tag="呼吸", type="breath", cover="doc",
        desc="跟着做三分钟。", moods=[1], category="放松训练", summary="短简介",
    )
    assert explicit.category == "放松训练"
    assert explicit.summary == "短简介"


def test_recommending_by_mood_prefers_contents_for_that_level() -> None:
    """按档位推荐走的是 ``moods``；一旦有命中，返回的就该全是命中项。"""

    for level in MOOD_LEVEL_TAGS:
        items = recommend_contents(mood=level)
        hits = [item for item in items if level in item.moods]
        assert hits, f"档位 {level} 一个内容都没有"
        assert len(items) == len(hits)
        assert all(level in item.moods for item in items)
