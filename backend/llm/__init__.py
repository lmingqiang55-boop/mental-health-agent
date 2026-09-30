"""Reply generation boundary.

本包同时包含两条并存的实现：
- ``client.py``：远程既有的同步 ``LLMClient`` 抽象 + Mock 降级（LLM_PROVIDER 体系）；
- ``deepseek_client.py`` / ``config.py``：Dialogue Agent 使用的异步 DeepSeek 客户端。
"""

from backend.llm.config import (
    DeepSeekConfig,
    DeepSeekConfigError,
    load_deepseek_config,
)
from backend.llm.deepseek_client import DeepSeekClient, DeepSeekClientError

__all__ = [
    "DeepSeekConfig",
    "DeepSeekConfigError",
    "load_deepseek_config",
    "DeepSeekClient",
    "DeepSeekClientError",
]
