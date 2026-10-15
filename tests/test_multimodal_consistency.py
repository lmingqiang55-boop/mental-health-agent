"""多模态一致性：把文字自述的极性与同一句的人脸效价放在一起比对。"""

from __future__ import annotations

import pytest

from backend.core.multimodal_consistency import compute_consistency
from backend.core.text_polarity import is_whole_sentence_denial, text_polarity
from backend.core.vision_thresholds import ConsistencyThresholds
from evaluation_agent.inputs import EvaluationInput
from evaluation_agent.schemas import ConsistencyLevel


def _user(text: str, valence: float | None, *, face: bool = True) -> dict:
    snapshot: dict = {"face_detected": face}
    if valence is not None:
        snapshot["valence"] = valence
    return {"role": "user", "content": text, "vision_snapshot": snapshot}


def _input(*messages: dict) -> EvaluationInput:
    return EvaluationInput.model_validate({"dialogue_history": list(messages)})


def test_text_polarity_reads_direction_and_negation() -> None:
    assert text_polarity("我很难过") < -0.5
    assert text_polarity("我最近很开心") > 0.5
    # 否定必须翻转极性，否则"不开心"会被读成正分。
    assert text_polarity("不开心") < 0.0
    assert text_polarity("") is None
    assert text_polarity("嗯，我在") is None


def test_pure_denial_reads_as_mildly_positive_not_negative() -> None:
    """「我没事」是本人对自己状态的否认，按弱正向读，不能算成负分。

    这是"嘴上说没事、脸上难过"能被核对通道抓到的前提：若读成负分或读不出，
    文字与表情就朝同一个方向，矛盾永远发现不了。
    """

    for phrase in ("没有", "没", "没事", "没事儿", "我没事", "没什么", "没啥", "没关系",
                   "没什么大不了的", "没事的"):
        value = text_polarity(phrase)
        assert value is not None, phrase
        assert 0.0 < value < 0.5, phrase
    # "还没"意思是"尚未"，不是"我没事"，别被剥成正向。
    assert text_polarity("还没呢") is None
    # 剥掉语气词也不能把"尚未"变成"我没事"：这两句和"还没呢"是同一层意思，
    # 只差一个"还"，读法必须一致（拿不准就返回 None）。
    assert text_polarity("没呢") is None
    assert text_polarity("没有呢") is None
    # 句中出现的否认片段不适用整句规则，仍走词典路径（这里没有情绪词）。
    assert text_polarity("没有烦心事") is None


def test_whole_sentence_denial_helper_matches_the_reading() -> None:
    """报告侧排除用的判定必须和极性读法同一套，不能各判各的。"""

    for phrase in ("没有", "没", "没事", "我没事", "没什么", "没关系", "没什么大不了的"):
        assert is_whole_sentence_denial(phrase), phrase
        assert text_polarity(phrase) is not None, phrase
    for phrase in ("还没呢", "没呢", "没有呢", "没有烦心事", "我很难过", "今天考了三门", ""):
        assert not is_whole_sentence_denial(phrase), phrase


def test_text_polarity_falls_back_to_ontology_words() -> None:
    """「迷茫」只在 DLUT 本体里，知网给它 0 分，兜底路径要能读出负向。"""

    assert text_polarity("我很迷茫") < 0.0


def test_whole_sentence_denials_do_not_enter_the_consistency_score() -> None:
    """整句否认不参与会话级一致性分数（报告口径的决定，见模块 docstring）。

    ``text_polarity`` 为了单句核对把"我没事"读成弱正向；如果这个分数也采用，
    普通筛查里大量的"没有"就会跟偏低的脸色凑成一对对"不一致"，把分数系统性压低。
    排除之后这里应当回到"没得比、不给分"，并在 summary 里说清排除了 2 句。
    """

    result = compute_consistency(_input(
        _user("没有", -0.31),
        _user("没事", -0.31),
    ))
    assert result.score is None
    assert result.level is ConsistencyLevel.UNKNOWN
    assert result.pairs == ()
    assert result.considered_turns == 2
    assert "整句否认" in result.summary
    assert "没有分数不等于" in result.summary


