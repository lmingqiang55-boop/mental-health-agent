"""Regressions from the reported repetitive conversation and missing visual cues."""

import asyncio
import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from conftest import create_consented_session

from backend.agents.dialogue_agent import DialogueAgent, DialogueAgentError
from backend.api import chat, vision
from backend.core.screening_flow import MAX_TURNS
from backend.core.session_manager import session_manager
from backend.main import app
from backend.models.dialogue import DialogueAgentRequest, DialogueAgentResponse
from backend.safety.schemas import SafetyLevel
from backend.vision import detector as detection
from backend.models.states import VisionState

client = TestClient(app)


def _session():
    return create_consented_session(client)


def _send(sid, text, **extra):
    return client.post('/api/chat', json={'session_id': sid, 'text': text, **extra})


def _natural_stub(monkeypatch):
    class Stub:
        async def generate_reply(self, request):
            if request.finish_screening:
                return DialogueAgentResponse(reply='这次先聊到这里，可以生成本次对话的初步结果。')
            if request.visual_observation:
                return DialogueAgentResponse(reply='你看起来有点不开心，最近睡眠怎么样？')
            return DialogueAgentResponse(reply='最近有什么变化？')
    monkeypatch.setattr(chat.dialogue_manager, '_dialogue_agent', Stub())


def test_repeated_policy_topic_visits_gaps_then_stops_without_assessment(
    monkeypatch, policy_stub, safety_stub
):
    _natural_stub(monkeypatch)
    policy_stub('depressed_mood')
    sid = _session()
    strategies = []
    for turn in range(MAX_TURNS):
        response = _send(sid, f'第 {turn} 次回答', utterance_id=f'u{turn}')
        assert response.status_code == 200
        body = response.json()
        strategies.append(body['next_strategy'])
        if body['assessment_ready']:
            break
    assert body['current_stage'] == 'assessment_ready'
    assert body['completion_reason'] == 'turn_limit'
    assert body['turn_count'] == MAX_TURNS == 35
    assert '？' not in body['reply'] and '?' not in body['reply']
    # 后端不按次数换题，也不把次数当作充分性依据。
    assert body['screening_progress']['topic_turns'] == {'depressed_mood': 34}
    assert session_manager.get_session(sid).assessment_result_id is None
    repeat = _send(sid, f'第 {turn} 次回答', utterance_id=f'u{turn}')
    assert repeat.json() == body
    previous = session_manager.get_session(sid)
    rejected = _send(sid, '普通新消息')
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'SCREENING_FINISHED'
    assert session_manager.get_session(sid) == previous
    # 安全分支优先于「已收尾」判定：高危消息仍要被处理，而不是 409
    safety_stub.force(SafetyLevel.HIGH, message='我很担心你，请先联系身边可信任的人。')
    crisis = _send(sid, '我想自杀')
    assert crisis.status_code == 200
    assert crisis.json()['current_stage'] == 'safety_stop'
    assert crisis.json()['safety']['route'] == 'safety_stop'
    assert crisis.json()['assessment_ready'] is False


def test_turn_limit_and_user_requested_end(monkeypatch, policy_stub):
    _natural_stub(monkeypatch)
    policy_stub('sleep_disturbance')
    sid = _session()
    session_manager.modify_session(sid, lambda state: setattr(state, 'turn_count', MAX_TURNS - 1))
    response = _send(sid, '一个月了').json()
    assert response['completion_reason'] == 'turn_limit'
    assert response['assessment_ready'] is True
    sid = _session()
    assert _send(sid, '这次先不聊了').json()['completion_reason'] == 'user_requested'
    sid = _session()
    assert not _send(sid, '不要结束对话').json()['assessment_ready']


def test_failed_closing_does_not_commit_progress_or_ready_stage(monkeypatch, policy_stub):
    _natural_stub(monkeypatch)
    policy_stub('sleep_disturbance')
    sid = _session()
    _send(sid, '最近睡不着')
    previous = session_manager.get_session(sid)

    class Failing:
        async def generate_reply(self, request):
            assert request.finish_screening
            raise DialogueAgentError('unavailable')

    monkeypatch.setattr(chat.dialogue_manager, '_dialogue_agent', Failing())
    response = _send(sid, '先不聊了', utterance_id='closing')
    assert response.status_code == 503
    assert session_manager.get_session(sid) == previous
    _natural_stub(monkeypatch)
    assert _send(sid, '先不聊了', utterance_id='closing').json()['assessment_ready']


