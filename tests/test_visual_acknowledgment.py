"""A reliable visual cue may be voiced, but only every few assistant turns."""

from backend.api import chat
from backend.core.dialogue_manager import DialogueManager
from backend.core.visual_acknowledgment import choose_visual_acknowledgment
from backend.core.session_manager import session_manager
from backend.models.dialogue import DialogueAgentResponse
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


def test_visual_observation_needs_reliable_real_frames(monkeypatch):
    session, snapshot = _visual_session()
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
    assert choose_visual_acknowledgment(session, "turn", snapshot) is None
    session.conversation_history.extend(Message(
        role=MessageRole.ASSISTANT, content=f"前面的回复 {index}") for index in range(3))
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


def test_three_intervening_assistant_replies_before_next_observation(monkeypatch):
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
    session, snapshot = _visual_session(label="happy")
    session.conversation_history.append(Message(
        role=MessageRole.ASSISTANT, content="你看起来挺开心的。"))

    for number in range(3):
        assert choose_visual_acknowledgment(session, "turn", snapshot) is None
        session.conversation_history.append(Message(
            role=MessageRole.USER, content=f"第 {number} 次回答"))
        session.conversation_history.append(Message(
            role=MessageRole.ASSISTANT, content=f"第 {number} 次回复"))
    assert choose_visual_acknowledgment(session, "turn", snapshot) == "happy"


def test_dialogue_manager_says_the_qualified_observation(monkeypatch):
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
    session, snapshot = _visual_session()
    session.conversation_history.extend(Message(
        role=MessageRole.ASSISTANT, content=f"前面的回复 {index}") for index in range(3))
    session.conversation_history.append(Message(role=MessageRole.USER, content="睡不着"))

    class Policy:
        def predict(self, history):
            return PolicyDecision(actions=[DialogueAction.SLEEP])

    class Dialogue:
        async def generate_reply(self, request):
            return DialogueAgentResponse(reply="最近是入睡困难，还是容易醒？")

    result = DialogueManager(policy_client=Policy(), dialogue_agent=Dialogue()).process_turn(
        "睡不着", session, snapshot, use_latest_states=False, utterance_id="turn")
    assert result.reply.startswith("你看起来好像有点不开心。")
    assert result.reply.endswith("最近是入睡困难，还是容易醒？")

    crisis = DialogueManager(policy_client=Policy(), dialogue_agent=Dialogue()).process_turn(
        "我想自杀", session, snapshot, use_latest_states=False, utterance_id="turn")
    assert "你看起来" not in crisis.reply


def test_chat_route_passes_frozen_turn_to_visual_frequency_gate(
        monkeypatch, policy_stub, dialogue_stub):
    monkeypatch.setattr("backend.core.visual_acknowledgment.real_vision_detector_active",
                        lambda: True)
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

    assert response.reply.startswith("你看起来好像有点不开心。")
    assert dialogue_stub.requests[-1].current_user_input.visual is not None
