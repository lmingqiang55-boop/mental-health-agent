"""演示插桩跟随当前决策接口，并通过正式授权门禁。"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.graph.nodes import TurnNodes
from backend.main import app
from scripts._probe import CountingPolicy, create_demo_session, install_route_recorder


def test_counting_policy_preserves_interview_context():
    received = {}

    def predict(history, **kwargs):
        received.update(history=history, **kwargs)
        return "decision"

    policy = CountingPolicy(SimpleNamespace(predict=predict))
    assert policy.predict(["answer"], turn_count=3, max_turns=35,
                          item_answer_counts={"sleep_disturbance": 1}) == "decision"
    assert received == {"history": ["answer"], "turn_count": 3, "max_turns": 35,
                        "item_answer_counts": {"sleep_disturbance": 1}}
    assert len(policy.log.elapsed) == 1


def test_recorder_observes_decision_without_a_router(monkeypatch):
    result = {"decision": "new target", "ending": None}
    monkeypatch.setattr(TurnNodes, "decision", lambda self, state: result)
    records = install_route_recorder()
    assert TurnNodes(None).decision({}) is result
    assert records == [{**result, "need_decision": True}]


def test_demo_session_uses_consent_api():
    client = TestClient(app)
    sid = create_demo_session(client)
    state = client.get(f"/api/session/{sid}").json()
    assert state["consent"]["status"] == "granted"
    assert "third_party_ai" in state["consent"]["scope"]
