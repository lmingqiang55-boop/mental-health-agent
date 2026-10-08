"""Install and check the team's trained decision model in local Ollama."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OLLAMA_URL = "http://127.0.0.1:11434"
MODEL_NAME = "policy-qwen3-8b"
MODEL_ID = f"{MODEL_NAME}:latest"
GGUF_NAME = "policy-qwen3-8b-Q4_K_M.gguf"
GGUF_SIZE = 5_027_780_096
GGUF_SHA256 = "b5898652f3978d777137951f4a6384c9f8a7b73e832dbab59b5c2729696fbbd2"


class LocalPolicyError(RuntimeError):
    """The local trained model cannot be installed or used."""


def ollama_executable() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def installed_models() -> set[str] | None:
    """Return None when the local Ollama server is unavailable."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as response:
            data = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return None
    return {item.get("name", "") for item in data.get("models", [])
            if isinstance(item, dict)}


def ensure_ollama_running(children: list[subprocess.Popen]) -> None:
    if installed_models() is not None:
        return
    executable = ollama_executable()
    if executable is None:
        raise LocalPolicyError("未找到 Ollama。请先从 https://ollama.com/download/windows 安装，重开终端后重试。")
    print("[start] 正在启动本机 Ollama ...", flush=True)
    process = subprocess.Popen([executable, "serve"], cwd=str(ROOT))
    children.append(process)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if installed_models() is not None:
            return
        if process.poll() is not None:
            break
        time.sleep(0.5)
    raise LocalPolicyError("本机 Ollama 未能启动，请打开 Ollama 并检查 127.0.0.1:11434。")


def extract_verified_model(
    package: Path,
    destination: Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> Path:
    """Extract only the expected GGUF; reject truncated or replaced model files."""
    expected_size = GGUF_SIZE if expected_size is None else expected_size
    expected_sha256 = GGUF_SHA256 if expected_sha256 is None else expected_sha256
    target = destination / GGUF_NAME
    digest = hashlib.sha256()
    total = 0
    try:
        with ZipFile(package) as archive:
            info = archive.getinfo(GGUF_NAME)
            if info.file_size != expected_size:
                raise LocalPolicyError("模型文件大小不符，请重新接收队友部署 ZIP。")
            with archive.open(info) as source, target.open("wb") as output:
                while block := source.read(8 * 1024 * 1024):
                    total += len(block)
                    digest.update(block)
                    output.write(block)
    except (BadZipFile, KeyError, OSError) as exc:
        raise LocalPolicyError("无法读取部署 ZIP 中的 GGUF 模型文件。") from exc
    if total != expected_size or digest.hexdigest() != expected_sha256:
        target.unlink(missing_ok=True)
        raise LocalPolicyError("模型 SHA-256 不匹配，请重新接收队友部署 ZIP。")
    return target


def import_model_package(package: Path) -> None:
    """Verify the QQ-delivered ZIP and import it using the repository's template."""
    package = package.expanduser().resolve()
    if not package.is_file():
        raise LocalPolicyError(f"找不到模型部署 ZIP：{package}")
    executable = ollama_executable()
    if executable is None:
        raise LocalPolicyError("未找到 Ollama 命令。请先安装 Ollama，重开终端后重试。")
    print("[start] 正在校验并导入决策模型（约 5 GB）...", flush=True)
    with tempfile.TemporaryDirectory(prefix="policy-model-", dir=package.parent) as temp:
        directory = Path(temp)
        extract_verified_model(package, directory)
        shutil.copyfile(ROOT / "scripts" / "Modelfile-policy", directory / "Modelfile-policy")
        try:
            subprocess.run(
                [executable, "create", MODEL_NAME, "-f", "Modelfile-policy"],
                cwd=directory, check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise LocalPolicyError("Ollama 导入模型失败，请查看上面的错误。") from exc
    if MODEL_ID not in (installed_models() or set()):
        raise LocalPolicyError(f"导入后未发现 {MODEL_ID}，请检查 Ollama 模型库。")
    verify_model_inference()
    print(f"[start] 已导入并验证 {MODEL_ID}", flush=True)


def verify_model_inference() -> None:
    """Exercise the real project client once after import, not just Ollama's model list."""
    from backend.models.enums import MessageRole
    from backend.models.states import Message
    from backend.policy.client import HttpPolicyClient, PolicyClientError
    from evaluation_agent.opening import OPENING_QUESTION

    history = [
        Message(role=MessageRole.ASSISTANT, content=OPENING_QUESTION),
        Message(role=MessageRole.USER, content="我最近睡不好。"),
    ]
    try:
        decision = HttpPolicyClient(base_url=OLLAMA_URL, model=MODEL_ID, timeout=60).predict(history)
    except (PolicyClientError, ValueError) as exc:
        raise LocalPolicyError("模型已导入，但实际决策调用失败，请查看 Ollama 状态。") from exc
    print(f"[start] 决策模型冒烟验证通过：{', '.join(action.value for action in decision.actions)}", flush=True)


def require_local_model() -> None:
    models = installed_models()
    if models is None:
        raise LocalPolicyError("本机 Ollama 不可用，请启动 Ollama 后重试。")
    if MODEL_ID not in models:
        raise LocalPolicyError(
            f"本机没有 {MODEL_ID}。首次运行请加 --model-package <从 QQ 收到的 ZIP 路径>。"
        )
