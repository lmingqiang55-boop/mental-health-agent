"""说不出名字、也不构成矛盾时，只凭连续效价说一句整体语气。

这是把"视觉只作辅助"变成"视觉真的参与关心"的那一步：模型对真实学生人脸
最常给出的就是 neutral 或置信度很低的输出，标签通道永远拒收；`valence`
却一直是有值的。默认只往"关心"的方向说——表情明显消极时才提，
**不主动说"你看起来挺开心"**（对方正在诉苦时那是冒犯）。
"""

import pytest

from backend.core.dialogue_manager import DialogueManager
from backend.core.visual_acknowledgment import (
    TONE_LABELS,
    choose_visual_acknowledgment,
    select_visual_checkin,
    select_visual_tone,
)
from backend.core.vision_thresholds import VisualEvidenceThresholds
from backend.models.dialogue import (
    DialogueAgentRequest,
    DialogueAgentResponse,
    DialogueCurrentUserInput,
    DialogueDecision,
)
from backend.models.enums import MessageRole
from backend.models.states import (
    Message,
    SessionState,
    VisionFrameObservation,
    VisionSegment,
    VisionState,
)
from backend.policy.client import PolicyDecision
from backend.prompts.dialogue_prompt import build_dialogue_user_prompt
from backend.vision.aggregation import aggregate_frames

#: 文字读出来是积极的（"我今天特别开心" → 约 +0.76）。
HAPPY_WORDS = "我今天特别开心"
#: 文字读出来是消极的（"我最近特别难过" → 约 -0.76）。
SAD_WORDS = "我最近特别难过"


