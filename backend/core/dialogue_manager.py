"""对话 Agent（A 模块核心）。

负责「问什么」：由已训练的决策模型选择下一步动作，并保留风险识别与危机干预。
普通回复交给 Dialogue Agent 按上下文生成，不直接调用视觉/音频模型，也不负责页面。

流程对应目标图「实时对话闭环（边聊边感知·动态引导）」：
    用户文本 + 句级 VisionState/AudioState
        → 多模态融合
        → 风险评估
        → 决策模型选择下一步动作
        → Dialogue Agent 生成回复

六维固定提问状态机（情绪、压力、人际关系、自我认知、学习生活、持续时间）
及其 ``POLICY_PROVIDER=legacy`` 回退路径已删除：本模块没有任何按维度推进、
模糊回答澄清或兜底提问的分支，模型不可用时直接抛出 ``PolicyClientError``。
"""

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
from backend.models.states import RiskResult, SessionState, VisionState
from backend.policy.client import (
    HttpPolicyClient,
    PolicyClientError,
    PolicyDecision,
    get_policy_client,
)


class DialogueUnavailable(RuntimeError):
    """对话生成服务无法生成可用回复。"""


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

    def process_turn(self, user_text: str,
                     session: SessionState) -> DialogueResponsePayload:
        fused = fuse_turn(
            user_text, session.latest_vision_state, session.latest_audio_state)
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
        reply = self._generate_reply(session, user_text, decision)
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
                        decision: PolicyDecision) -> str:
        """按上游动作和历史生成回复，不使用固定问题。"""
        history = session.conversation_history
        if (history and history[-1].role == MessageRole.USER
                and history[-1].content == user_text):
            history = history[:-1]
        previous = [DialogueHistoryMessage(
            role=message.role.value,
            content=message.content,
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
                text=user_text,
                visual=_dialogue_visual(session.latest_vision_state),
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
