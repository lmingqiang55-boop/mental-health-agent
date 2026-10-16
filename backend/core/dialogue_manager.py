"""决策模型选动作，对话 Agent 根据完整上下文生成真正的下一句。

本模块同时服务两条**等价**调用路径，二者共用下面这些模块级函数，
以保证两条路径不会行为漂移：

- :meth:`DialogueManager.process_turn`：顺序执行（``DIALOGUE_ENGINE=legacy``）；
- :mod:`backend.graph`：把同一组步骤拆成 LangGraph 节点（``DIALOGUE_ENGINE=graph``）。
"""

import asyncio
from dataclasses import dataclass

from backend.agents.dialogue_agent import (
    DialogueAgent, DialogueAgentError, route_fallback,
)
from backend.core.screening_flow import (
    MAX_TOPIC_TURNS, MAX_TURNS, MIN_TURNS, completion_reason, limit_topic,
    record_answer,
)
from backend.core.multimodal_consistency import TurnDiscordance
from backend.core.visual_acknowledgment import (
    VisualAcknowledgment, select_visual_checkin, select_visual_observation,
    select_visual_tone,
)
from backend.llm.config import DeepSeekConfigError, load_deepseek_config
from backend.llm.deepseek_client import DeepSeekClient, DeepSeekClientError
from backend.models.dialogue import (
    DialogueAgentRequest, DialogueAgentResponse, DialogueCurrentUserInput,
    DialogueDecision, DialogueHistoryMessage, DialogueRouteDecision,
    DialogueRouteRequest, DialogueVisual, DialogueVisualDiscordance,
)
from backend.models.enums import MessageRole, SessionStage
from backend.models.responses import DialogueResponsePayload, VisualFeedback
from backend.models.states import SessionState, VisionState, _now
from backend.policy.client import (
    DialogueAction,
    HttpPolicyClient,
    PolicyClientError,
    PolicyDecision,
    get_policy_client,
)


class DialogueUnavailable(RuntimeError):
    """The dialogue generation service cannot produce a usable reply."""


class ScreeningFinished(RuntimeError):
    """A closed screening accepts no further ordinary chat turns."""


