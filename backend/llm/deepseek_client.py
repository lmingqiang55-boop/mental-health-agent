# -*- coding: utf-8 -*-
"""DeepSeek API 客户端。

职责边界（本模块只做三件事）：
1. 把 system / user 两条 prompt 发给 DeepSeek；
2. 取回文本并做空值防御；
3. 把底层异常统一包装成 DeepSeekClientError。

本模块不含任何对话策略、话题选择或决策逻辑。

【密钥安全】任何异常信息都只包含异常**类型名**，绝不拼接 API Key，
也不会打印 HTTP Authorization Header。
"""

from __future__ import annotations

from typing import Any, Dict

from openai import AsyncOpenAI

from backend.llm.config import DeepSeekConfig

__all__ = ["DeepSeekClient", "DeepSeekClientError"]


class DeepSeekClientError(RuntimeError):
    """DeepSeek 调用失败或返回了不可用的内容。"""


def build_thinking_disabled_extra_body() -> Dict[str, Any]:
    """构造「关闭 thinking」的 extra_body。

    DeepSeek 当前部分模型默认开启 thinking。Dialogue Agent 第一版**必须**显式关闭：
    - Dialogue Agent 不负责复杂推理；
    - 聊什么话题已由上游 decision 决定；
    - 这里只需要稳定的自然语言表达；
    - 关闭后 temperature=0.5 的采样风格才可控。
    """
    return {"thinking": {"type": "disabled"}}


class DeepSeekClient:
    """DeepSeek Chat Completions 的异步客户端。

    通过依赖注入暴露给 DialogueAgent：只要对象实现了
    ``async generate(system_prompt, user_prompt) -> str``，
    就可以替换成 Fake/Mock 实现用于离线测试。
    """

    def __init__(self, config: DeepSeekConfig) -> None:
        self.config = config
        # 注意：api_key 只在这里传入 SDK，绝不打印。
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
        )

    def __repr__(self) -> str:
        """安全 repr：不包含 api_key。"""
        return (
            f"{type(self).__name__}(model={self.config.model!r}, "
            f"base_url={self.config.base_url!r}, api_key=***)"
        )

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """调用 DeepSeek 生成一段回复文本。

        Args:
            system_prompt: System Prompt（本项目使用 DIALOGUE_AGENT_SYSTEM_PROMPT）。
            user_prompt: User Prompt（由 build_dialogue_user_prompt 构造）。

        Returns:
            模型回复文本（已 strip，保证非空）。

        Raises:
            DeepSeekClientError: 请求失败、响应结构异常，或回复为空。
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=False,
                # Dialogue Agent 只是受控语言生成，第一版关闭 DeepSeek thinking。
                extra_body=build_thinking_disabled_extra_body(),
            )
        except Exception as exc:
            # 只拼异常类型名，不拼异常正文（正文可能含请求细节）。
            raise DeepSeekClientError(
                f"DeepSeek API request failed: {type(exc).__name__}"
            ) from exc

        return self._extract_content(response)

    @staticmethod
    def _extract_content(response: Any) -> str:
        """从 ChatCompletion 响应中安全提取文本。

        防御四种情况：choices 为空、message 缺失、content 为 None、content 为空白。
        """
        choices = getattr(response, "choices", None)
        if not choices:
            raise DeepSeekClientError("DeepSeek returned no choices.")

        message = getattr(choices[0], "message", None)
        if message is None:
            raise DeepSeekClientError("DeepSeek returned a choice without a message.")

        content = getattr(message, "content", None)
        if content is None:
            raise DeepSeekClientError("DeepSeek returned a message without content.")

        reply = str(content).strip()
        if not reply:
            raise DeepSeekClientError("DeepSeek returned an empty response.")

        return reply
