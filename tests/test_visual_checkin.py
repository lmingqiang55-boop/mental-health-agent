"""说的和显示的反着来时，对话 Agent 可以温和核对一次。

这条通道和"你看起来……"是**两回事**：核对靠文字极性与人脸效价的方向，
不需要模型先给出一个高置信度的表情名字。真实会话里最常见的情况恰好是
"画面 neutral、置信度不高，但效价明显为负"，那种情况在标签通道里永远被拒。
"""

import pytest

from backend.core.dialogue_manager import DialogueManager
from backend.core.multimodal_consistency import detect_turn_discordance
from backend.core.visual_acknowledgment import (
    choose_visual_acknowledgment,
    select_visual_checkin,
)
from backend.core.vision_thresholds import (
    ConsistencyThresholds,
    VisualEvidenceThresholds,
)
from backend.models.dialogue import (
    DialogueAgentRequest,
    DialogueAgentResponse,
    DialogueCurrentUserInput,
    DialogueDecision,
    DialogueVisualDiscordance,
)
from backend.models.enums import MessageRole
from backend.models.states import (
    Message,
    SessionState,
    VisionFrameObservation,
    VisionSegment,
    VisionState,
)
from backend.policy.client import DialogueAction, PolicyDecision
from backend.prompts.dialogue_prompt import build_dialogue_user_prompt
from backend.vision.aggregation import aggregate_frames

#: 文字读出来是积极的（"我今天特别开心" → 约 +0.76）。
HAPPY_WORDS = "我今天特别开心"
#: 文字读出来是消极的（"我最近特别难过" → 约 -0.76）。
SAD_WORDS = "我最近特别难过"


def _visual_session(label="neutral", confidence=0.2, *, valence=-0.6, face=True):
    """默认造一张"表情说不出口、但脸是负效价"的画面——标签通道会被拒。"""

    session = SessionState(session_id="checkin-test", active_vision_capture_id="camera")
    frames = [VisionState(face_detected=face, emotion=label,
                          emotion_confidence=confidence, valence=valence)
              for _ in range(3)]
    snapshot = aggregate_frames(frames)
    session.vision_frames = [VisionFrameObservation(
        frame_id=f"frame-{index}", capture_id="camera",
        captured_at_ms=index * 100, image_digest="test", state=frame, source="real",
    ) for index, frame in enumerate(frames)]
    session.vision_segments["turn"] = VisionSegment(
        capture_id="camera", start_ms=0, end_ms=300,
        vision_snapshot=snapshot, frame_count=3,
        valid_frame_count=sum(frame.face_detected for frame in frames),
        dialogue_frames=session.vision_frames,
    )
    return session, snapshot


