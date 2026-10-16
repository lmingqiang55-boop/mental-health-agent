# -*- coding: utf-8 -*-
"""Phase 4：Dialogue 输出 1~3 条独立消息（聊天气泡）。

本文件验证四类约束：

1. **分段由 Dialogue 决定**：模型每行一条消息，后端不做按标点的机械拆分；
2. **向后兼容**：``reply`` 永远是 ``messages`` 的换行拼接，旧调用方不受影响；
3. **一轮仍然只有一个轮次**：多条气泡不会让 ``turn_count`` 多自增、不会让历史
   多长记录、不会让 TTS 重复播报，``utterance_id`` 幂等语义不变；
4. **既有链路不受影响**：Safety 两个分支、视觉线索、Legacy 引擎照旧工作。

【关于 Mock 的边界】这里的对话桩只替代"模型返回什么文本"，**解析、落库、
历史、TTS 全部走真实实现**，因此它证明的是后端行为，而不是模型的分段质量。
真实模型的分段效果需要跑真模型实验，本文件不做这个结论。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.agents.dialogue_agent import (
    DialogueAgent, DialogueAgentError, parse_reply_messages,
)
from backend.api import chat
from backend.api import tts as tts_api
from backend.core.session_manager import session_manager
from backend.graph.engine import DIALOGUE_ENGINE_ENV, ENGINE_GRAPH, ENGINE_LEGACY
from backend.main import app
from backend.models.dialogue import (
    MAX_REPLY_MESSAGES, DialogueAgentRequest, DialogueAgentResponse,
    DialogueCurrentUserInput, DialogueDecision, DialogueHistoryMessage,
)
from backend.models.enums import MessageRole
from backend.models.states import Message
from backend.safety.schemas import SafetyLevel

client = TestClient(app)

TWO = "听起来你最近确实有点累。\n能和我说说最近发生了什么吗？"
THREE = "听你这么说，这阵子确实挺熬人的。\n这种情况大概从什么时候开始的？\n晚上睡得着吗？"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

class ReplyStub:
    """离线对话 Agent：按脚本给出**模型原始文本**（可多行）。

    刻意走真实的 :func:`parse_reply_messages`，这样"分段 + 落库 + 历史 + TTS"
    整条链路都是真的，只有模型本身是假的。
    """

    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.requests: list[DialogueAgentRequest] = []
        self.calls = 0
        self.need_decision = False
        self.route_reason_code = "continue_topic"

    async def route(self, request):
        from backend.models.dialogue import DialogueRouteDecision
        return DialogueRouteDecision(
            need_decision=self.need_decision,
            reason_code=self.route_reason_code, reason="离线桩")

    async def generate_reply(self, request: DialogueAgentRequest):
        self.requests.append(request)
        raw = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        messages = parse_reply_messages(raw)
        if not messages:
            raise DialogueAgentError("Dialogue Agent generated an empty reply.")
        return DialogueAgentResponse(messages=messages)


def install(monkeypatch, *outputs: str) -> ReplyStub:
    stub = ReplyStub(*outputs)
    monkeypatch.setattr(chat.dialogue_manager, "_dialogue_agent", stub)
    return stub


def new_session() -> str:
    return client.post("/api/session").json()["session_id"]


def turn(session_id: str, text: str, **extra) -> dict:
    response = client.post("/api/chat",
                           json={"session_id": session_id, "text": text, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def history(session_id: str) -> list[dict]:
    return client.get(f"/api/session/{session_id}").json()["conversation_history"]


def make_request(text: str = "最近睡不好") -> DialogueAgentRequest:
    return DialogueAgentRequest(
        conversation_history=[DialogueHistoryMessage(role="assistant", content="你好呀")],
        decision=DialogueDecision(actions=["共情安慰", "睡眠"], topic="睡眠"),
        current_user_input=DialogueCurrentUserInput(text=text),
    )


class FakeLLM:
    """按顺序返回若干段原始文本；用来测 DialogueAgent 自己的解析与重写。"""

    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append(user_prompt)
        return self.outputs[min(len(self.prompts) - 1, len(self.outputs) - 1)]


# ---------------------------------------------------------------------------
# 1. 解析：1 / 2 / 3 条与各种脏输出
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("count", [1, 2, 3])
def test_generate_reply_produces_one_to_three_messages(count):
    """① ② ③ 分别生成 1 / 2 / 3 条消息。"""
    raw = "\n".join(f"第{index}句。" for index in range(1, count + 1))
    response = asyncio.run(
        DialogueAgent(FakeLLM(raw)).generate_reply(make_request()))
    assert len(response.messages) == count
    assert response.messages == [f"第{index}句。" for index in range(1, count + 1)]
    assert response.reply == raw


@pytest.mark.parametrize("raw,expected", [
    ("  \n  唯一一句。  \n\n", ["唯一一句。"]),
    ("- 第一条。\n- 第二条。", ["第一条。", "第二条。"]),
    ("1. 第一条。\n2. 第二条。", ["第一条。", "第二条。"]),
    ("1、第一条。\n2、第二条。", ["第一条。", "第二条。"]),
    ("```\n第一条。\n第二条。\n```", ["第一条。", "第二条。"]),
])
def test_malformed_output_is_cleaned_into_messages(raw, expected):
    """④ 非法/脏结构化输出按容错规则清理，而不是整轮失败。"""
    assert parse_reply_messages(raw) == expected


def test_beyond_the_limit_is_merged_not_truncated():
    """超过 3 条时**合并**，正文一个字都不能少。"""
    raw = "一。\n二。\n三。\n四。\n五。"
    messages = parse_reply_messages(raw)
    assert len(messages) == MAX_REPLY_MESSAGES
    assert messages[0] == "一。" and messages[1] == "二。"
    assert "三。" in messages[2] and "五。" in messages[2]


def test_blank_output_is_rejected():
    """模型什么都没说时不伪造回复。"""
    assert parse_reply_messages("   \n\n ") == []
    with pytest.raises(DialogueAgentError):
        asyncio.run(DialogueAgent(FakeLLM("  \n ")).generate_reply(make_request()))


def test_rewrite_keeps_the_multi_message_format():
    """⑤ 重写路径同样受输出格式约束：重写不会把多条消息压回一行。"""
    repeated = "听起来你最近确实有点累。\n能和我说说最近发生了什么吗？"
    rewritten = "这阵子确实挺熬人的。\n这种感觉大概从什么时候开始的？"
    llm = FakeLLM(repeated, rewritten)
    request = DialogueAgentRequest(
        conversation_history=[
            DialogueHistoryMessage(role="user", content="嗯"),
            DialogueHistoryMessage(role="assistant", content=repeated),
        ],
        decision=DialogueDecision(actions=["共情安慰", "睡眠"], topic="睡眠"),
        current_user_input=DialogueCurrentUserInput(text="最近睡不好"),
    )
    response = asyncio.run(DialogueAgent(llm).generate_reply(request))
    assert len(llm.prompts) == 2, "命中重复时必须重写一次"
    assert "格式保持不变" in llm.prompts[-1]
    assert response.messages == rewritten.split("\n")


# ---------------------------------------------------------------------------
# 6 / 7 / 8：写入、历史恢复、轮次与幂等
# ---------------------------------------------------------------------------

def test_two_messages_are_written_as_one_turn_and_restored(
        monkeypatch, policy_stub):
    """⑥ 消息写入历史并可恢复；⑦ turn_count 只加一次。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub()
    install(monkeypatch, TWO)

    sid = new_session()
    body = turn(sid, "最近睡不好")

    assert body["messages"] == TWO.split("\n")
    assert body["reply"] == TWO, "reply 必须是 messages 的换行拼接"
    assert body["turn_count"] == 1, "一轮用户输入只算一个轮次"

    # 历史里只有**一条** assistant 记录，气泡挂在它身上。
    stored = [item for item in history(sid) if item["role"] == "assistant"
              and item["content"] == TWO]
    assert len(stored) == 1
    assert stored[0]["messages"] == TWO.split("\n")

    # 恢复（前端 init 的路径）读到的还是同样的气泡。
    restored = history(sid)
    assistant = [item for item in restored if item["role"] == "assistant"]
    assert [item["messages"] for item in assistant if item["content"] == TWO] \
        == [TWO.split("\n")]
    assert client.get(f"/api/session/{sid}").json()["turn_count"] == 1


