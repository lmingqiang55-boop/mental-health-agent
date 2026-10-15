"""多模态一致性：把文字自述的极性与同一句的人脸效价放在一起比对。"""

from __future__ import annotations

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


def test_min_pairs_threshold_is_configurable_for_calibration() -> None:
    result = compute_consistency(
        _input(_user("我很难过", -0.8)),
        ConsistencyThresholds(min_pairs=1),
    )
    assert result.score is not None
    assert result.level is ConsistencyLevel.HIGH
