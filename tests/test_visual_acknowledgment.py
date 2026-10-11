"""A reliable visual cue reaches the generator at most once every few turns."""

import pytest

from backend.api import chat
from backend.agents.dialogue_agent import DialogueAgent
from backend.core.dialogue_manager import DialogueManager
from backend.core.visual_acknowledgment import choose_visual_acknowledgment
from backend.core.session_manager import session_manager
from backend.models.dialogue import DialogueAgentResponse
from backend.models.dialogue import (
    DialogueAgentRequest, DialogueCurrentUserInput, DialogueDecision,
)
from backend.prompts.dialogue_prompt import build_dialogue_user_prompt
from backend.models.enums import MessageRole
from backend.models.requests import ChatRequest
from backend.models.states import (
    Message, SessionState, VisionFrameObservation, VisionSegment, VisionState,
)
from backend.policy.client import DialogueAction, PolicyDecision
from backend.vision.aggregation import aggregate_frames


def _visual_session(label="sad", confidence=0.95, *, face=True):
    session = SessionState(session_id="visual-test")
    frames = [VisionState(face_detected=face, emotion=label,
                          emotion_confidence=confidence) for _ in range(3)]
    snapshot = aggregate_frames(frames)
    session.vision_frames = [VisionFrameObservation(
        frame_id=f"frame-{index}", capture_id="camera",
        captured_at_ms=index * 100, image_digest="test", state=frame,
    ) for index, frame in enumerate(frames)]
    session.vision_segments["turn"] = VisionSegment(
        capture_id="camera", start_ms=0, end_ms=300,
        vision_snapshot=snapshot, frame_count=3,
        valid_frame_count=sum(frame.face_detected for frame in frames),
    )
    return session, snapshot


def _resolve_synchronous_stub(coroutine):
    """Run a stub coroutine without Windows' socket based event loop."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Stub unexpectedly suspended")


def test_visual_observation_needs_reliable_real_frames(monkeypatch):
    session, snapshot = _visual_session()
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
    assert choose_visual_acknowledgment(session, "turn", snapshot) is None
    session.turn_count = 2
    assert choose_visual_acknowledgment(session, "turn", snapshot) == "sad"

    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: False)
    assert choose_visual_acknowledgment(session, "turn", snapshot) is None
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
    assert choose_visual_acknowledgment(session, "missing", snapshot) is None
    assert choose_visual_acknowledgment(session, "turn", None) is None
    for weak_session, weak_snapshot in (
            _visual_session(confidence=0.45), _visual_session(face=False)):
        assert choose_visual_acknowledgment(weak_session, "turn", weak_snapshot) is None


@pytest.mark.parametrize("label", ["happy", "sad", "fearful", "angry"])
def test_four_supported_emotions_and_turn_cooldown(monkeypatch, label):
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
    session, snapshot = _visual_session(label=label)
    session.turn_count = 2
    assert choose_visual_acknowledgment(session, "turn", snapshot) == label
    session.last_visual_observation_turn = session.turn_count

    for number in range(3):
        session.turn_count += 1
        assert choose_visual_acknowledgment(session, "turn", snapshot) is None
    session.turn_count += 1
    assert choose_visual_acknowledgment(session, "turn", snapshot) == label


@pytest.mark.parametrize("label,zh", [
    ("happy", "开心"), ("sad", "难过"),
    ("fearful", "紧张"), ("angry", "烦躁"),
])
def test_prompt_asks_agent_to_integrate_each_cue_naturally(label, zh):
    request = DialogueAgentRequest(
        conversation_history=[], decision=DialogueDecision(actions=["情绪"]),
        current_user_input=DialogueCurrentUserInput(text="最近有点累"),
        visual_observation=label,
    )
    prompt = build_dialogue_user_prompt(request)
    assert f"外观线索：{zh}" in prompt
    assert "整句由你根据上下文组织" in prompt
    request.visual_observation = None
    assert "本轮没有可口头提及的视觉观察" in build_dialogue_user_prompt(request)


def test_dialogue_manager_says_the_qualified_observation(monkeypatch):
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
    monkeypatch.setattr("backend.core.dialogue_manager.asyncio.run", _resolve_synchronous_stub)
    session, snapshot = _visual_session()
    session.turn_count = 2
    session.conversation_history.append(Message(role=MessageRole.USER, content="睡不着"))

    class Policy:
        def predict(self, history):
            return PolicyDecision(actions=[DialogueAction.SLEEP])

    class Dialogue:
        request = None

        async def generate_reply(self, request):
            self.request = request
            return DialogueAgentResponse(
                reply="你看起来有点不开心，最近是入睡困难，还是容易醒？")

    dialogue = Dialogue()
    result = DialogueManager(policy_client=Policy(), dialogue_agent=dialogue).process_turn(
        "睡不着", session, snapshot, use_latest_states=False, utterance_id="turn")
    assert result.reply == "你看起来有点不开心，最近是入睡困难，还是容易醒？"
    assert dialogue.request.visual_observation == "sad"
    assert session.last_visual_observation_turn == 2

    crisis = DialogueManager(policy_client=Policy(), dialogue_agent=Dialogue()).process_turn(
        "我想自杀", session, snapshot, use_latest_states=False, utterance_id="turn")
    assert "你看起来" not in crisis.reply


def test_chat_route_passes_frozen_turn_to_visual_frequency_gate(
        monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
    monkeypatch.setattr("backend.core.dialogue_manager.asyncio.run", _resolve_synchronous_stub)
    policy_stub(("情绪",))
    session_id = session_manager.create_session().session_id
    for text in ("第一句", "第二句"):
        chat.chat(ChatRequest(session_id=session_id, text=text))

    visual_session, snapshot = _visual_session()

    def add_frozen_vision(session):
        session.vision_frames = visual_session.vision_frames
        session.vision_segments = visual_session.vision_segments

    session_manager.modify_session(session_id, add_frozen_vision)
    response = chat.chat(ChatRequest(
        session_id=session_id, text="第三句", utterance_id="turn",
        vision_snapshot=snapshot,
    ))

    assert "你看起来" not in response.reply
    assert dialogue_stub.requests[-1].visual_observation == "sad"
    assert dialogue_stub.requests[-1].current_user_input.visual is not None


def test_agent_rewrites_missing_visual_observation_without_fixed_prefix():
    class Client:
        prompts = []

        async def generate(self, *, system_prompt, user_prompt):
            self.prompts.append(user_prompt)
            return ("最近睡得怎么样？" if len(self.prompts) == 1 else
                    "你看起来有点紧张，最近睡眠怎么样？")

    client = Client()
    agent = DialogueAgent(client)
    request = DialogueAgentRequest(
        conversation_history=[], decision=DialogueDecision(actions=["睡眠"]),
        current_user_input=DialogueCurrentUserInput(text="睡不着"),
        visual_observation="fearful",
    )
    result = _resolve_synchronous_stub(agent.generate_reply(request))
    assert result.reply == "你看起来有点紧张，最近睡眠怎么样？"
    assert len(client.prompts) == 2