def test_denials_are_excluded_while_normal_sentences_still_count() -> None:
    """排除的是否认句，不是整场会话；正常句子照算，排除了几句要写在 summary 里。"""

    result = compute_consistency(_input(
        _user("没有", -0.8),
        _user("我最近很难过", -0.8),
        _user("没什么", -0.8),
        _user("压力很大", -0.6),
    ))
    assert result.score is not None and result.score >= 80
    assert len(result.pairs) == 2
    assert result.considered_turns == 4
    assert "另有 2 句是整句否认" in result.summary


def test_consistency_is_high_when_both_signals_point_the_same_way() -> None:
    result = compute_consistency(_input(
        _user("我最近很难过", -0.8),
        _user("压力很大", -0.6),
    ))
    assert result.score is not None
    assert result.score >= 80
    assert result.level is ConsistencyLevel.HIGH
    assert "视觉" in result.summary
    assert len(result.pairs) == 2


def test_consistency_is_low_when_the_signals_point_opposite_ways() -> None:
    result = compute_consistency(_input(
        _user("我最近很开心", -0.8),
        _user("我挺开心的", -0.5),
    ))
    assert result.score is not None
    assert result.score < 60
    assert result.level is ConsistencyLevel.LOW
    assert "不代表诊断置信度" in result.summary
    assert "不表示受访者是否诚实" in result.summary


def test_consistency_stays_unknown_when_there_are_too_few_pairs() -> None:
    result = compute_consistency(_input(
        _user("我很难过", -0.8),
        {"role": "assistant", "content": "这种情况多久了？"},
    ))
    assert result.score is None
    assert result.level is ConsistencyLevel.UNKNOWN
    assert result.considered_turns == 1
    assert "视觉" in result.summary
    assert "没有分数不等于" in result.summary


def test_consistency_ignores_turns_without_a_detected_face() -> None:
    result = compute_consistency(_input(
        _user("我很难过", None, face=False),
        _user("压力很大", None, face=False),
    ))
    assert result.score is None
    assert result.considered_turns == 0
    assert "没有一句" in result.summary


def test_consistency_reports_how_many_turns_it_could_compare() -> None:
    result = compute_consistency(_input(
        _user("我很难过", -0.8),
        _user("压力很大", -0.7),
        _user("今天考了三门", -0.7),  # 一句情绪词都没有，读不出极性
    ))
    assert result.score is not None
    assert len(result.pairs) == 2
    assert result.considered_turns == 3
    assert "另有 1 句" in result.summary


def test_colloquial_words_fill_the_single_character_gap() -> None:
    """知网与本体都只收双字及以上的词，"累/烦/困"这类单字靠口语词表补上。"""

    assert text_polarity("我最近很累") < -0.5
    assert text_polarity("心累") < 0.0
    assert text_polarity("有点烦") < 0.0
    assert text_polarity("心里挺沉的") < 0.0


def test_adverb_prefix_survives_as_an_intensifier() -> None:
    """「好烦」里的"好"是"很"，不能被当成正向词，否则整句方向会被抵消掉。"""

    assert text_polarity("好烦") < text_polarity("烦")
    assert text_polarity("好累") < text_polarity("累")
    assert text_polarity("我很好") > 0.5


def test_lukewarm_answers_read_as_mildly_positive() -> None:
    """"还好""还行"是暧昧的肯定，读成弱正向——这是核对通道能成立的前提。"""

    assert 0.0 < text_polarity("还好") < 0.5
    assert 0.0 < text_polarity("还行") < 0.5
    assert 0.0 < text_polarity("挺好的") < 0.5


def test_jieba_splitting_does_not_silence_the_spoken_word_lists() -> None:
    """口语词表里被 jieba 拆开的写法必须仍然读得出极性。

    两张口语词表是按"学生实际会怎么说"写的，jieba 并不认识它们：实测 25 条被拆成
    几段（"心情不好" → ["心情","不好"]、"提不起劲" → ["提不起","劲"]、"想哭" →
    ["想","哭"]），拆完每一段都不在词表里，整句直接返回 None——词表白写。
    :func:`_merge_spoken_compounds` 负责把它们合回去。
    """

    for phrase in ("心情不好", "提不起劲", "想哭", "没精神", "浑身没劲", "喘不过气", "心里堵"):
        assert text_polarity(phrase) is not None and text_polarity(phrase) < 0.0, phrase
    for phrase in ("有精神", "睡得好", "还不错"):
        assert text_polarity(phrase) is not None and text_polarity(phrase) > 0.0, phrase


