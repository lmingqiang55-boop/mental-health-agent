"""决策模型选动作，对话 Agent 根据完整上下文生成真正的下一句。"""

import asyncio

from backend.agents.dialogue_agent import DialogueAgent, DialogueAgentError
from backend.core.screening_flow import completion_reason, limit_topic, record_answer
from backend.core.multimodal_consistency import TurnDiscordance
from backend.core.visual_acknowledgment import (
    VisualAcknowledgment, select_visual_checkin, select_visual_observation,
    select_visual_tone,
)
from backend.llm.config import DeepSeekConfigError, load_deepseek_config
from backend.llm.deepseek_client import DeepSeekClient, DeepSeekClientError
from backend.models.dialogue import (
    DialogueAgentRequest, DialogueCurrentUserInput, DialogueDecision,
    DialogueHistoryMessage, DialogueVisual, DialogueVisualDiscordance,
)
from backend.models.enums import MessageRole, SessionStage
from backend.models.responses import DialogueResponsePayload, VisualFeedback
from backend.models.states import SessionState, VisionState, _now
from backend.policy.client import (
    HttpPolicyClient,
    PolicyClientError,
    PolicyDecision,
    get_policy_client,
)
class DialogueUnavailable(RuntimeError):
    """The dialogue generation service cannot produce a usable reply."""


class ScreeningFinished(RuntimeError):
    """A closed screening accepts no further ordinary chat turns."""


