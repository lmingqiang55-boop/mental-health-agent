"""决策模型规划具体评估目标，对话 Agent 根据完整上下文生成真正的下一句。

本模块同时服务两条**等价**调用路径，二者共用下面这些模块级函数，
以保证两条路径不会行为漂移：

- :meth:`DialogueManager.process_turn`：顺序执行（``DIALOGUE_ENGINE=legacy``）；
- :mod:`backend.graph`：把同一组步骤拆成 LangGraph 节点（``DIALOGUE_ENGINE=graph``）。
"""

import asyncio
from dataclasses import dataclass

from backend.agents.dialogue_agent import (
    DialogueAgent, DialogueAgentError,
)
from backend.core.screening_flow import (
    MAX_TURNS, adopt_decision, check_model_completion, completion_reason, record_answer,
)
from backend.core.multimodal_consistency import TurnDiscordance
from backend.core.visual_acknowledgment import (
    # VISUAL_MENTION_PHRASES / mentions_appearance 在视觉模块里定义、在这里再导出：
    # 以前 dialogue_agent 与本文件各存一份同样内容的词表，改文案只会改到一处，
    # 于是"允许说的"和"判定说没说出口"会悄悄分家。
    VISUAL_MENTION_PHRASES, VisualAcknowledgment, mentions_appearance,
    select_visual_checkin, select_visual_observation, select_visual_tone,
)
from backend.llm.config import DeepSeekConfigError, load_deepseek_config
from backend.llm.deepseek_client import DeepSeekClient, DeepSeekClientError
from backend.models.dialogue import (
    DialogueAgentRequest, DialogueAgentResponse, DialogueCurrentUserInput,
    DialogueDecision, DialogueHistoryMessage, DialogueVisual, DialogueVisualDiscordance,
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


@dataclass(frozen=True)
class VisualChannels:
    """一轮里生成前可用的视觉线索。

    三条通道**互斥**，一轮最多提一次外观：说得出口的表情名字、
    "文字与表情方向相反"的温和核对、只凭连续效价的整体语气。
    """

    feedback: VisualFeedback
    acknowledgment: VisualAcknowledgment | None = None
    discordance: TurnDiscordance | None = None
    tone: str | None = None


def resolve_current_vision(
    session: SessionState, vision_snapshot: VisionState | None,
    use_latest_states: bool,
) -> VisionState | None:
    """本轮可用的视觉快照：显式传入的优先，否则用足够新鲜的最近状态。"""
    latest = session.latest_vision_state if use_latest_states else None
    if latest is not None:
        # Only recent, timezone-aware observations can inform a legacy text turn.
        stamp = latest.timestamp
        age = (_now() - stamp).total_seconds() if stamp.tzinfo is not None else -1
        if not 0 <= age <= 5:
            latest = None
    return vision_snapshot if vision_snapshot is not None else latest


def ensure_screening_open(session: SessionState) -> None:
    if session.current_stage in (SessionStage.ASSESSMENT_READY, SessionStage.COMPLETED):
        raise ScreeningFinished("本次筛查已收尾，请生成结果或重新开始。")


def history_before_turn(session: SessionState,
                        user_text: str) -> list[DialogueHistoryMessage]:
    """本轮生成/路由用的历史：**不含**本轮这条用户输入。

    ``/api/chat`` 在调用之前已经把本轮用户消息写进了 ``conversation_history``，
    因此这里在末尾那条正是本轮输入时把它去掉，避免同一句话在 Prompt 里出现两次。
    生成与路由共用本函数，两处不会各自判断一遍而分家。
    """
    history = session.conversation_history
    if (history and history[-1].role == MessageRole.USER
            and history[-1].content == user_text):
        history = history[:-1]
    return [DialogueHistoryMessage(
        role=message.role.value, content=message.content,
        visual=_dialogue_visual(message.vision_snapshot),
    ) for message in history]


def select_visual_channels(
    session: SessionState, utterance_id: str | None,
    current_vision: VisionState | None, user_text: str,
) -> VisualChannels:
    """三选一挑出本轮的外观线索；不做任何会话状态写入。"""
    visual = select_visual_observation(session, utterance_id, current_vision)
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
    return VisualChannels(feedback=visual, acknowledgment=visual_ack,
                          discordance=discordance, tone=tone)


def finalize_visual_feedback(
    session: SessionState, channels: VisualChannels, reply: str,
) -> None:
    """生成之后才敢记账：**真的说出口了**才进冷却。

    这一轮模型要是没提外观，学生什么都没听到，就不该把 4 轮冷却记在账上。
    原实现连"没提到"（``generation_omitted``）也照样推进冷却，与本函数
    "提到过就进冷却"的本意相反：模型沉默一次，后面 4 轮都不会再给线索，
    演示里就会出现"素材明明有、全场一句外观关怀都没有"。现在改成说了才进
    冷却，没说就留白，下一轮还能再试——而只要说了就一定会进冷却，所以
    "连着几轮盯着表情说"仍然被挡住。
    """
    provided = (channels.acknowledgment is not None
                or channels.discordance is not None
                or channels.tone is not None)
    mentioned = mentions_appearance(reply)
    if channels.acknowledgment is not None:
        channels.feedback.reason = "mentioned" if mentioned else "generation_omitted"
    # 本轮根本没给线索时不记账：回复里恰好出现"看起来"不该算作提过一次外观。
    if provided and mentioned:
        session.last_visual_observation_turn = session.turn_count


def open_payload(
    session: SessionState, response: DialogueAgentResponse, next_strategy: str,
    visual_feedback: VisualFeedback,
) -> DialogueResponsePayload:
    """普通轮次的响应载荷；legacy 与 graph 共用，避免两处各写一份。

    ``response.messages`` 是本轮的气泡（1~3 条），``response.reply`` 是全文投影。
    """
    return DialogueResponsePayload(
        reply=response.reply, messages=response.messages,
        next_strategy=next_strategy,
        current_stage=session.current_stage.value,
        screening_progress=session.screening_progress,
        visual_feedback=visual_feedback,
    )


def closing_payload(
    session: SessionState, response: DialogueAgentResponse, ending: str,
) -> DialogueResponsePayload:
    """收尾轮次的响应载荷；调用前调用方须已推进会话阶段。"""
    return DialogueResponsePayload(
        reply=response.reply, messages=response.messages,
        next_strategy="结束本次筛查",
        current_stage=session.current_stage.value,
        assessment_ready=True, completion_reason=ending,
        screening_progress=session.screening_progress,
        visual_feedback={"reason": "closing"},
    )


class DialogueManager:
    """决策模型规划下一轮访谈目标，对话 Agent 生成真正的下一句。

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
        current_vision = resolve_current_vision(
            session, vision_snapshot, use_latest_states)
        ensure_screening_open(session)
        record_answer(session)
        ending = completion_reason(session, user_text)
        if ending is not None:
            return self.finish_screening(
                user_text, session, current_vision, ending)

        decision = self.decide(session)
        if decision.is_finished:
            return self.finish_screening(
                user_text, session, current_vision, "model_finished")
        adopt_decision(session, decision)
        channels = select_visual_channels(
            session, utterance_id, current_vision, user_text)
        response = self.reply_for_decision(
            session, user_text, current_vision, decision, channels)
        finalize_visual_feedback(session, channels, response.reply)
        return open_payload(
            session, response, decision.target_label, channels.feedback)

    # -- 供 backend.graph 复用的公开入口 ---------------------------------
    #
    # 图节点必须走这三个方法，而不是 ``_decide`` / ``_generate_reply``，
    # 这样"决策怎么调""回复怎么生成"只有一份实现，两条路径不会漂移。

    def decide(self, session: SessionState) -> PolicyDecision:
        """调用决策模型，接受结束前校验11项是否各收到过一次回答。"""
        return check_model_completion(session, self._decide(session))

    def reply_for_decision(self, session: SessionState, user_text: str,
                           current_vision: VisionState | None,
                           decision: PolicyDecision,
                           channels: VisualChannels) -> DialogueAgentResponse:
        """按决策生成回复（1~3 条消息），并带上本轮选中的视觉线索。"""
        return self._generate_reply(
            session, user_text, current_vision, decision, channels.acknowledgment,
            visual_discordance=channels.discordance, visual_tone=channels.tone)

    def closing_reply(self, user_text: str, session: SessionState,
                      current_vision: VisionState | None,
                      ending: str) -> DialogueAgentResponse:
        """收尾轮的回复正文；同时推进会话阶段与收尾原因。"""
        response = self._generate_reply(
            session, user_text, current_vision, None, None, closing_reason=ending)
        session.current_stage = SessionStage.ASSESSMENT_READY
        session.screening_progress.end_reason = ending
        session.screening_progress.pending_topic = None
        return response

    def finish_screening(self, user_text: str, session: SessionState,
                         current_vision: VisionState | None,
                         ending: str) -> DialogueResponsePayload:
        """收尾轮：只提示生成结果、不再提问，也不选集视觉线索。"""
        response = self.closing_reply(user_text, session, current_vision, ending)
        return closing_payload(session, response, ending)

    # -- 决策 ------------------------------------------------------------

    def _decide(self, session: SessionState) -> PolicyDecision:
        """调用决策模型；不可用时抛错，不退回规则提问。"""
        if self._policy is None:
            try:
                self._policy = get_policy_client()
            except ValueError as exc:
                raise PolicyClientError(
                    f"决策模型配置无效：{exc}") from exc
        return self._policy.predict(
            session.conversation_history, turn_count=session.turn_count + 1,
            max_turns=MAX_TURNS,
            item_answer_counts=session.screening_progress.topic_turns)

    def _generate_reply(self, session: SessionState, user_text: str,
                        current_vision: VisionState | None,
                        decision: PolicyDecision | None,
                        visual_ack: VisualAcknowledgment | None,
                        *, closing_reason: str | None = None,
                        visual_discordance: TurnDiscordance | None = None,
                        visual_tone: str | None = None) -> DialogueAgentResponse:
        """Pass the exact target and question goal to the dialogue Agent.

        返回 :class:`DialogueAgentResponse`（1~3 条 ``messages`` + 全文 ``reply``），
        由调用方决定怎么消费；本函数不写会话状态。分段的唯一来源仍是 Dialogue Agent。
        """
        previous = history_before_turn(session, user_text)
        request = DialogueAgentRequest(
            conversation_history=previous,
            decision=(DialogueDecision(**decision.model_dump()) if decision else
                      DialogueDecision(target_item=None, question_goal="结束访谈")),
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
                return asyncio.run(self._dialogue_agent.generate_reply(request))
            except (DialogueAgentError, DeepSeekClientError) as exc:
                raise DialogueUnavailable("对话 Agent 生成失败") from exc

        try:
            client = DeepSeekClient(load_deepseek_config())
        except DeepSeekConfigError as exc:
            raise DialogueUnavailable("对话 Agent 缺少有效的 DeepSeek 配置") from exc

        async def generate() -> DialogueAgentResponse:
            try:
                return await DialogueAgent(client).generate_reply(request)
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