def _resolve_synchronous_stub(coroutine):
    """Run a stub coroutine without Windows' socket based event loop."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Stub unexpectedly suspended")


def test_checkin_fires_without_a_labelled_emotion():
    session, snapshot = _visual_session()
    session.turn_count = 2

    # 标签通道仍然拒收：neutral 且置信度 0.2，说不出名字。
    assert choose_visual_acknowledgment(session, "turn", snapshot) is None

    checkin = select_visual_checkin(session, "turn", snapshot, HAPPY_WORDS)
    assert checkin.reason == "discordance"
    assert checkin.discordance is not None
    assert checkin.discordance.text_polarity > 0
    assert checkin.discordance.vision_valence == pytest.approx(-0.6)
    assert checkin.discordance.difference == pytest.approx(1.36, abs=0.05)


def test_checkin_keeps_quiet_when_the_face_agrees_with_the_words():
    session, snapshot = _visual_session(valence=-0.7)
    session.turn_count = 2
    assert select_visual_checkin(session, "turn", snapshot, SAD_WORDS).reason == "no_discordance"


def test_checkin_keeps_quiet_without_any_emotion_words():
    """没有情绪词就不算矛盾，否则"今天考了三门"会被当成表里不一。"""

    session, snapshot = _visual_session()
    session.turn_count = 2
    for text in ("今天考了三门", "没什么特别的", "嗯，我在"):
        assert select_visual_checkin(session, "turn", snapshot, text).reason == "no_discordance"


def test_checkin_catches_the_lukewarm_answer():
    """"还行""还好"这类暧昧回答读成弱正向，配上明显偏负的脸就是该核对的情况。"""

    session, snapshot = _visual_session(valence=-0.6)
    session.turn_count = 2
    for text in ("还行吧", "还好", "挺好的"):
        checkin = select_visual_checkin(session, "turn", snapshot, text)
        assert checkin.reason == "discordance"
        assert checkin.discordance is not None
        assert checkin.discordance.text_polarity > 0


def test_checkin_never_contradicts_a_self_reported_complaint():
    """文字在诉苦、表情却偏正时不核对：不能拿摄像头的猜测反驳学生自己的话。"""

    session, snapshot = _visual_session(valence=0.5)
    session.turn_count = 2
    assert select_visual_checkin(
        session, "turn", snapshot, SAD_WORDS).reason == "no_discordance"

    # 对称判定（both）仍认得这种情况，只是默认不采用。
    symmetric = ConsistencyThresholds(discordance_direction="both")
    assert detect_turn_discordance(SAD_WORDS, snapshot, symmetric) is not None


def test_checkin_needs_both_opposite_direction_and_enough_gap():
    """同向而强度不同不算矛盾；反着来也要差得够明显。"""

    # "我挺开心的"约 +0.17，与 -0.10 只差 0.27，未达 0.4。
    session, snapshot = _visual_session(valence=-0.1)
    session.turn_count = 2
    assert select_visual_checkin(session, "turn", snapshot, "我挺开心的").reason == "no_discordance"

    session, snapshot = _visual_session(valence=-0.6)
    session.turn_count = 2
    assert select_visual_checkin(session, "turn", snapshot, "我挺开心的").reason == "discordance"

    # 把 gap 抬到 2.0 就等于关掉这条通道。
    off = ConsistencyThresholds(discordance_gap=2.0)
    assert detect_turn_discordance(HAPPY_WORDS, snapshot, off) is None


def test_checkin_shares_the_observation_gates():
    session, snapshot = _visual_session()
    limits = VisualEvidenceThresholds()

    session.turn_count = 1
    assert select_visual_checkin(
        session, "turn", snapshot, HAPPY_WORDS).reason == "cooldown"

    session.turn_count = 2
    assert select_visual_checkin(
        session, "missing", snapshot, HAPPY_WORDS).reason == "missing_segment"
    assert select_visual_checkin(
        session, "turn", None, HAPPY_WORDS).reason == "snapshot_mismatch"

    session.vision_segments["turn"].dialogue_frames[0].source = "mock"
    assert select_visual_checkin(
        session, "turn", snapshot, HAPPY_WORDS).reason == "unverified_source"
    session.vision_segments["turn"].dialogue_frames[0].source = "real"

    # 提过一次就进冷却，免得连着几轮盯着表情问。
    session.last_visual_observation_turn = 2
    assert select_visual_checkin(
        session, "turn", snapshot, HAPPY_WORDS).reason == "cooldown"

    faceless, faceless_snapshot = _visual_session(face=False)
    faceless.turn_count = 2
    assert select_visual_checkin(
        faceless, "turn", faceless_snapshot, HAPPY_WORDS).reason == "no_face"

    no_valence = VisionState(face_detected=True, emotion="neutral", emotion_confidence=0.2)
    assert detect_turn_discordance(HAPPY_WORDS, no_valence) is None
    assert limits.first_eligible_turn == 2


def test_prompt_asks_for_one_gentle_checkin():
    request = DialogueAgentRequest(
        conversation_history=[], decision=DialogueDecision(actions=["情绪"]),
        current_user_input=DialogueCurrentUserInput(text=HAPPY_WORDS),
        visual_discordance=DialogueVisualDiscordance(
            text_polarity=0.76, vision_valence=-0.6),
    )
    prompt = build_dialogue_user_prompt(request)
    assert "两者方向相反" in prompt
    assert "只核对一次" in prompt
    assert "不说他在掩饰、逞强或不诚实" in prompt
    assert "不要提摄像头、检测器或数值" in prompt

    request.visual_discordance = None
    fallback = build_dialogue_user_prompt(request)
    assert "本轮没有可口头提及的视觉观察" in fallback
    assert "两者方向相反" not in fallback


def test_dialogue_manager_asks_the_checkin(monkeypatch):
    monkeypatch.setattr("backend.core.dialogue_manager.asyncio.run", _resolve_synchronous_stub)
    session, snapshot = _visual_session()
    session.turn_count = 2
    session.conversation_history.append(Message(role=MessageRole.USER, content="还好"))

    class Policy:
        def predict(self, history):
            return PolicyDecision(actions=[DialogueAction.SLEEP])

    class Dialogue:
        request = None

        async def generate_reply(self, request):
            self.request = request
            return DialogueAgentResponse(
                reply="你说今天特别开心，不过看你好像有点累，是这样吗？")

    dialogue = Dialogue()
    result = DialogueManager(policy_client=Policy(), dialogue_agent=dialogue).process_turn(
        HAPPY_WORDS, session, snapshot, use_latest_states=False, utterance_id="turn")

    # 核对不是"说出某个情绪"，所以 visual_observation 必须留空。
    assert dialogue.request.visual_observation is None
    assert dialogue.request.visual_discordance is not None
    assert dialogue.request.visual_discordance.vision_valence == pytest.approx(-0.6)
    assert result.visual_feedback.reason == "discordance"
    assert session.last_visual_observation_turn == 2


def test_labelled_observation_wins_over_checkin(monkeypatch):
    """能说出表情名字时走原通道，不再额外核对，避免同一句前后打架。"""

    monkeypatch.setattr("backend.core.dialogue_manager.asyncio.run", _resolve_synchronous_stub)
    session, snapshot = _visual_session(label="sad", confidence=0.95, valence=-0.6)
    session.turn_count = 2
    session.conversation_history.append(Message(role=MessageRole.USER, content="还好"))

    class Policy:
        def predict(self, history):
            return PolicyDecision(actions=[DialogueAction.SLEEP])

    class Dialogue:
        request = None

        async def generate_reply(self, request):
            self.request = request
            return DialogueAgentResponse(reply="你看起来有点难过，最近睡得怎么样？")

    dialogue = Dialogue()
    result = DialogueManager(policy_client=Policy(), dialogue_agent=dialogue).process_turn(
        HAPPY_WORDS, session, snapshot, use_latest_states=False, utterance_id="turn")

    assert dialogue.request.visual_observation == "sad"
    assert dialogue.request.visual_discordance is None
    assert result.visual_feedback.reason == "mentioned"
