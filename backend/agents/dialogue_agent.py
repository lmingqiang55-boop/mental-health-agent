# -*- coding: utf-8 -*-
"""Dialogue Agent：受控对话生成 + 路由判断。

本模块只有两条链路，都是「结构化输入 -> Prompt -> LLM -> 结构化输出」::

    generate_reply: DialogueAgentRequest -> build_dialogue_user_prompt
                    -> llm_client.generate -> DialogueAgentResponse(reply=...)

    route:          DialogueRouteRequest -> build_dialogue_route_prompt
                    -> llm_client.generate -> DialogueRouteDecision(need_decision=...)

【职责边界】本模块**只**做上面两条链路。因此这里没有、也永远不应该有：
- 话题选择（选哪个话题、换成哪个话题）；
- topic 计数与话题次数上限；
- action 分支判断（如 if action == "共情安慰"）；
- 记忆检索或写入；
- 视觉评分规则、风险评分、疾病诊断；
- 随机选择、重试策略或所谓「Agent 自主规划」。

``route`` 只回答"这一轮要不要新的全局策略"这一个布尔问题，**它不决定换成哪个
话题**——那仍然是决策模型 + 话题次数约束器的职责。``generate_reply`` 的 decision
由上游给出，本 Agent 只负责执行，不修改、不补充、不重新决定。
"""

from __future__ import annotations

from typing import Any
from difflib import SequenceMatcher
import json
import re

from backend.models.dialogue import (
    DialogueAgentRequest,
    DialogueAgentResponse,
    DialogueRouteDecision,
    DialogueRouteRequest,
)
from backend.prompts.dialogue_prompt import (
    DIALOGUE_AGENT_SYSTEM_PROMPT,
    DIALOGUE_ROUTER_SYSTEM_PROMPT,
    build_dialogue_route_prompt,
    build_dialogue_user_prompt,
)

__all__ = ["DialogueAgent", "DialogueAgentError", "parse_route_decision",
           "route_fallback"]

#: 原因码按"它暗示的方向"分成两组，用来识别布尔值与理由自相矛盾的情况。
#: 前一组说"当前话题还能继续"，后一组说"需要新方向"。
ROUTE_CONTINUE_CODES = frozenset({"continue_topic", "clarify"})
ROUTE_DECISION_CODES = frozenset({
    "topic_exhausted", "user_wants_change", "off_topic",
})
#: 路由模块可以给出的原因码；用于识别"模型没有按约定输出"。
ROUTE_REASON_CODES = ROUTE_CONTINUE_CODES | ROUTE_DECISION_CODES
#: 路由异常（输出不合约定或调用失败）时使用的原因码。
ROUTE_ERROR = "route_error"
ROUTE_UNCERTAIN = "route_uncertain"
#: 布尔值与原因码自相矛盾时使用的标记（仍按需要决策处理）。
ROUTE_INCONSISTENT = "route_inconsistent"


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


def route_fallback(reason: str) -> DialogueRouteDecision:
    """路由不可用时的**安全**结论：回到既有的"每轮都决策"流程。"""
    return DialogueRouteDecision(
        need_decision=True, reason_code=ROUTE_ERROR, reason=reason)


def parse_route_decision(content: str) -> DialogueRouteDecision:
    """解析路由模块的输出；任何异常都安全回退为"需要决策"。

    回退方向是刻意选的：多调一次决策模型只是多一次调用，而错误地跳过决策
    会让全局话题推进停摆。因此只有"布尔值明确 + 原因码在约定集合内"才接受
    ``need_decision=False``；模型没按约定输出时一律回退。
    """
    if not isinstance(content, str):
        return route_fallback("路由输出不是文本")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return route_fallback("路由输出不是合法 JSON")
    if not isinstance(payload, dict):
        return route_fallback("路由输出不是 JSON 对象")

    value = payload.get("need_decision")
    if isinstance(value, bool):
        need_decision = value
    elif isinstance(value, str) and value.strip().lower() in ("true", "false"):
        need_decision = value.strip().lower() == "true"
    else:
        return route_fallback("need_decision 缺失或不是布尔值")

    reason_code = str(payload.get("reason_code") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if reason_code not in ROUTE_REASON_CODES:
        if need_decision:
            # "需要"是无条件安全的，原因码不认也照样接受，只把原因码标注清楚。
            return DialogueRouteDecision(
                need_decision=True, reason_code=ROUTE_UNCERTAIN, reason=reason)
        return DialogueRouteDecision(
            need_decision=True, reason_code=ROUTE_UNCERTAIN,
            reason=f"原因码不在约定集合内：{reason_code or '（空）'}")
    if not need_decision and reason_code in ROUTE_DECISION_CODES:
        # 理由本身在说"需要新方向"，只是布尔值写成了 false。以理由为准：
        # 否则会跳过一次必要的话题推进，而这正是本阶段要守住的东西。
        return DialogueRouteDecision(
            need_decision=True, reason_code=reason_code,
            reason=f"理由暗示需要新方向但布尔值为 false，按需要处理：{reason}")
    if need_decision and reason_code in ROUTE_CONTINUE_CODES:
        # 理由说可以继续、布尔值却要求决策：仍然决策（这是安全方向），
        # 但把原因码标成不一致，免得统计与后续 Agent Trace 被这句话误导。
        return DialogueRouteDecision(
            need_decision=True, reason_code=ROUTE_INCONSISTENT,
            reason=f"布尔值与理由不一致（{reason_code}），按需要处理：{reason}")
    return DialogueRouteDecision(
        need_decision=need_decision, reason_code=reason_code, reason=reason)


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
        self.last_route_system_prompt: str | None = None
        self.last_route_user_prompt: str | None = None

    async def route(self, request: DialogueRouteRequest) -> DialogueRouteDecision:
        """判断这一轮是否需要重新调用决策模型。

        与 :meth:`generate_reply` 同属"结构化输入 -> Prompt -> LLM -> 结构化输出"，
        但职责分离：本方法**不生成任何对用户可见的话**，也不选话题。
        模型调用异常会原样抛出，由调用方决定如何回退。
        """
        user_prompt = build_dialogue_route_prompt(request)
        self.last_route_system_prompt = DIALOGUE_ROUTER_SYSTEM_PROMPT
        self.last_route_user_prompt = user_prompt
        content = await self.llm_client.generate(
            system_prompt=DIALOGUE_ROUTER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        return parse_route_decision(content or "")

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
