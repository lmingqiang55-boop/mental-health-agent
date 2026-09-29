import json

import httpx
import pytest

from backend.api import assessment as assessment_api
from backend.assessment.engine import AssessmentEngine
from backend.assessment.extractor import ExtractionUnavailable, RuleMockExtractor, build_extractor_from_env
from backend.assessment.model_extractor import OpenAICompatibleExtractor
from backend.main import app
from fastapi.testclient import TestClient


def _model_response(candidates: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps({"candidates": candidates})}}],
    })


def _extractor(response: httpx.Response) -> OpenAICompatibleExtractor:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
    return OpenAICompatibleExtractor("http://local.test/v1", "test-model", client=client)


def test_factory_defaults_to_mock_and_can_select_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSESSMENT_EXTRACTOR", raising=False)
    assert isinstance(build_extractor_from_env(), RuleMockExtractor)

    monkeypatch.setenv("ASSESSMENT_EXTRACTOR", "openai_compatible")
    monkeypatch.setenv("ASSESSMENT_LLM_BASE_URL", "http://localhost:8001/v1")
    monkeypatch.setenv("ASSESSMENT_LLM_MODEL", "local-model")
    assert isinstance(build_extractor_from_env(), OpenAICompatibleExtractor)


def test_model_candidates_are_grounded_before_scoring() -> None:
    response = _model_response([
        {"item_id": "item_01", "quote": "这两周几乎每天心情低落",
         "period": "unknown", "category": "nearly_every_day"},
        {"item_id": "item_03", "quote": "睡眠也不好",
         "period": "past_14_days", "category": "nearly_every_day"},
        {"item_id": "item_05", "quote": "有几天精力不足",
         "period": "past_14_days", "category": "several_days"},
    ])
    engine = AssessmentEngine(_extractor(response))
    state, _ = engine.start()
    state, _ = engine.process(state, "这两周几乎每天心情低落，睡眠也不好。")

    assert state.items["item_01"].score == 3
    assert state.items["item_03"].score is None
    assert state.items["item_03"].evidence_history[-1].proposed_category is None
    assert state.items["item_05"].evidence_history == []
    assert state.current_item_id == "item_03"


def test_model_cannot_invent_category_or_time_window() -> None:
    response = _model_response([
        {"item_id": "item_03", "quote": "经常睡不好",
         "period": "past_14_days", "category": "nearly_every_day"},
    ])
    engine = AssessmentEngine(_extractor(response))
    state, _ = engine.start()
    state, _ = engine.process(state, "经常睡不好")
    event = state.items["item_03"].evidence_history[-1]
    assert event.period == "unknown"
    assert event.proposed_category is None
    assert state.items["item_03"].score is None


def test_model_category_must_match_user_words() -> None:
    response = _model_response([
        {"item_id": "item_01", "quote": "有几天",
         "period": "past_14_days", "category": "nearly_every_day"},
    ])
    engine = AssessmentEngine(_extractor(response))
    state, _ = engine.start()
    state, _ = engine.process(state, "有几天")
    assert state.items["item_01"].status == "needs_clarification"
    assert state.items["item_01"].score is None


def test_shared_two_week_context_can_ground_another_clause() -> None:
    response = _model_response([
        {"item_id": "item_03", "quote": "有几天睡不好",
         "period": "unknown", "category": "several_days"},
    ])
    engine = AssessmentEngine(_extractor(response))
    state, _ = engine.start()
    state, _ = engine.process(state, "这两周心情还好，但有几天睡不好")
    assert state.items["item_03"].score == 1
    assert state.items["item_03"].period == "past_14_days"


def test_model_cannot_score_third_person_or_wrong_item() -> None:
    response = _model_response([
        {"item_id": "item_01", "quote": "几乎每天心情低落",
         "period": "past_14_days", "category": "nearly_every_day"},
        {"item_id": "item_04", "quote": "几乎每天心情低落",
         "period": "past_14_days", "category": "nearly_every_day"},
    ])
    engine = AssessmentEngine(_extractor(response))
    state, _ = engine.start()
    state, _ = engine.process(state, "她这两周几乎每天心情低落")
    assert state.items["item_01"].score is None
    assert state.items["item_04"].score is None


def test_provider_failure_returns_503_without_committing_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = AssessmentEngine(_extractor(httpx.Response(502, text="upstream error")))
    monkeypatch.setattr(assessment_api, "engine", engine)
    client = TestClient(app)
    created = client.post("/api/assessment").json()
    session_id = created["session_id"]

    failed = client.post(f"/api/assessment/{session_id}/turn", json={"text": "有几天"})
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "EXTRACTION_UNAVAILABLE"
    unchanged = client.get(f"/api/assessment/{session_id}").json()
    assert unchanged["turns"] == []
    assert unchanged["current_item_id"] == "item_01"
    assert unchanged["items"]["item_01"]["score"] is None
    client.delete(f"/api/assessment/{session_id}")


def test_malformed_model_json_is_rejected() -> None:
    bad = httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
    with pytest.raises(ExtractionUnavailable):
        _extractor(bad).extract("有几天", "item_01")


def test_deepseek_request_uses_json_mode_and_non_thinking_option() -> None:
    captured: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return _model_response([])

    extractor = OpenAICompatibleExtractor(
        "https://api.deepseek.com", "deepseek-flash", "test-key",
        thinking_mode="disabled",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    assert extractor.extract("有几天", "item_01") == []
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "deepseek-flash"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert captured["payload"]["max_tokens"] == 1024


def test_truncated_model_output_is_rejected() -> None:
    truncated = httpx.Response(200, json={"choices": [{
        "finish_reason": "length",
        "message": {"content": '{"candidates":[]}'},
    }]})
    with pytest.raises(ExtractionUnavailable):
        _extractor(truncated).extract("有几天", "item_01")
