# -*- coding: utf-8 -*-
"""Dialogue Agent：受控对话生成。

流程（严格只有这一条链路）::

    DialogueAgentRequest
        -> build_dialogue_user_prompt(request)   （复用第 2 步实现）
        -> llm_client.generate(system, user)     （DeepSeek 或 Fake）
        -> DialogueAgentResponse(reply=...)

【职责边界】本模块**只**做「结构化输入 -> Prompt -> LLM -> reply」。
因此这里没有、也永远不应该有：
- 话题选择 / 话题切换判断 / topic 计数；
- action 分支判断（如 if action == "共情安慰"）；
- 记忆检索或写入；
- 视觉评分规则、风险评分、疾病诊断；
- 随机选择、重试策略或所谓「Agent 自主规划」。

decision 由上游（决策 Agent + 话题次数约束器）给出，本 Agent 只负责执行，
不修改、不补充、不重新决定。
"""

from __future__ import annotations

from typing import Any

from backend.models.dialogue import DialogueAgentRequest, DialogueAgentResponse
from backend.prompts.dialogue_prompt import (
    DIALOGUE_AGENT_SYSTEM_PROMPT,
    build_dialogue_user_prompt,
)

__all__ = ["DialogueAgent", "DialogueAgentError"]


class DialogueAgentError(RuntimeError):
    """Dialogue Agent 生成失败（例如模型返回空内容）。"""


class DialogueAgent:
    """根据上游 decision 生成下一句对用户说的话。

    Args:
        llm_client: 任何实现 ``async generate(system_prompt, user_prompt) -> str``
            的对象。生产环境传 DeepSeekClient，测试传 FakeDeepSeekClient。
            使用依赖注入是为了让离线测试完全不碰网络。

    Attributes:
        last_system_prompt: 最近一次实际发送的 System Prompt（便于调试/测试断言）。
        last_user_prompt: 最近一次实际发送的 User Prompt（便于调试/测试断言）。
    """

    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client
        self.last_system_prompt: str | None = None
        self.last_user_prompt: str | None = None

    async def generate_reply(
        self,
        request: DialogueAgentRequest,
    ) -> DialogueAgentResponse:
        """生成下一句回复。

        Args:
            request: 完整结构化输入（history / memory / decision / current_input）。

        Returns:
            DialogueAgentResponse，其 reply 已 strip 且保证非空。

        Raises:
            DialogueAgentError: 模型返回空白内容。
        """
        user_prompt = build_dialogue_user_prompt(request)

        self.last_system_prompt = DIALOGUE_AGENT_SYSTEM_PROMPT
        self.last_user_prompt = user_prompt

        reply = await self.llm_client.generate(
            system_prompt=DIALOGUE_AGENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        reply = (reply or "").strip()

        if not reply:
            raise DialogueAgentError("Dialogue Agent generated an empty reply.")

        previous_replies = {message.content.strip()
                            for message in request.conversation_history
                            if message.role == "assistant"}
        if reply in previous_replies:
            retry_prompt = (
                user_prompt + "\n\n【重写要求】上一版回复与历史中已说过的话完全相同。"
                "请严格保持上游 decision 不变，针对用户刚才的新信息换一种具体追问，"
                "不要重复历史中的任何一句助手回复。"
            )
            self.last_user_prompt = retry_prompt
            reply = (await self.llm_client.generate(
                system_prompt=DIALOGUE_AGENT_SYSTEM_PROMPT,
                user_prompt=retry_prompt,
            ) or "").strip()
            if not reply or reply in previous_replies:
                raise DialogueAgentError("Dialogue Agent repeated an earlier reply.")

        return DialogueAgentResponse(reply=reply)
