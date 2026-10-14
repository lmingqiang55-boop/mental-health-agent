"""多模态一致性：把文字自述的极性与同一句的人脸效价放在一起比对。"""

from __future__ import annotations

from backend.core.multimodal_consistency import compute_consistency
from backend.core.text_polarity import text_polarity
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


def test_text_polarity_ignores_pure_denial_answers() -> None:
    """「没有」是回答里的否定词，不是情绪词，不该被算成负分。"""

    assert text_polarity("没有") is None
    assert text_polarity("没有烦心事") is None


def test_text_polarity_falls_back_to_ontology_words() -> None:
    """「迷茫」只在 DLUT 本体里，知网给它 0 分，兜底路径要能读出负向。"""

    assert text_polarity("我很迷茫") < 0.0


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
