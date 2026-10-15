# -*- coding: utf-8 -*-
"""艺术表达「读画」：把画面的客观特征交给大模型，写一段陪伴式解读。

边界（本模块只做一件事）：
- 输入画面的客观特征（颜色 / 涂满程度 / 对称方式 / 心情 / 题面 / 标题）；
- 输出 1~2 句温柔、非诊断的中文回应。

不做心理诊断、不下结论、不参与风险判定。后端不可用时抛 ArtReflectUnavailable，
由 API 层转成 503，前端静默回退到本地回看文案。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Dict

from backend.llm.config import load_deepseek_config
from backend.llm.deepseek_client import DeepSeekClient

__all__ = ["ArtReflectUnavailable", "reflect_artwork"]

# 大模型越界用词：命中即视为不可用，前端保留本地中性文案。
BANNED_WORDS = (
    "抑郁", "焦虑症", "症状", "倾向", "诊断", "患病", "病症", "心理疾病", "测试结果",
)

SYSTEM_PROMPT = """你是「心晴」里陪学生画画的小助手。学生刚画完一幅涂鸦，请根据这幅画的客观特征，写一两句温柔的回应。

必须遵守：
- 只做陪伴式的描述与陪伴，不诊断、不下结论、不评估任何心理疾病。
- 严禁出现「抑郁」「焦虑」「症状」「倾向」「诊断」等词。
- 不给建议、不说教、不命令学生做任何事。
- 语言像朋友，顺着画面本身说（颜色、留白、重复的线条），克制、简短。
- 1~2 句，不超过 60 字，不要逐条罗列特征。
- 只用中文，直接给回应本身，不要引号、不要前后缀。"""


class ArtReflectUnavailable(RuntimeError):
    """读画服务不可用；消息不含 prompt、画面内容或任何密钥。"""


async def reflect_artwork(features: Dict[str, object]) -> str:
    """根据画面特征调用大模型，返回一段陪伴式解读。

    Raises:
        ArtReflectUnavailable: 未配置密钥、请求失败、返回为空或出现越界用词。
    """
    try:
        config = replace(load_deepseek_config(), max_tokens=200, timeout=20.0, temperature=0.8)
        client = DeepSeekClient(config)
        client.client.max_retries = 0
        try:
            async with asyncio.timeout(25):
                text = await client.generate(SYSTEM_PROMPT, f"画面信息：{json.dumps(features, ensure_ascii=False)}")
        finally:
            await client.client.close()
    except Exception as exc:
        # 只带异常类型名，绝不拼接密钥或响应正文。
        raise ArtReflectUnavailable(type(exc).__name__) from None

    reply = text.strip().strip('“”"\'')
    if not reply or any(word in reply for word in BANNED_WORDS):
        raise ArtReflectUnavailable("unsafe_or_empty")
    return reply[:120]