def test_three_messages_do_not_grow_history_or_turn_count(monkeypatch, policy_stub):
    """气泡数量与轮次、历史条数完全解耦。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub()
    install(monkeypatch, THREE, TWO)

    sid = new_session()
    first = turn(sid, "最近睡不好")
    second = turn(sid, "大概一个多月了")

    assert first["messages"] == THREE.split("\n")
    assert second["messages"] == TWO.split("\n")
    assert second["turn_count"] == 2

    entries = history(sid)
    # 开场白 1 条 + 每轮 user/assistant 各 1 条 = 1 + 2 * 2
    assert len([item for item in entries if item["role"] == "assistant"]) == 3
    assert len([item for item in entries if item["role"] == "user"]) == 2


def test_utterance_id_replay_returns_the_same_messages(monkeypatch, policy_stub):
    """⑧ 同一 utterance_id 重复提交：不重新生成、不加轮次、历史不变。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub()
    stub = install(monkeypatch, TWO, THREE)

    sid = new_session()
    first = turn(sid, "最近睡不好", utterance_id="u1")
    before = history(sid)
    replay = turn(sid, "最近睡不好", utterance_id="u1")

    assert replay == first, "重放必须原样返回首次结果"
    assert replay["messages"] == TWO.split("\n")
    assert stub.calls == 1, "重放不得再生成一次"
    assert history(sid) == before, "重放不得再追加历史"
    assert client.get(f"/api/session/{sid}").json()["turn_count"] == 1


