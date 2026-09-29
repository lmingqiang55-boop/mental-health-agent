from fastapi.testclient import TestClient

from backend.assessment.engine import AssessmentEngine
from backend.assessment.models import build_report
from backend.main import app


client = TestClient(app)


def test_nine_confirmed_answers_produce_auditable_total() -> None:
    state, first_question = AssessmentEngine().start()
    assert "过去两周" in first_question
    engine = AssessmentEngine()
    answers = (
        "完全没有", "有几天", "超过一半的天数", "几乎每天",
        "完全没有", "有几天", "超过一半的天数", "几乎每天", "完全没有",
    )
    for answer in answers:
        state, _ = engine.process(state, answer)

    report = build_report(state)
    assert report.status == "complete"
    assert report.mapped_total == 12
    assert report.confirmed_count == 9
    assert report.pending_items == []
    assert report.items["item_03"].score == 2
    assert report.items["item_03"].evidence_quote == "超过一半的天数"
    assert report.items["item_03"].evidence_turn_id == 3


def test_spontaneous_clues_change_question_order_without_inventing_scores() -> None:
    engine = AssessmentEngine()
    state, _ = engine.start()
    state, reply = engine.process(state, "这两周几乎每天心情低落，睡眠也不好。")
    assert state.items["item_01"].score == 3
    assert state.items["item_03"].score is None
    assert state.current_item_id == "item_03"
    assert "睡" in reply

    state, _ = engine.process(state, "这两周大约十天睡不好")
    assert state.items["item_03"].status == "needs_clarification"
    assert state.items["item_03"].score is None
    assert build_report(state).mapped_total is None

    state, _ = engine.process(state, "超过一半的天数")
    assert state.items["item_03"].score == 2
    assert state.current_item_id == "item_02"


def test_unrelated_school_preference_and_old_history_do_not_score() -> None:
    engine = AssessmentEngine()
    state, _ = engine.start()
    state.current_item_id = "item_02"
    state, reply = engine.process(state, "我不喜欢数学课")
    assert state.items["item_02"].score is None
    assert "平时喜欢的活动" in reply

    state.current_item_id = "item_07"
    state, _ = engine.process(state, "去年备考时很难集中")
    assert state.items["item_07"].score is None
    assert state.items["item_07"].evidence_history[-1].period == "other"


def test_conflicting_answer_is_kept_and_requires_resolution() -> None:
    engine = AssessmentEngine()
    state, _ = engine.start()
    state.current_item_id = "item_03"
    state, _ = engine.process(state, "完全没有睡眠问题")
    assert state.items["item_03"].score == 0

    state, reply = engine.process(state, "昨天说没问题，但其实这两周几乎每天失眠")
    assert state.items["item_03"].status == "needs_clarification"
    assert state.items["item_03"].conflict is True
    assert state.items["item_03"].score is None
    assert state.current_item_id == "item_03"
    assert "不一致" in reply
    assert len(state.items["item_03"].evidence_history) == 2

    state, _ = engine.process(state, "几乎每天")
    assert state.items["item_03"].score == 3
    assert state.items["item_03"].conflict is False
    assert len(state.items["item_03"].evidence_history) == 3


def test_hopelessness_is_not_read_as_a_zero_answer() -> None:
    engine = AssessmentEngine()
    state, _ = engine.start()
    state, _ = engine.process(state, "这两周我觉得没有希望")
    assert state.items["item_01"].score is None
    assert state.current_item_id == "item_01"

    state, _ = engine.start()
    state, _ = engine.process(state, "她这两周几乎每天心情低落")
    assert state.items["item_01"].score is None

    state, _ = engine.start()
    state.current_item_id = "item_03"
    state, _ = engine.process(state, "这两周完全没有睡眠问题，但又几乎每天睡不好")
    assert state.items["item_03"].score is None


def test_self_harm_signal_pauses_and_never_fills_missing_items() -> None:
    engine = AssessmentEngine()
    state, _ = engine.start()
    state, reply = engine.process(state, "我现在想伤害自己")
    assert state.status == "safety_paused"
    assert state.safety_flag == "urgent"
    assert build_report(state).mapped_total is None

    state, _ = engine.start()
    state, _ = engine.process(state, "我不想自杀，但我现在想伤害自己")
    assert state.status == "safety_paused"
    assert state.safety_flag == "urgent"
    assert "暂停" in reply

    state, _ = engine.start()
    state.current_item_id = "item_09"
    state, _ = engine.process(state, "有几天")
    assert state.items["item_09"].score == 1
    assert state.safety_flag == "needs_review"
    assert state.status == "safety_paused"
    assert build_report(state).mapped_total is None


def test_stopping_preserves_partial_answers_without_a_total() -> None:
    engine = AssessmentEngine()
    state, _ = engine.start()
    state, _ = engine.process(state, "有几天")
    state, _ = engine.process(state, "先到这里吧")
    assert state.status == "stopped"
    assert state.items["item_01"].score == 1
    assert build_report(state).mapped_total is None
    assert len(build_report(state).pending_items) == 8


def test_assessment_api_lifecycle_and_closed_session() -> None:
    created = client.post("/api/assessment")
    assert created.status_code == 200
    body = created.json()
    session_id = body["session_id"]
    assert body["current_item_id"] == "item_01"
    assert body["report"]["mapped_total"] is None

    turn = client.post(f"/api/assessment/{session_id}/turn", json={"text": "有几天"})
    assert turn.status_code == 200
    assert turn.json()["report"]["items"]["item_01"]["score"] == 1
    assert client.get(f"/api/assessment/{session_id}/report").json()["confirmed_count"] == 1
    assert len(client.get(f"/api/assessment/{session_id}").json()["turns"]) == 1

    stopped = client.post(f"/api/assessment/{session_id}/turn", json={"text": "停止测评"})
    assert stopped.json()["status"] == "stopped"
    closed = client.post(f"/api/assessment/{session_id}/turn", json={"text": "有几天"})
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "ASSESSMENT_CLOSED"
    assert client.delete(f"/api/assessment/{session_id}").status_code == 200
    assert client.get(f"/api/assessment/{session_id}").status_code == 404
