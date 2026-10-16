# -*- coding: utf-8 -*-
"""Phase 2.5 前置检查：真实模型是否可用（不打印任何密钥）。"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from backend.core.screening_flow import MAX_TURNS, MIN_TURNS, TOPICS  # noqa: E402
from backend.llm.config import DeepSeekConfigError, load_deepseek_config  # noqa: E402
from backend.llm.deepseek_client import DeepSeekClient  # noqa: E402


def check_env() -> None:
    print("=== 环境变量（只报是否存在，不打印取值）===")
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
                 "DEEPSEEK_MAX_TOKENS", "DIALOGUE_ENGINE",
                 "POLICY_API_BASE_URL", "POLICY_MODEL", "SAFETY_DEPLOYMENT_REGION"):
        value = os.getenv(name)
        if value is None:
            print(f"  {name:26} 未设置")
        elif "KEY" in name or "TOKEN" in name:
            print(f"  {name:26} 已设置（长度 {len(value)}）")
        else:
            print(f"  {name:26} {value}")
    print()


def check_ollama() -> bool:
    print("=== Qwen3-8B 决策模型（Ollama）===")
    base = os.getenv("POLICY_API_BASE_URL", "http://127.0.0.1:11434")
    model = os.getenv("POLICY_MODEL", "policy-qwen3-8b:latest")
    try:
        with httpx.Client(base_url=base, timeout=10.0, trust_env=False) as client:
            tags = client.get("/api/tags")
        print(f"  GET /api/tags -> HTTP {tags.status_code}")
        names = [item.get("name") for item in tags.json().get("models", [])]
        print(f"  本地模型：{names}")
        if model not in names:
            print(f"  !! 期望的 {model} 不在列表里")
            return False
    except Exception as exc:  # noqa: BLE001
        print(f"  !! 连接失败：{type(exc).__name__}: {exc}")
        return False
    print("  可用 ✅\n")
    return True


def check_deepseek() -> bool:
    print("=== DeepSeek 对话模型 ===")
    try:
        config = load_deepseek_config()
    except DeepSeekConfigError as exc:
        print(f"  !! 配置无效：{exc}")
        return False
    print(f"  model={config.model}")
    print(f"  base_url={config.base_url}")

    client = DeepSeekClient(config)

    async def ping() -> str:
        try:
            return await client.generate(system_prompt="你只回答一个字。",
                                         user_prompt="回答：好")
        finally:
            await client.client.close()

    started = time.perf_counter()
    try:
        reply = asyncio.run(ping())
    except Exception as exc:  # noqa: BLE001
        print(f"  !! 调用失败：{type(exc).__name__}: {exc}")
        return False
    elapsed = time.perf_counter() - started
    print(f"  真实调用成功，返回 {reply!r}，耗时 {elapsed:.2f}s ✅\n")
    return True


def main() -> int:
    print(f"筛查参数：MIN_TURNS={MIN_TURNS} MAX_TURNS={MAX_TURNS} "
          f"话题数={len(TOPICS)}\n")
    check_env()
    ollama_ok = check_ollama()
    deepseek_ok = check_deepseek()
    print("=== 结论 ===")
    print(f"  决策模型（Qwen3-8B）：{'可用' if ollama_ok else '不可用'}")
    print(f"  对话/路由模型（DeepSeek）：{'可用' if deepseek_ok else '不可用'}")
    return 0 if (ollama_ok and deepseek_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