def test_custom_real_detector_short_reply_uses_frozen_recent_window(monkeypatch, policy_stub):
    class Real(detection.VisionDetector):
        def analyze_frame(self, frame=None):
            return VisionState(face_detected=True, emotion='sad', emotion_confidence=0.95)
    real = Real()
    monkeypatch.setattr(detection, '_detector', real)
    _natural_stub(monkeypatch)
    policy_stub('sleep_disturbance')
    sid = _session()
    _send(sid, '第一句'); _send(sid, '第二句')
    client.post('/api/vision/capture', json={
        'session_id': sid, 'capture_id': 'camera', 'generation': 1, 'active': True})
    image = BytesIO()
    Image.new('RGB', (32, 32)).save(image, format='JPEG')
    encoded = base64.b64encode(image.getvalue()).decode()
    for at in (1000, 1500, 2000):
        response = client.post('/api/vision/frame', json={
            'session_id': sid, 'image_base64': encoded, 'capture_id': 'camera',
            'frame_id': str(at), 'captured_at_ms': at})
        assert response.status_code == 200
    segment = client.post('/api/vision/segment', json={
        'session_id': sid, 'utterance_id': 'short', 'capture_id': 'camera',
        'start_ms': 1900, 'end_ms': 2200}).json()
    assert segment['frame_count'] == 1  # Evaluation remains sentence-aligned.
    assert 'dialogue_frames' not in segment
    # A late frame must not alter either the aligned snapshot or the cue window.
    real.analyze_frame = lambda frame: VisionState(
        face_detected=True, emotion='angry', emotion_confidence=0.95)
    assert client.post('/api/vision/frame', json={
        'session_id': sid, 'image_base64': encoded, 'capture_id': 'camera',
        'frame_id': 'late', 'captured_at_ms': 2100}).status_code == 200
    assert client.post('/api/vision/segment', json={
        'session_id': sid, 'utterance_id': 'short', 'capture_id': 'camera',
        'start_ms': 1900, 'end_ms': 2200}).json() == segment
    assert len(session_manager.get_session(sid).vision_segments['short'].dialogue_frames) == 3
    response = _send(sid, '是', utterance_id='short', vision_snapshot=segment['vision_snapshot']).json()
    assert response['visual_feedback'] == {'reason': 'mentioned', 'emotion': 'sad'}
    assert '你看起来' in response['reply']
    assert client.get('/api/vision/status').json()['provider'] == 'custom'
    # Closing this capture prevents even a previously frozen window from being used.
    client.post('/api/vision/capture', json={
        'session_id': sid, 'capture_id': 'camera', 'generation': 2, 'active': False})
    from backend.core.visual_acknowledgment import select_visual_observation
    state = session_manager.get_session(sid)
    assert select_visual_observation(state, 'short', state.vision_segments['short'].vision_snapshot).reason == 'capture_inactive'


@pytest.mark.parametrize('first,second,history,closing', [
    ('那最近吃饭是经常吃得特别多，还是有时很多、有时不太想吃呢？',
     '这种变化大概从什么时候开始的？',
     ['那最近吃饭会经常吃得特别多，还是有时很多、有时不太想吃呢？'], False),
    ('听你这么说，每天这样确实难受。一般能吃下多少？',
     '一般能吃下多少？',
     ['听你这么说，有时会很难受。最近食欲怎么样？', '听你这么说，那种感觉不容易。大概有多久？'], False),
    ('这次先聊到这里，你还有什么想说的吗？',
     '这次先聊到这里，可以生成结果。', [], True),
])
def test_generator_rewrites_near_duplicate_opening_or_closing_question(first, second, history, closing):
    class LLM:
        calls = 0
        async def generate(self, **kwargs):
            self.calls += 1
            return first if self.calls == 1 else second
    llm = LLM()
    request = DialogueAgentRequest.model_validate({
        'conversation_history': [{'role': 'assistant', 'content': text} for text in history],
        'decision': {'target_item': 'appetite_change', 'question_goal': '了解过去两周该项表现及尚缺的信息'}, 'current_user_input': {'text': '暴饮暴食'},
        'finish_screening': closing,
    })
    assert asyncio.run(DialogueAgent(llm).generate_reply(request)).reply == second
    assert llm.calls == 2
