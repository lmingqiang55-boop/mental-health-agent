# -*- coding: utf-8 -*-
"""Prompt 构建包。

目前仅包含 Dialogue Agent 的 System Prompt 与 User Prompt 构造逻辑。
本包只做文本组装，不包含任何 LLM 调用。
"""

from backend.prompts.dialogue_prompt import (
    DIALOGUE_AGENT_SYSTEM_PROMPT,
    build_dialogue_user_prompt,
)

__all__ = [
    "DIALOGUE_AGENT_SYSTEM_PROMPT",
    "build_dialogue_user_prompt",
]
