# -*- coding: utf-8 -*-
"""DeepSeek 配置加载。

从项目根目录的 .env（以及进程环境变量）读取 DeepSeek 连接参数，
并转换成 frozen dataclass。

【密钥安全约定】
- 真实 API Key 只存在于本地 .env，绝不写入源码、测试脚本、日志或 git。
- DeepSeekConfig 的 api_key 字段标记为 repr=False，
  因此 print(config) / repr(config) / 异常回溯都不会泄露密钥内容。
- 需要报告配置状态时，请使用 describe_config_status()，它只输出是否存在的布尔值。
- 注意：dataclasses.asdict() / vars() 会绕过 repr=False 拿到真实密钥，
  不要把这两个结果写进日志。

优先级：.env 文件中的键 > 进程环境变量 > 内置默认值。
（只有 .env 里没写的键才会回退到进程环境变量。）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from dotenv import load_dotenv

__all__ = [
    "DeepSeekConfig",
    "DeepSeekConfigError",
    "load_deepseek_config",
    "describe_config_status",
    "PROJECT_ROOT",
    "DEFAULT_ENV_FILE",
]

# backend/llm/config.py -> parents[2] == 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# 默认值（仅当环境变量缺省时生效）
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_TEMPERATURE = 0.5
DEFAULT_MAX_TOKENS = 300
DEFAULT_TIMEOUT = 60.0


class DeepSeekConfigError(RuntimeError):
    """DeepSeek 配置缺失或非法。"""


@dataclass(frozen=True)
class DeepSeekConfig:
    """DeepSeek 连接与生成参数（不可变）。

    api_key 使用 repr=False，避免被 print / repr / 异常回溯意外泄露。
    """

    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = DEFAULT_TIMEOUT


def _clean(value: Optional[object]) -> Optional[str]:
    """把可能为 None 的环境变量值转成去空白的字符串；空串视为未设置。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strip_quotes(value: str) -> str:
    """去掉 .env 值两侧成对的引号（"x" 或 'x'）。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_env_file(path: Path) -> Dict[str, str]:
    """解析 .env 文件为 {键: 值}。

    只做最朴素的解析：忽略空行与 # 注释行，支持 KEY=VALUE、
    KEY="VALUE"、KEY='VALUE'，并允许值为空。
    不使用 os.environ 作为中转，保证「文件里的值」是确定可测的。
    """
    values: Dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeepSeekConfigError(
            f"Failed to read .env file: {type(exc).__name__}"
        ) from exc

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.lower().startswith("export "):
            key = key[len("export "):].strip()
        if not key:
            continue
        values[key] = _strip_quotes(value.strip())
    return values


def load_deepseek_config(
    env_file: Union[str, Path, None, bool] = None,
    use_process_env: bool = True,
) -> DeepSeekConfig:
    """加载 DeepSeek 配置。

    Args:
        env_file: .env 文件路径。
            - None（默认）：使用项目根目录的 .env；文件不存在时不视为错误，
              由 api_key 必填校验给出清晰提示。
            - False：完全不读取 .env，只用进程环境变量。
            - 其他路径：读取指定的 .env（测试用临时文件）；路径不存在则报错。
        use_process_env: 是否允许在 .env 缺失某个键时回退到进程环境变量。
            测试中设为 False 可保证结果只由 env_file 决定。

    Returns:
        校验并类型转换后的 DeepSeekConfig。

    Raises:
        DeepSeekConfigError: 缺少 DEEPSEEK_API_KEY，或数值型环境变量无法转换。
    """
    file_values: Dict[str, str] = {}

    if env_file is not False:
        target = DEFAULT_ENV_FILE if env_file is None else Path(env_file)
        if not target.is_file():
            if env_file is not None:
                raise DeepSeekConfigError(f".env file not found: {target}")
        else:
            # 仍调用 load_dotenv 以遵循项目的 .env 加载约定
            # （副作用：把这些键写入 os.environ，供第三方库读取）。
            load_dotenv(dotenv_path=target, override=False)
            file_values = parse_env_file(target)

    def sourced(key: str) -> Optional[str]:
        """按来源取值：.env 文件优先，其次进程环境变量。"""
        if key in file_values:
            return _clean(file_values[key])
        if use_process_env:
            return _clean(os.environ.get(key))
        return None

    api_key = sourced("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekConfigError(
            "DEEPSEEK_API_KEY is missing. "
            "Put it in the project-root .env file (see .env.example); "
            "it must never be hard-coded in source code."
        )

    return DeepSeekConfig(
        api_key=api_key,
        base_url=sourced("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL,
        model=sourced("DEEPSEEK_MODEL") or DEFAULT_MODEL,
        temperature=_parse_float(
            "DEEPSEEK_TEMPERATURE", sourced("DEEPSEEK_TEMPERATURE"), DEFAULT_TEMPERATURE
        ),
        max_tokens=_parse_int(
            "DEEPSEEK_MAX_TOKENS", sourced("DEEPSEEK_MAX_TOKENS"), DEFAULT_MAX_TOKENS
        ),
        timeout=_parse_float("DEEPSEEK_TIMEOUT", sourced("DEEPSEEK_TIMEOUT"), DEFAULT_TIMEOUT),
    )


def _parse_float(name: str, raw: Optional[str], default: float) -> float:
    """把环境变量解析为 float，失败时抛出清晰的配置错误。"""
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise DeepSeekConfigError(f"{name} must be a number, got {raw!r}.") from exc


def _parse_int(name: str, raw: Optional[str], default: int) -> int:
    """把环境变量解析为 int，失败时抛出清晰的配置错误。"""
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise DeepSeekConfigError(f"{name} must be an integer, got {raw!r}.") from exc


def describe_config_status(config: Optional[DeepSeekConfig] = None) -> str:
    """生成可安全打印的配置状态摘要（绝不包含 API Key 内容）。

    输出示例::

        DeepSeek config loaded successfully
        model=deepseek-flash
        base_url=https://api.deepseek.com
        api_key_present=True
    """
    if config is None:
        return "DeepSeek config not loaded"

    lines: List[str] = [
        "DeepSeek config loaded successfully",
        f"model={config.model}",
        f"base_url={config.base_url}",
        f"api_key_present={bool(config.api_key)}",
        f"temperature={config.temperature}",
        f"max_tokens={config.max_tokens}",
        f"timeout={config.timeout}",
    ]
    return "\n".join(lines)