#: 生成后用来判断回复是否真的把外观线索说了出口。
VISUAL_MENTION_PHRASES = ("看起来", "看上去", "表情", "神情", "脸上", "显得")


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
    """生成之后才敢记账：提到过就进冷却，免得连着几轮盯着表情说。"""
    if channels.acknowledgment is not None:
        session.last_visual_observation_turn = session.turn_count
        channels.feedback.reason = "mentioned" if any(
            phrase in reply for phrase in VISUAL_MENTION_PHRASES
        ) else "generation_omitted"
    elif channels.discordance is not None or channels.tone is not None:
        # 核对与语气同样算"提过一次外观"，要进冷却。
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
        current_vision = resolve_current_vision(
            session, vision_snapshot, use_latest_states)
        ensure_screening_open(session)
        record_answer(session)
        ending = completion_reason(session, user_text)
        if ending is not None:
            return self.finish_screening(
                user_text, session, current_vision, ending)

        decision = limit_topic(session, self.decide(session))
        channels = select_visual_channels(
            session, utterance_id, current_vision, user_text)
        response = self.reply_for_decision(
            session, user_text, current_vision, decision, channels)
        finalize_visual_feedback(session, channels, response.reply)
        return open_payload(
            session, response, decision.actions[-1].value, channels.feedback)

    # -- 供 backend.graph 复用的公开入口 ---------------------------------
    #
    # 图节点必须走这三个方法，而不是 ``_decide`` / ``_generate_reply``，
    # 这样"决策怎么调""回复怎么生成"只有一份实现，两条路径不会漂移。

    def decide(self, session: SessionState) -> PolicyDecision:
        """调用决策模型取得本轮动作。"""
        return self._decide(session)

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
        return response

    def route_turn(self, session: SessionState, user_text: str,
                   current_vision: VisionState | None) -> DialogueRouteDecision:
        """Dialogue 主控：判断本轮是否需要新的全局策略。

        **路由失败不中断这一轮**，一律回退为"需要决策"（即迁移前的既有流程）。
        多调一次决策模型是安全的；因为路由坏掉而停止话题推进不是。
        """
        request = self._route_request(session, user_text, current_vision)
        if self._dialogue_agent is not None:
            try:
                return asyncio.run(self._dialogue_agent.route(request))
            except (DialogueAgentError, DeepSeekClientError) as exc:
                return route_fallback(f"路由调用失败：{type(exc).__name__}")
            except Exception as exc:  # noqa: BLE001 - 路由绝不能成为单点故障
                return route_fallback(f"路由意外失败：{type(exc).__name__}")

        try:
            client = DeepSeekClient(load_deepseek_config())
        except DeepSeekConfigError:
            return route_fallback("缺少有效的 DeepSeek 配置")

        async def decide() -> DialogueRouteDecision:
            try:
                return await DialogueAgent(client).route(request)
            finally:
                # 每个节点自建自关客户端，绝不跨已关闭的事件循环复用。
                await client.client.close()

        try:
            return asyncio.run(decide())
        except (DialogueAgentError, DeepSeekClientError) as exc:
            return route_fallback(f"路由调用失败：{type(exc).__name__}")
        except Exception as exc:  # noqa: BLE001 - 路由绝不能成为单点故障
            return route_fallback(f"路由意外失败：{type(exc).__name__}")

    def reuse_decision(self, session: SessionState) -> PolicyDecision:
        """复用当前仍然有效的全局策略，供跳过决策的轮次生成回复。

        这不是"为了填 Schema 伪造一个决策"，而是把上一条**仍然有效**的决策
        原样还原。调用方（``resolve_topic``）只在 ``should_force_decision``
        判定策略有效时才会走到这里，因此 ``active_actions`` 必然合法且非空。
        """
        stored = session.screening_progress.active_actions
        if not stored:
            raise DialogueUnavailable("跳过决策时没有可复用的全局策略")
        try:
            actions = [DialogueAction(action) for action in stored]
        except ValueError as exc:
            raise DialogueUnavailable("已存全局策略含无效动作，无法复用") from exc
        return PolicyDecision(actions=actions)

    def _route_request(self, session: SessionState, user_text: str,
                       current_vision: VisionState | None) -> DialogueRouteRequest:
        progress = session.screening_progress
        return DialogueRouteRequest(
            conversation_history=history_before_turn(session, user_text),
            current_user_input=DialogueCurrentUserInput(
                text=user_text, visual=_dialogue_visual(current_vision),
            ),
            active_actions=list(progress.active_actions),
            active_topic=progress.active_topic,
            active_topic_turns=progress.topic_turns.get(
                progress.active_topic or "", 0),
            topic_turns=dict(progress.topic_turns),
            topic_limit=MAX_TOPIC_TURNS,
            turn_count=session.turn_count,
            min_turns=MIN_TURNS,
            max_turns=MAX_TURNS,
        )

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
        return self._policy.predict(session.conversation_history)

    def _generate_reply(self, session: SessionState, user_text: str,
                        current_vision: VisionState | None,
                        decision: PolicyDecision | None,
                        visual_ack: VisualAcknowledgment | None,
                        *, closing_reason: str | None = None,
                        visual_discordance: TurnDiscordance | None = None,
                        visual_tone: str | None = None) -> DialogueAgentResponse:
        """Pass the selected actions to the dialogue Agent; never use canned questions.

        返回 :class:`DialogueAgentResponse`（1~3 条 ``messages`` + 全文 ``reply``），
        由调用方决定怎么消费；本函数不写会话状态。分段的唯一来源仍是 Dialogue Agent。
        """
        previous = history_before_turn(session, user_text)
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