def test_lukewarm_word_is_not_doubled_by_its_own_adverb() -> None:
    """"还行"要被当成一个词，不能被"还"按程度副词翻倍。

    jieba 把"还行"切成 ["还","行"]，"还"在知网里是程度副词（2.0），于是"行"被加倍，
    实测读成 +0.32，正好是文档里那一档（0.5，与"还好"同级 → +0.16）的两倍。
    量纲偏一倍会让后面按文档校准的阈值算错，所以这里把两者钉成同一档。
    """

    assert text_polarity("还行") == pytest.approx(text_polarity("还好"))
    assert text_polarity("还行") < 0.25


@pytest.mark.parametrize("phrase", ["我没事，真的", "我最近没事", "我觉得没事",
                                    "我没什么大不了的", "没事的啦"])
def test_natural_denial_variants_still_read_as_mildly_positive(phrase: str) -> None:
    r"""否认句多一个逗号、人称或语气词，读法不能反过来。

    这些是最自然的说法。修之前它们会落回词典路径、被本体当负向词读成 ``-0.32``
    （"我没什么大不了的"是 ``-0.58``），于是"嘴上说没事、脸上难过"抓不到，
    "整句否认不计入会话级分数"的排除规则对它们也不生效。
    """

    value = text_polarity(phrase)
    assert value is not None and 0.0 < value < 0.5, phrase
    assert is_whole_sentence_denial(phrase), phrase


@pytest.mark.parametrize("phrase", ["我不是没事", "我没有说没事", "我不觉得没事"])
def test_denying_a_denial_reads_negative(phrase: str) -> None:
    """「否认自己的否认」= 我不好，不能读成弱正向。

    按"奇数个否定词翻转"的老规则，这类句子会被读成 ``+0.32``，配上难过的脸
    就触发一次假核对——正是"拿摄像头的猜测反驳学生诉苦"那条禁忌。
    """

    assert text_polarity(phrase) is not None and text_polarity(phrase) < 0.0, phrase


def test_negation_scope_stops_at_the_word_it_negates() -> None:
    """否定只作用于它后面的那个词，不能一路管到句尾。"""

    # 修之前"没有"会一路管到"没事"，把诉苦读成正向。
    assert text_polarity("我没有说没事") < 0.0
    # 同一个意思的两种说法必须同向（修之前一个是 -0.32、一个是 +0.32）。
    assert text_polarity("没什么问题") > 0.0
    assert text_polarity("没问题") > 0.0
    # 被 jieba 粘成一个词的"不 + 程度副词 + 情绪词"要切开，不能整句读不出。
    assert text_polarity("我不太好") < 0.0
    assert text_polarity("我心情不太好") < 0.0
    # 正常否定不受影响。
    assert text_polarity("我没有不开心") > 0.0
    assert text_polarity("不差") > 0.0


def test_min_pairs_threshold_is_configurable_for_calibration() -> None:
    result = compute_consistency(
        _input(_user("我很难过", -0.8)),
        ConsistencyThresholds(min_pairs=1),
    )
    assert result.score is not None
    assert result.level is ConsistencyLevel.HIGH


@pytest.mark.parametrize("min_pairs", [0, -1])
def test_zero_min_pairs_gives_no_score_instead_of_dividing_by_zero(min_pairs: int) -> None:
    """这个旋钮是文档化的可调项，配成 0 不能让报告接口崩。

    空配对时 ``len(matched) < limits.min_pairs`` 对 0 不成立，会一路走到
    ``/ len(matched)``，抛 ZeroDivisionError——评估报告接口一次 500。
    """

    result = compute_consistency(
        _input(_user("嗯，我在", -0.3)),  # 读不出极性 → 一个可比的句子都没有
        ConsistencyThresholds(min_pairs=min_pairs),
    )
    assert result.score is None
    assert result.level is ConsistencyLevel.UNKNOWN


def test_from_env_never_yields_a_useless_min_pairs(monkeypatch) -> None:
    monkeypatch.setenv("CONSISTENCY_MIN_PAIRS", "0")
    assert ConsistencyThresholds.from_env().min_pairs == 1
