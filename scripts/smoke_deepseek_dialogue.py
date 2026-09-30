# -*- coding: utf-8 -*-
"""真实 DeepSeek API Smoke Test（第 3 步，仅调用一次）。

⚠️ 本脚本会**真实消耗 API 配额**：只调用一次，不循环、不批量、不自动重试。

只打印：模型名、decision 摘要、模型生成的 reply。
绝不打印：API Key、完整环境变量、Authorization Header。

运行：python scripts/smoke_deepseek_dialogue.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.dialogue_agent import DialogueAgent, DialogueAgentError  # noqa: E402
from backend.llm.config import DeepSeekConfigError, load_deepseek_config  # noqa: E402
from backend.llm.deepseek_client import DeepSeekClient, DeepSeekClientError  # noqa: E402
from backend.models.dialogue import DialogueAgentRequest  # noqa: E402


def build_request() -> DialogueAgentRequest:
    """smoke test 用例：睡眠 -> 食欲，含记忆与视觉标签。"""
    return DialogueAgentRequest.model_validate(
        {
            "conversation_history": [
                {"role": "assistant", "content": "最近睡眠怎么样？"},
                {"role": "user", "content": "最近一直睡不好。"},
            ],
            "user_memory": {"facts": ["用户最近正在准备考试"]},
            "decision": {
                "actions": ["共情安慰", "当前话题从睡眠转到食欲"],
                "topic": "食欲",
                "reason": "睡眠话题达到次数限制",
            },
            "current_user_input": {
                "text": "最近每天都睡得很晚，白天也没精神。",
                "visual": {"valence": -0.5, "arousal": 0.3, "engagement": 0.6},
            },
        }
    )


async def main() -> int:
    print("=== DeepSeek Dialogue Agent Smoke Test ===")

    try:
        config = load_deepseek_config()
    except DeepSeekConfigError as exc:
        print("\n[CONFIG ERROR] 未能加载 DeepSeek 配置")
        print(f"{type(exc).__name__}: {exc}")
        return 2

    client = DeepSeekClient(config)
    agent = DialogueAgent(client)
    request = build_request()

    print(f"\nmodel: {config.model}")
    print("\ndecision:")
    print("共情安慰 + 睡眠 -> 食欲")

    # 单次调用。失败即如实报告，不做重试。
    try:
        response = await agent.generate_reply(request)
    except DeepSeekClientError as exc:
        print("\n[API ERROR] 调用失败（未重试）")
        print(f"{type(exc).__name__}: {exc}")
        return 3
    except DialogueAgentError as exc:
        print("\n[AGENT ERROR] 生成失败（未重试）")
        print(f"{type(exc).__name__}: {exc}")
        return 4

    print("\nreply:")
    print(response.reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
