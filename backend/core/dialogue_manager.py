"""对话 Agent（A 模块核心）。

负责「问什么」：由已训练的决策模型选择下一步动作，并保留风险识别与危机干预。
不负责「怎么表达」（LLMClient）、不直接调用视觉/音频模型、不负责页面。

流程对应目标图「实时对话闭环（边聊边感知·动态引导）」：
    用户文本 + 句级 VisionState/AudioState
        → 多模态融合
        → 风险评估
        → 决策模型选择下一步动作
        → 本地话术生成回复

六维固定提问状态机（情绪、压力、人际关系、自我认知、学习生活、持续时间）
及其 ``POLICY_PROVIDER=legacy`` 回退路径已删除：本模块没有任何按维度推进、
模糊回答澄清或兜底提问的分支，模型不可用时直接抛出 ``PolicyClientError``。
"""

from backend.core.multimodal_fusion import fuse_turn
from backend.core.risk_engine import assess_risk
from backend.llm.client import get_llm_client
from backend.models.enums import SessionStage
from backend.models.responses import DialogueResponsePayload
from backend.models.states import RiskResult, SessionState, VisionState
from backend.policy.client import (
    HttpPolicyClient,
    PolicyClientError,
    PolicyDecision,
    get_policy_client,
)
from backend.policy.reply import reply_for_decision
from backend.rag.retriever import retrieve


class DialogueManager:
    """决策模型决定下一步动作，危机消息优先走现实支持话术。

    Args:
        policy_client: 决策模型客户端；测试可注入模拟响应，不注入时首次
            使用时按环境变量构造，构造失败会转成 ``PolicyClientError``。
    """

    def __init__(self, policy_client: HttpPolicyClient | None = None) -> None:
        self._llm = get_llm_client()
        self._policy = policy_client

    def process_turn(self, user_text: str, session: SessionState,
                     vision_snapshot: VisionState | None = None,
                     *, use_latest_states: bool = True) -> DialogueResponsePayload:
        fused = fuse_turn(
            user_text,
            vision_snapshot if vision_snapshot is not None else (
                session.latest_vision_state if use_latest_states else None),
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
        return DialogueResponsePayload(
            reply=reply_for_decision(decision),
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

    # -- 回复生成 --------------------------------------------------------

    def _reply(self, session: SessionState, strategy: str,
               risk: RiskResult) -> DialogueResponsePayload:
        context = retrieve(f"{strategy}")
        reply = self._llm.generate_reply(
            "", strategy, context, session.conversation_history)
        return DialogueResponsePayload(
            reply=reply,
            next_strategy=strategy,
            current_stage=session.current_stage.value,
            risk=risk,
        )