class DialogueManager:
    """决策模型决定下一步动作，对话 Agent 生成真正的下一句。

    **本类不做任何安全判定。** 安全由 ``backend/safety`` 的 Safety Agent
    在进入本类之前完成（见 ``backend/api/chat.py``）：安全分支不会走到这里。

    Args:
        policy_client: 决策模型客户端；测试可注入模拟响应，不注入时首次
            使用时按环境变量构造，构造失败会转成 ``PolicyClientError``。
    """

    def __init__(self, policy_client: HttpPolicyClient | None = None,
                 dialogue_agent: DialogueAgent | None = None) -> None:
        self._policy = policy_client
        self._dialogue_agent = dialogue_agent

    def process_turn(self, user_text: str, session: SessionState,
                     vision_snapshot: VisionState | None = None,
                     *, use_latest_states: bool = True,
                     utterance_id: str | None = None) -> DialogueResponsePayload:
        latest = session.latest_vision_state if use_latest_states else None
        if latest is not None:
            # Only recent, timezone-aware observations can inform a legacy text turn.
            stamp = latest.timestamp
            age = (_now() - stamp).total_seconds() if stamp.tzinfo is not None else -1
            if not 0 <= age <= 5:
                latest = None
        current_vision = vision_snapshot if vision_snapshot is not None else latest

        if session.current_stage in (SessionStage.ASSESSMENT_READY, SessionStage.COMPLETED):
            raise ScreeningFinished("本次筛查已收尾，请生成结果或重新开始。")
        record_answer(session)
        ending = completion_reason(session, user_text)
        if ending is not None:
            reply = self._generate_reply(
                session, user_text, current_vision, None, None, closing_reason=ending)
            session.current_stage = SessionStage.ASSESSMENT_READY
            session.screening_progress.end_reason = ending
            return DialogueResponsePayload(
                reply=reply, next_strategy="结束本次筛查",
                current_stage=session.current_stage.value,
                assessment_ready=True, completion_reason=ending,
                screening_progress=session.screening_progress,
                visual_feedback={"reason": "closing"},
            )

        decision = limit_topic(session, self._decide(session))
        visual = select_visual_observation(
            session, utterance_id, current_vision)
        visual_ack = visual.emotion
        # 表情说不出名字时退一步：这一句是不是"说的和显示的反着来"？
        # 这条通道只要真实新鲜的人脸加有效价，不要求表情有高置信度的名字。
        checkin = (
            select_visual_checkin(session, utterance_id, current_vision, user_text)
            if visual_ack is None else None
        )
        discordance = checkin.discordance if checkin is not None else None
        # 既不构成矛盾、又拿不到说得出口的名字时，只剩最后一条通道：只凭连续效价
        # 说一句整体语气。三选一，一轮最多提一次外观。
        reading = (
            select_visual_tone(session, utterance_id, current_vision)
            if visual_ack is None and discordance is None else None
        )
        tone = reading.tone if reading is not None else None
        if discordance is not None:
            visual = VisualFeedback(reason=checkin.reason)
        elif tone is not None:
            visual = VisualFeedback(reason=reading.reason)
        reply = self._generate_reply(
            session, user_text, current_vision, decision, visual_ack,
            visual_discordance=discordance, visual_tone=tone)
        if visual_ack is not None:
            session.last_visual_observation_turn = session.turn_count
            visual.reason = "mentioned" if any(
                phrase in reply for phrase in ("看起来", "看上去", "表情", "神情", "脸上", "显得")
            ) else "generation_omitted"
        elif discordance is not None or tone is not None:
            # 核对与语气同样算"提过一次外观"，要进冷却，免得连着几轮盯着表情说。
            session.last_visual_observation_turn = session.turn_count
        return DialogueResponsePayload(
            reply=reply,
            next_strategy=decision.actions[-1].value,
            current_stage=session.current_stage.value,
            screening_progress=session.screening_progress,
            visual_feedback=visual,
        )

    # -- 决策 ------------------------------------------------------------

    def _decide(self, session: SessionState) -> PolicyDecision:
        """调用决策模型；不可用时抛错，不退回规则提问。"""
        if self._policy is None:
            try:
                self._policy = get_policy_client()
            except ValueError as exc:
                raise PolicyClientError(
                    f"决策模型配置无效：{exc}") from exc
        return self._policy.predict(session.conversation_history)

    def _generate_reply(self, session: SessionState, user_text: str,
                        current_vision: VisionState | None,
                        decision: PolicyDecision | None,
                        visual_ack: VisualAcknowledgment | None,
                        *, closing_reason: str | None = None,
                        visual_discordance: TurnDiscordance | None = None,
                        visual_tone: str | None = None) -> str:
        """Pass the selected actions to the dialogue Agent; never use canned questions."""
        history = session.conversation_history
        if (history and history[-1].role == MessageRole.USER
                and history[-1].content == user_text):
            history = history[:-1]
        previous = [DialogueHistoryMessage(
            role=message.role.value, content=message.content,
            visual=_dialogue_visual(message.vision_snapshot),
        ) for message in history]
        actions = [action.value for action in decision.actions] if decision else ["结束本次筛查"]
        topics = [action for action in actions if action != "共情安慰"]
        request = DialogueAgentRequest(
            conversation_history=previous,
            decision=DialogueDecision(
                actions=actions,
                topic=topics[-1] if topics else None,
                reason=closing_reason,
                extra={"topic_turns": session.screening_progress.topic_turns},
            ),
            current_user_input=DialogueCurrentUserInput(
                text=user_text, visual=_dialogue_visual(current_vision),
            ),
            visual_observation=visual_ack,
            visual_discordance=(
                DialogueVisualDiscordance(
                    text_polarity=visual_discordance.text_polarity,
                    vision_valence=visual_discordance.vision_valence,
                )
                if visual_discordance is not None else None
            ),
            visual_tone=visual_tone if visual_tone in ("low", "bright") else None,
            finish_screening=closing_reason is not None,
        )
        if self._dialogue_agent is not None:
            try:
                return asyncio.run(self._dialogue_agent.generate_reply(request)).reply
            except (DialogueAgentError, DeepSeekClientError) as exc:
                raise DialogueUnavailable("对话 Agent 生成失败") from exc

        try:
            client = DeepSeekClient(load_deepseek_config())
        except DeepSeekConfigError as exc:
            raise DialogueUnavailable("对话 Agent 缺少有效的 DeepSeek 配置") from exc

        async def generate() -> str:
            try:
                return (await DialogueAgent(client).generate_reply(request)).reply
            finally:
                await client.client.close()

        try:
            return asyncio.run(generate())
        except (DialogueAgentError, DeepSeekClientError) as exc:
            raise DialogueUnavailable("对话 Agent 生成失败") from exc

    # -- 回复生成 --------------------------------------------------------


def _dialogue_visual(state: VisionState | None) -> DialogueVisual | None:
    if state is None:
        return None
    values = state.model_dump(exclude={"timestamp"}, exclude_none=True)
    known = {key: values.pop(key, None)
             for key in ("valence", "arousal", "engagement")}
    return DialogueVisual(**known, extra=values)
