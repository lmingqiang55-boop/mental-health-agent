import json
import random

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import chat
from backend.core.dialogue_manager import DialogueManager
from backend.main import app
from backend.models.enums import DialogueAction
from backend.models.response import PolicyDecision
from backend.models.states import Message
from backend.policy.client import (
    HttpPolicyClient,
    MockPolicyClient,
    PolicyClientError,
    get_policy_client,
    parse_policy_content,
    set_policy_client,
)
from backend.policy.prompt import POLICY_SYSTEM_PROMPT, build_policy_user_prompt
from backend.policy.topic_constraint import (
    MAX_TOPIC_COUNT,
    TOPICS,
    TopicConstraint,
)


def test_build_policy_user_prompt_keeps_full_history_in_order() -> None:
    history = [
        Message(role="user", content="我最近睡不好"),
        Message(role="assistant", content="最近一般几点睡？"),
        Message(role="user", content="经常凌晨两三点"),
    ]
    prompt = build_policy_user_prompt(history)
    assert prompt == (
        "请根据以下对话历史，决定医生下一步的对话动作。\n\n"
        "【对话历史】\n"
        "患者：我最近睡不好\n"
        "医生：最近一般几点睡？\n"
        "患者：经常凌晨两三点"
    )


@pytest.mark.parametrize("content, expected", [
    ('{"actions":["睡眠"]}', [DialogueAction.SLEEP]),
    ('{"actions":["共情安慰","睡眠"]}', [DialogueAction.EMPATHY, DialogueAction.SLEEP]),
    ('  ```json\n{"actions":["睡眠"]}\n```  ', [DialogueAction.SLEEP]),
])
def test_parse_policy_content(content: str, expected: list[DialogueAction]) -> None:
    assert parse_policy_content(content).actions == expected


@pytest.mark.parametrize("content", [
    '{"actions":["未知动作"]}',
    '{"actions":[]}',
    'not json',
])
def test_invalid_policy_output_raises_clear_error(content: str) -> None:
    with pytest.raises(PolicyClientError):
        parse_policy_content(content)


def test_policy_decision_accepts_the_eleven_prompt_actions() -> None:
    assert len(DialogueAction) == 11
    for action in DialogueAction:
        assert f"\n{action.value}\n" in POLICY_SYSTEM_PROMPT
        assert parse_policy_content(
            json.dumps({"actions": [action.value]}, ensure_ascii=False)
        ).actions == [action]


def test_policy_decision_keeps_action_order() -> None:
    content = '{"actions":["共情安慰","睡眠","食欲"]}'
    assert parse_policy_content(content).actions == [
        DialogueAction.EMPATHY, DialogueAction.SLEEP, DialogueAction.APPETITE,
    ]


def test_topic_constraint_passes_three_mentions_then_switches_to_unused_topic() -> None:
    constraint = TopicConstraint()
    for _ in range(MAX_TOPIC_COUNT):
        assert constraint.apply(["睡眠", "共情安慰"]) == ["睡眠", "共情安慰"]

    switched = constraint.apply(["睡眠"])
    assert len(switched) == 1
    assert switched[0].startswith("当前话题从睡眠转到")
    assert switched[0] not in TOPICS


def test_topic_constraint_prefers_a_never_used_topic_over_a_used_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First unused topic in list order (自杀倾向) wins over exhausted
    # 精神状态 and already used 情绪.
    monkeypatch.setattr(random, "choice", lambda candidates: candidates[0])
    constraint = TopicConstraint()
    constraint.counts.update(
        {"睡眠": MAX_TOPIC_COUNT, "精神状态": MAX_TOPIC_COUNT, "情绪": 1}
    )
    assert constraint.apply(["睡眠"]) == ["当前话题从睡眠转到自杀倾向"]
    assert constraint.counts["自杀倾向"] == 1


def test_topic_constraint_passes_through_when_every_other_topic_is_exhausted() -> None:
    constraint = TopicConstraint()
    for topic in TOPICS:
        constraint.counts[topic] = MAX_TOPIC_COUNT
    assert constraint.apply(["睡眠"]) == ["睡眠"]


