"""The chat API uses the dialogue Agent after policy selection."""

import asyncio

from fastapi.testclient import TestClient

from backend.agents.dialogue_agent import DialogueAgent
from backend.api import chat
from backend.llm.config import DeepSeekConfigError
from backend.main import app
from backend.models.dialogue import DialogueAgentRequest


def test_repeated_policy_action_generates_contextual_follow_up(
        monkeypatch, policy_stub):
    policy_stub(("共情安慰", "睡眠"))

    class RecordingClient:
        def __init__(self):
            self.prompts = []

        async def generate(self, system_prompt, user_prompt):
            self.prompts.append(user_prompt)
            current = user_prompt.split("用户刚刚说：", 1)[1].splitlines()[0]
            return f"听起来{current}让你难受。关于睡眠，能再说说具体情况吗？"

    generator = RecordingClient()
    monkeypatch.setattr(chat.dialogue_manager, "_dialogue_agent", DialogueAgent(generator))
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]

    first = client.post("/api/chat", json={
        "session_id": session_id, "text": "最近睡眠不好",
        "vision_snapshot": {"valence": -0.3},
    })
    second = client.post("/api/chat", json={
        "session_id": session_id, "text": "入睡困难",
    })

    assert first.status_code == second.status_code == 200
    assert first.json()["next_strategy"] == second.json()["next_strategy"] == "睡眠"
    assert first.json()["reply"] != second.json()["reply"]
    assert "入睡困难" in second.json()["reply"]
    assert "actions：共情安慰、睡眠" in generator.prompts[1]
    assert "助手：" + first.json()["reply"] in generator.prompts[1]
    assert "valence=-0.3" in generator.prompts[1]
    assert generator.prompts[1].count("用户刚刚说：入睡困难") == 1


def test_dialogue_unavailable_does_not_save_partial_turn(monkeypatch, policy_stub):
    policy_stub(("睡眠",))
    monkeypatch.setattr(chat.dialogue_manager, "_dialogue_agent", None)

    def missing_config():
        raise DeepSeekConfigError("missing key")

    monkeypatch.setattr("backend.core.dialogue_manager.load_deepseek_config",
                        missing_config)
    client = TestClient(app)
    session_id = client.post("/api/session").json()["session_id"]

    result = client.post("/api/chat", json={
        "session_id": session_id, "text": "我睡不着",
    })
    session = client.get(f"/api/session/{session_id}").json()

    assert result.status_code == 503
    assert result.json()["error"]["code"] == "DIALOGUE_UNAVAILABLE"
    assert session["turn_count"] == 0
    assert len(session["conversation_history"]) == 1


def test_dialogue_agent_rewrites_an_exact_repeat():
    class SequencedClient:
        def __init__(self):
            self.prompts = []

        async def generate(self, system_prompt, user_prompt):
            self.prompts.append(user_prompt)
            return ("最近睡眠怎么样？" if len(self.prompts) == 1
                    else "你说入睡困难，是从什么时候开始的？")

    request = DialogueAgentRequest.model_validate({
        "conversation_history": [
            {"role": "assistant", "content": "最近睡眠怎么样？"},
        ],
        "decision": {"actions": ["睡眠"], "topic": "睡眠"},
        "current_user_input": {"text": "入睡困难"},
    })
    client = SequencedClient()
    answer = asyncio.run(DialogueAgent(client).generate_reply(request))

    assert answer.reply == "你说入睡困难，是从什么时候开始的？"
    assert len(client.prompts) == 2
    assert "上游 decision 不变" in client.prompts[1]