def test_new_utterance_id_generates_a_new_turn(monkeypatch, policy_stub):
    """对照组：换一个标识就是新的一轮。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub()
    stub = install(monkeypatch, TWO, THREE)

    sid = new_session()
    turn(sid, "最近睡不好", utterance_id="u1")
    second = turn(sid, "大概一个多月了", utterance_id="u2")
    assert second["messages"] == THREE.split("\n")
    assert stub.calls == 2
    assert client.get(f"/api/session/{sid}").json()["turn_count"] == 2


def test_same_utterance_id_with_different_text_still_conflicts(monkeypatch, policy_stub):
    """幂等的边界没有被多气泡放开：同标识不同内容仍然 409。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub()
    install(monkeypatch, TWO)

    sid = new_session()
    turn(sid, "最近睡不好", utterance_id="u1")
    conflict = client.post("/api/chat", json={
        "session_id": sid, "text": "换了一句话", "utterance_id": "u1"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "UTTERANCE_CONFLICT"


# ---------------------------------------------------------------------------
# 9：Safety 分支
# ---------------------------------------------------------------------------

def test_safety_review_branch_keeps_its_messages(
        monkeypatch, policy_stub, safety_stub):
    """⑨ 澄清模式照旧：消息来自 Safety，普通图完全不参与。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub()
    stub = install(monkeypatch, TWO)
    safety_stub.force(SafetyLevel.UNCERTAIN, message="我想再确认一下你现在的状况。")

    sid = new_session()
    body = turn(sid, "我也不知道该怎么办")

    assert body["safety"]["route"] == "safety_review"
    assert body["messages"] == ["我想再确认一下你现在的状况。"]
    assert body["reply"] == body["messages"][0]
    assert stub.calls == 0, "安全分支不得调用 Dialogue"
    assert body["turn_count"] == 1

    stored = [item for item in history(sid) if item["role"] == "assistant"]
    # 开场白 + 本轮各一条：安全消息没有因为条数而多出一条记录。
    assert len(stored) == 2
    assert stored[-1]["messages"] == ["我想再确认一下你现在的状况。"]


def test_safety_support_branch_messages_are_persisted_once(
        monkeypatch, policy_stub, safety_stub):
    """支持模式同样落库一次；历史不会因为消息条数多出来。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub()
    install(monkeypatch, TWO)
    safety_stub.force(SafetyLevel.HIGH, message="请先联系身边可信任的人。")

    sid = new_session()
    body = turn(sid, "我不想活了")

    assert body["safety"]["route"] == "safety_stop"
    assert body["safety"]["hotline_numbers"] == ["12356"]
    assert body["messages"] == ["请先联系身边可信任的人。"]
    stored = [item for item in history(sid) if item["role"] == "assistant"]
    # 开场白 + 本轮各一条。
    assert len(stored) == 2
    assert stored[-1]["messages"] == ["请先联系身边可信任的人。"]


# ---------------------------------------------------------------------------
# 10 / 11：视觉线索与 Legacy 引擎
# ---------------------------------------------------------------------------

def test_visual_observation_still_reaches_dialogue(monkeypatch, policy_stub):
    """⑩ 视觉得到允许时仍然进入 Dialogue 请求（本轮允许提及外观）。

    这里把"挑选视觉通道"固定成一个已知结果，只验证 Phase 4 关心的那一段：
    多气泡输出不会挤掉 ``visual_observation``。挑选规则本身由
    ``tests/test_visual_acknowledgment.py`` 覆盖，不在这里重复。
    """
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub(("共情安慰", "睡眠"))
    stub = install(monkeypatch, "你看起来有点累。\n最近睡得怎么样？")

    # 图在编译时按名字绑定了节点里的 select_visual_channels，因此按节点模块打桩。
    import backend.graph.nodes as nodes_module
    monkeypatch.setattr(nodes_module, "select_visual_channels",
                        lambda *args, **kwargs: _channels_with_visual())

    from backend.models.states import VisionState
    sid = new_session()
    snapshot = VisionState(face_detected=True).model_dump(mode="json")
    body = turn(sid, "最近睡不好", vision_snapshot=snapshot)

    assert stub.requests, "Dialogue 必须被调用"
    assert stub.requests[-1].visual_observation == "sad"
    assert body["messages"] == ["你看起来有点累。", "最近睡得怎么样？"]


def _channels_with_visual():
    from backend.core.dialogue_manager import VisualChannels
    from backend.models.responses import VisualFeedback
    return VisualChannels(feedback=VisualFeedback(reason="test"), acknowledgment="sad")


def test_legacy_engine_still_returns_messages(monkeypatch, policy_stub):
    """⑪ 旧版顺序执行路径同样产出多条消息，行为与图一致。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_LEGACY)
    policy_stub()
    install(monkeypatch, TWO)

    sid = new_session()
    body = turn(sid, "最近睡不好")

    assert body["messages"] == TWO.split("\n")
    assert body["reply"] == TWO
    assert body["turn_count"] == 1
    stored = [item for item in history(sid) if item["role"] == "assistant"]
    assert [item["messages"] for item in stored if item["content"] == TWO] \
        == [TWO.split("\n")]


# ---------------------------------------------------------------------------
# TTS：整轮合成，不漏读、不重复
# ---------------------------------------------------------------------------

def test_tts_reads_every_bubble_of_a_turn_exactly_once():
    """语音按整轮合成：三条气泡全部读到，且 reply 不会被再读一遍。"""
    session = session_manager.get_session(new_session())
    session.conversation_history.extend([
        Message(role=MessageRole.USER, content="最近睡不好"),
        Message(role=MessageRole.ASSISTANT, content=TWO, messages=TWO.split("\n")),
    ])
    session.turn_count = 1

    text = tts_api._text_for_turn(session, 1)
    assert text == TWO
    for bubble in TWO.split("\n"):
        assert text.count(bubble) == 1, "每条气泡只出现一次"


def test_tts_reads_all_three_bubbles_in_order():
    session = session_manager.get_session(new_session())
    session.conversation_history.extend([
        Message(role=MessageRole.USER, content="最近睡不好"),
        Message(role=MessageRole.ASSISTANT, content=THREE, messages=THREE.split("\n")),
    ])
    session.turn_count = 1

    text = tts_api._text_for_turn(session, 1)
    positions = [text.index(bubble) for bubble in THREE.split("\n")]
    assert positions == sorted(positions), "气泡顺序必须保持"


def test_tts_falls_back_to_content_for_history_without_messages():
    """本次改动之前的历史没有 messages，回退到 content，不能读成空。"""
    session = session_manager.get_session(new_session())
    session.conversation_history.extend([
        Message(role=MessageRole.USER, content="最近睡不好"),
        Message(role=MessageRole.ASSISTANT, content="我们可以先聊聊睡眠。"),
    ])
    session.turn_count = 1

    assert tts_api._text_for_turn(session, 1) == "我们可以先聊聊睡眠。"
    with pytest.raises(Exception):
        tts_api._text_for_turn(session, 2)


def test_tts_route_serves_the_whole_turn(monkeypatch, policy_stub):
    """端到端：/api/tts 拿到的就是整轮气泡拼接，不是某一条。"""
    monkeypatch.setenv(DIALOGUE_ENGINE_ENV, ENGINE_GRAPH)
    policy_stub()
    install(monkeypatch, THREE)

    class FakeTTS:
        config = tts_api.get_tts_service().config
        received = None

        async def synthesize(self, text):
            self.received = text
            return b"ID3test"

    fake = FakeTTS()
    monkeypatch.setattr(tts_api, "get_tts_service", lambda: fake)

    sid = new_session()
    turn(sid, "最近睡不好")
    response = client.post("/api/tts", json={"session_id": sid, "turn_count": 1})
    assert response.status_code == 200
    assert fake.received == THREE


# ---------------------------------------------------------------------------
# 契约：响应里的 messages 永远非空，且 reply 兼容
# ---------------------------------------------------------------------------

def test_payload_messages_default_to_the_reply():
    """没有显式传 messages 时退化为单条，消费方不用判断"是不是旧响应"。"""
    from backend.models.responses import DialogueResponsePayload
    payload = DialogueResponsePayload(reply="一句话。", next_strategy="情绪",
                                      current_stage="exploration")
    assert payload.messages == ["一句话。"]


def test_dialogue_response_rejects_a_completely_empty_output():
    with pytest.raises(Exception):
        DialogueAgentResponse()
    assert DialogueAgentResponse(reply="x").messages == ["x"]
    assert DialogueAgentResponse(messages=["a", "b"]).reply == "a\nb"