def test_topic_constraint_reset_clears_counts_and_keeps_order() -> None:
    constraint = TopicConstraint()
    assert constraint.apply(["其它", "共情安慰", "筛查"]) == ["其它", "共情安慰", "筛查"]
    for _ in range(MAX_TOPIC_COUNT):
        constraint.apply(["情绪"])

    constraint.reset()
    assert all(count == 0 for count in constraint.counts.values())
    assert constraint.apply(["情绪", "兴趣"]) == ["情绪", "兴趣"]


def test_chat_resets_topic_counter_for_each_session() -> None:
    class SleepPolicy(MockPolicyClient):
        def predict(self, conversation_history: list[Message]) -> PolicyDecision:
            return PolicyDecision(actions=[DialogueAction.SLEEP])

    original = chat.dialogue_manager._policy
    chat.dialogue_manager._policy = SleepPolicy()
    try:
        client = TestClient(app)
        first_session = client.post("/api/session").json()["session_id"]
        for _ in range(MAX_TOPIC_COUNT):
            assert client.post("/api/chat", json={
                "session_id": first_session, "text": "睡不好"
            }).json()["actions"] == ["睡眠"]
        fourth = client.post("/api/chat", json={
            "session_id": first_session, "text": "睡不好"
        }).json()
        assert fourth["actions"][0].startswith("当前话题从睡眠转到")
        assert fourth["next_strategy"] == fourth["actions"][0]

        fresh_session = client.post("/api/session").json()["session_id"]
        fresh = client.post("/api/chat", json={
            "session_id": fresh_session, "text": "睡不好"
        }).json()
        assert fresh["actions"] == ["睡眠"]
        assert fresh["next_strategy"] == "睡眠"
    finally:
        chat.dialogue_manager._policy = original


def test_http_policy_client_sends_expected_request() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"actions":["共情安慰","睡眠"]}'}}]
        })

    transport = httpx.MockTransport(handle)
    policy = HttpPolicyClient(
        base_url="http://policy.test/", model="test-model", timeout=5,
        client=httpx.Client(transport=transport),
    )
    history = [Message(role="user", content="我最近睡不好")]
    assert policy.predict(history).actions == [DialogueAction.EMPATHY, DialogueAction.SLEEP]

    assert len(seen) == 1
    assert str(seen[0].url) == "http://policy.test/v1/chat/completions"
    body = json.loads(seen[0].content)
    assert body == {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": POLICY_SYSTEM_PROMPT},
            {"role": "user", "content": build_policy_user_prompt(history)},
        ],
        "temperature": 0,
        "max_tokens": 64,
    }


@pytest.mark.parametrize("response", [
    httpx.Response(503, text="unavailable"),
    httpx.Response(200, json={}),
    httpx.Response(200, json={"choices": [{"message": {"content": "oops"}}]}),
])
def test_http_policy_client_rejects_bad_responses(response: httpx.Response) -> None:
    policy = HttpPolicyClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: response))
    )
    with pytest.raises(PolicyClientError):
        policy.predict([Message(role="user", content="你好")])


def test_policy_factory_and_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLICY_PROVIDER", raising=False)
    assert isinstance(get_policy_client(), MockPolicyClient)
    fake = MockPolicyClient()
    try:
        set_policy_client(fake)
        assert DialogueManager()._policy is fake
    finally:
        set_policy_client(None)
    monkeypatch.setenv("POLICY_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="Unknown POLICY_PROVIDER"):
        get_policy_client()


def test_chat_uses_current_turn_and_full_history_for_http_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"actions":["睡眠"]}'}}]
        })

    policy = HttpPolicyClient(
        client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    monkeypatch.setattr(chat.dialogue_manager, "_policy", policy)
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]
    first = client.post("/api/chat", json={"session_id": session_id, "text": "我最近睡不好"})
    second = client.post("/api/chat", json={"session_id": session_id, "text": "经常凌晨两三点"})

    assert first.status_code == second.status_code == 200
    assert second.json()["actions"] == ["睡眠"]
    assert second.json()["next_strategy"] == "睡眠"
    assert second.json()["reply"] == "谢谢你愿意分享。还有什么最近的变化想补充吗？"
    assert prompts[0].endswith("患者：我最近睡不好")
    assert prompts[1].endswith(
        "患者：我最近睡不好\n"
        "医生：谢谢你愿意分享。还有什么最近的变化想补充吗？\n"
        "患者：经常凌晨两三点"
    )
