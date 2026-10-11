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
from difflib import SequenceMatcher
import re

from backend.models.dialogue import DialogueAgentRequest, DialogueAgentResponse
from backend.prompts.dialogue_prompt import (
    DIALOGUE_AGENT_SYSTEM_PROMPT,
    build_dialogue_user_prompt,
)

__all__ = ["DialogueAgent", "DialogueAgentError"]


class DialogueAgentError(RuntimeError):
    """Dialogue Agent 生成失败（例如模型返回空内容）。"""


def _main_question(text: str) -> str:
    questions = re.findall(r"([^。！？!?]+)[？?]", text)
    return re.sub(r"[\W_]+", "", questions[-1]) if questions else ""


def _near_repeated_question(reply: str, previous: list[str]) -> bool:
    question = _main_question(reply)
    return len(question) >= 12 and any(
        len(old := _main_question(text)) >= 12
        and SequenceMatcher(None, question, old).ratio() >= 0.88
        for text in previous[-5:])


def _repeated_opening(reply: str, previous: list[str]) -> bool:
    if len(previous) < 2:
        return False
    return any(all(text.strip().startswith(prefix) for text in [*previous[-2:], reply])
               for prefix in ("听你这么说", "听起来", "嗯，", "嗯,"))


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
        recent_replies = [message.content.strip() for message in request.conversation_history
                          if message.role == "assistant"]
        visual_phrases = ("看起来", "看上去", "表情", "神情", "脸上", "显得")
        repeated = reply in previous_replies
        repeated_question = _near_repeated_question(reply, recent_replies)
        mechanical_opening = _repeated_opening(reply, recent_replies)
        closing_question = request.finish_screening and bool(re.search(r"[？?]", reply))
        missed_visual = (request.visual_observation is not None
                         and not any(phrase in reply for phrase in visual_phrases))
        if repeated or repeated_question or mechanical_opening or closing_question or missed_visual:
            requirements = []
            if repeated:
                requirements.append(
                    "上一版回复与历史中已说过的话完全相同。请针对用户刚才的新信息换一种具体追问。")
            if repeated_question:
                requirements.append("上一版的主要问题与近期已问的问题高度相似。请使用用户已经给出的答案，补问尚缺的信息。")
            if mechanical_opening:
                requirements.append("近期已连续使用同一个共情开头。请直接推进，省略套话和对上一句的复述。")
            if closing_question:
                requirements.append("这轮已经收尾，请删掉所有问句，不再邀请继续回答，只提示生成结果。")
            if missed_visual:
                requirements.append(
                    "上一版没有自然提及本轮允许的外观线索。请把它融入完整句子，"
                    "例如用‘你看起来……’承接当前话题，不要在句首机械拼接固定短语。")
            retry_prompt = (
                user_prompt + "\n\n【重写要求】" + "".join(requirements)
                + "保持上游 decision 不变，不要重复历史中的助手回复。"
            )
            self.last_user_prompt = retry_prompt
            reply = (await self.llm_client.generate(
                system_prompt=DIALOGUE_AGENT_SYSTEM_PROMPT,
                user_prompt=retry_prompt,
            ) or "").strip()
            if not reply or reply in previous_replies:
                raise DialogueAgentError("Dialogue Agent repeated an earlier reply.")
            if _near_repeated_question(reply, recent_replies):
                raise DialogueAgentError("Dialogue Agent repeated an earlier question.")
            if request.finish_screening and re.search(r"[？?]", reply):
                raise DialogueAgentError("Dialogue Agent asked a question after closing.")

        return DialogueAgentResponse(reply=reply)
