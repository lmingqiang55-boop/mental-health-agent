"""决策模型选动作，对话 Agent 根据完整上下文生成真正的下一句。"""

import asyncio

from backend.agents.dialogue_agent import DialogueAgent, DialogueAgentError
from backend.core.multimodal_fusion import fuse_turn
from backend.core.risk_engine import assess_risk
from backend.llm.config import DeepSeekConfigError, load_deepseek_config
from backend.llm.deepseek_client import DeepSeekClient, DeepSeekClientError
from backend.llm.prompts import QUESTIONS
from backend.models.dialogue import (
    DialogueAgentRequest, DialogueCurrentUserInput, DialogueDecision,
    DialogueHistoryMessage, DialogueVisual,
)
from backend.models.enums import MessageRole, SessionStage
from backend.models.responses import DialogueResponsePayload
from backend.models.states import RiskResult, SessionState, VisionState, _now
from backend.policy.client import (
    HttpPolicyClient,
    PolicyClientError,
    PolicyDecision,
    get_policy_client,
)
class DialogueUnavailable(RuntimeError):
    """The dialogue generation service cannot produce a usable reply."""


class DialogueManager:
    """决策模型决定下一步动作，危机消息优先走现实支持话术。

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
                     *, use_latest_states: bool = True) -> DialogueResponsePayload:
        latest = session.latest_vision_state if use_latest_states else None
        if latest is not None:
            # Only recent, timezone-aware observations can inform a legacy text turn.
            stamp = latest.timestamp
            age = (_now() - stamp).total_seconds() if stamp.tzinfo is not None else -1
            if not 0 <= age <= 5:
                latest = None
        current_vision = vision_snapshot if vision_snapshot is not None else latest
        fused = fuse_turn(
            user_text,
            current_vision,
            session.latest_audio_state if use_latest_states else None,
        )
        risk = assess_risk(fused)
        session.latest_risk = risk

        # 危机模式：高风险后不再提问评估内容，只给出现实支持指引
        if risk.requires_intervention:
            session.crisis_mode = True
            session.current_stage = SessionStage.CRISIS
            return self._reply(session, "crisis_support", risk)
        if session.crisis_mode:
            return self._reply(session, "crisis_support", risk)

        decision = self._decide(session)
        reply = self._generate_reply(session, user_text, current_vision, decision)
        return DialogueResponsePayload(
            reply=reply,
            next_strategy=decision.actions[-1].value,
            current_stage=session.current_stage.value,
            risk=risk,
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
                        decision: PolicyDecision) -> str:
        """Pass the selected actions to the dialogue Agent; never use canned questions."""
        history = session.conversation_history
        if (history and history[-1].role == MessageRole.USER
                and history[-1].content == user_text):
            history = history[:-1]
        previous = [DialogueHistoryMessage(
            role=message.role.value, content=message.content,
            visual=_dialogue_visual(message.vision_snapshot),
        ) for message in history]
        topics = [action.value for action in decision.actions
                  if action.value != "共情安慰"]
        request = DialogueAgentRequest(
            conversation_history=previous,
            decision=DialogueDecision(
                actions=[action.value for action in decision.actions],
                topic=topics[-1] if topics else None,
            ),
            current_user_input=DialogueCurrentUserInput(
                text=user_text, visual=_dialogue_visual(current_vision),
            ),
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

    def _reply(self, session: SessionState, strategy: str,
               risk: RiskResult) -> DialogueResponsePayload:
        return DialogueResponsePayload(
            reply=QUESTIONS["crisis_support"],
            next_strategy=strategy,
            current_stage=session.current_stage.value,
            risk=risk,
        )


def _dialogue_visual(state: VisionState | None) -> DialogueVisual | None:
    if state is None:
        return None
    values = state.model_dump(exclude={"timestamp"}, exclude_none=True)
    known = {key: values.pop(key, None)
             for key in ("valence", "arousal", "engagement")}
    return DialogueVisual(**known, extra=values)