def _visual_session(label="neutral", confidence=0.2, *, valence=-0.5, face=True,
                    valences=None):
    """默认造一张"表情说不出口、但脸明显偏负"的画面——标签通道会被拒。"""

    session = SessionState(session_id="tone-test", active_vision_capture_id="camera")
    values = list(valences) if valences is not None else [valence] * 3
    frames = [VisionState(face_detected=face, emotion=label,
                          emotion_confidence=confidence, valence=value)
              for value in values]
    snapshot = aggregate_frames(frames)
    session.vision_frames = [VisionFrameObservation(
        frame_id=f"frame-{index}", capture_id="camera",
        captured_at_ms=index * 100, image_digest="test", state=frame, source="real",
    ) for index, frame in enumerate(frames)]
    session.vision_segments["turn"] = VisionSegment(
        capture_id="camera", start_ms=0, end_ms=300,
        vision_snapshot=snapshot, frame_count=len(frames),
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


def test_tone_speaks_when_the_label_channel_cannot():
    session, snapshot = _visual_session()
    session.turn_count = 2

    # 标签通道拒收（neutral + 0.2），也不是矛盾（文字与脸同向偏负）。
    assert choose_visual_acknowledgment(session, "turn", snapshot) is None
    assert select_visual_checkin(session, "turn", snapshot, SAD_WORDS).reason == "no_discordance"

    reading = select_visual_tone(session, "turn", snapshot)
    assert reading.reason == "tone"
    assert reading.tone == "low"
    assert reading.valence == pytest.approx(-0.5)
    assert TONE_LABELS["low"].startswith("偏低落")


def test_tone_also_fires_when_the_words_say_nothing():
    """文字读不出情绪时（"今天考了三门"）也不妨碍说一句语气。"""

    session, snapshot = _visual_session()
    session.turn_count = 2
    assert select_visual_tone(session, "turn", snapshot).tone == "low"


def test_tone_stays_quiet_on_a_bright_face():
    """默认只往"关心"的方向说：不主动告诉学生"你看起来挺开心"。"""

    session, snapshot = _visual_session(valence=0.5)
    session.turn_count = 2
    reading = select_visual_tone(session, "turn", snapshot)
    assert reading.reason == "tone_direction"
    assert reading.tone is None
    assert reading.valence == pytest.approx(0.5)

    both = VisualEvidenceThresholds(tone_direction="both")
    assert select_visual_tone(session, "turn", snapshot, both).tone == "bright"


def test_tone_needs_frames_that_agree():
    """只有一帧恰好偏负不算，更可能是识别抖动。"""

    session, snapshot = _visual_session(valences=[-0.5, -0.5, 0.2])
    session.turn_count = 2
    assert select_visual_tone(session, "turn", snapshot).reason == "unstable_valence"

    faceless_valence = [VisionState(face_detected=True, emotion="neutral",
                                    emotion_confidence=0.2) for _ in range(3)]
    empty, empty_snapshot = _visual_session()
    empty.vision_frames = [VisionFrameObservation(
        frame_id=f"frame-{index}", capture_id="camera", captured_at_ms=index * 100,
        image_digest="test", state=frame, source="real",
    ) for index, frame in enumerate(faceless_valence)]
    empty.vision_segments["turn"] = VisionSegment(
        capture_id="camera", start_ms=0, end_ms=300,
        vision_snapshot=aggregate_frames(faceless_valence), frame_count=3,
        valid_frame_count=3, dialogue_frames=empty.vision_frames,
    )
    empty.turn_count = 2
    assert select_visual_tone(empty, "turn", empty.vision_segments["turn"].vision_snapshot).reason == "no_valence"


def test_tone_ignores_a_faint_valence():
    """-0.1 这种"略偏负"落在识别误差里，不值得开口。"""

    session, snapshot = _visual_session(valence=-0.1)
    session.turn_count = 2
    reading = select_visual_tone(session, "turn", snapshot)
    assert reading.reason == "faint_valence"
    assert reading.tone is None


def test_tone_shares_the_observation_gates():
    session, snapshot = _visual_session()

    session.turn_count = 1
    assert select_visual_tone(session, "turn", snapshot).reason == "cooldown"

    session.turn_count = 2
    assert select_visual_tone(session, "missing", snapshot).reason == "missing_segment"
    assert select_visual_tone(session, "turn", None).reason == "snapshot_mismatch"

    session.vision_segments["turn"].dialogue_frames[0].source = "mock"
    assert select_visual_tone(session, "turn", snapshot).reason == "unverified_source"
    session.vision_segments["turn"].dialogue_frames[0].source = "real"

    session.last_visual_observation_turn = 2
    assert select_visual_tone(session, "turn", snapshot).reason == "cooldown"


def test_tone_thresholds_are_overridable():
    """门槛必须能用环境变量改：产品调档位不该改代码。"""

    assert VisualEvidenceThresholds().tone_valence == 0.2
    assert VisualEvidenceThresholds().tone_direction == "low"
    assert VisualEvidenceThresholds(tone_valence=0.5).tone_valence == 0.5
    assert VisualEvidenceThresholds(tone_direction="both").tone_direction == "both"


def test_prompt_describes_tone_without_naming_an_emotion():
    request = DialogueAgentRequest(
        conversation_history=[], decision=DialogueDecision(target_item='depressed_mood', question_goal='了解过去两周该项表现及尚缺的信息'),
        current_user_input=DialogueCurrentUserInput(text=SAD_WORDS),
        visual_tone="low",
    )
    prompt = build_dialogue_user_prompt(request)
    # 新提示词允许模型只调整语气，也可以完全不提外观。
    assert "外观线索" in prompt
    assert "优先用试探语气简短描述一次" in prompt
    assert "可以暂不提及" in prompt
    assert "必须用一句外观描述" not in prompt
    assert "不能命名具体情绪" in prompt
    assert "不要提摄像头、检测器或数值" in prompt

    request.visual_tone = None
    fallback = build_dialogue_user_prompt(request)
    assert "本轮没有可口头提及的视觉观察" in fallback
    assert "外观线索" not in fallback


def test_dialogue_manager_mentions_the_tone(monkeypatch):
    monkeypatch.setattr("backend.core.dialogue_manager.asyncio.run", _resolve_synchronous_stub)
    session, snapshot = _visual_session()
    session.turn_count = 2
    session.conversation_history.append(Message(role=MessageRole.USER, content="最近挺累"))

    class Policy:
        def predict(self, history, **kwargs):
            return PolicyDecision(target_item='sleep_disturbance', question_goal='了解过去两周该项表现及尚缺的信息')

    class Dialogue:
        request = None

        async def generate_reply(self, request):
            self.request = request
            return DialogueAgentResponse(reply="听起来确实挺累的，你看起来也有点疲惫。")

    dialogue = Dialogue()
    result = DialogueManager(policy_client=Policy(), dialogue_agent=dialogue).process_turn(
        SAD_WORDS, session, snapshot, use_latest_states=False, utterance_id="turn")

    assert dialogue.request.visual_observation is None
    assert dialogue.request.visual_discordance is None
    assert dialogue.request.visual_tone == "low"
    assert result.visual_feedback.reason == "tone"
    assert session.last_visual_observation_turn == 2


def test_checkin_wins_over_tone(monkeypatch):
    """说的和显示的反着来时先核对，不再另外报语气，免得同一句前后打架。"""

    monkeypatch.setattr("backend.core.dialogue_manager.asyncio.run", _resolve_synchronous_stub)
    session, snapshot = _visual_session(valence=-0.6)
    session.turn_count = 2
    session.conversation_history.append(Message(role=MessageRole.USER, content="挺好"))

    class Policy:
        def predict(self, history, **kwargs):
            return PolicyDecision(target_item='sleep_disturbance', question_goal='了解过去两周该项表现及尚缺的信息')

    class Dialogue:
        request = None

        async def generate_reply(self, request):
            self.request = request
            return DialogueAgentResponse(reply="你说还挺好的，不过看你好像有点累，是这样吗？")

    dialogue = Dialogue()
    result = DialogueManager(policy_client=Policy(), dialogue_agent=dialogue).process_turn(
        HAPPY_WORDS, session, snapshot, use_latest_states=False, utterance_id="turn")

    assert dialogue.request.visual_discordance is not None
    assert dialogue.request.visual_tone is None
    assert result.visual_feedback.reason == "discordance"
