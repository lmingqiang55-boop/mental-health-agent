# -*- coding: utf-8 -*-
"""Import the QQ-delivered model ZIP once, then start the local backend.

First run: python scripts/start_dev.py --model-package path/to/model.zip
Later runs: python scripts/start_dev.py

The trained policy model must be installed in local Ollama. There is no
remote tunnel or automatic keyword-rule fallback.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local_policy import (  # noqa: E402
    MODEL_ID, OLLAMA_URL, LocalPolicyError, ensure_ollama_running,
    import_model_package, require_local_model,
)

BACKEND_PORT = 8000
PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"

# 只有语音识别(funasr/torch)、摄像头情绪(emotiefflib/opencv)才需要的重包。
# 实测：不装这些，后端照样正常启动，ASR 只降级为 unavailable，
# 对话与决策链路完全不受影响。所以 --core-only 时把它们摘掉。
HEAVY_PACKAGES = {
    "torch", "torchaudio", "torchvision", "funasr", "modelscope",
    "av", "emotiefflib", "opencv-python", "sentencepiece",
}


def log(message: str) -> None:
    print(f"[start] {message}", flush=True)


def alive(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is None


def http_json(url: str, timeout: float = 3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_http(url: str, seconds: float = 45.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if http_json(url, timeout=1.5) is not None:
            return True
        time.sleep(0.5)
    return False


def ensure_env() -> None:
    if (ROOT / ".env").exists():
        return
    example = ROOT / ".env.example"
    if example.exists():
        shutil.copyfile(example, ROOT / ".env")
        log("已从 .env.example 生成 .env")


def core_requirement_lines() -> list[str]:
    """从 requirements.txt 里摘掉重包，只留跑对话链路需要的。"""
    lines: list[str] = []
    for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        name = re.split(r"[=<>!\[;]", line, 1)[0].strip().lower()
        if name in HEAVY_PACKAGES:
            continue
        lines.append(line)
    return lines


def ensure_deps(skip: bool, core_only: bool = False) -> None:
    missing = []
    for module in ("fastapi", "uvicorn", "pydantic", "httpx", "dotenv", "jieba", "rank_bm25"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if not missing:
        return
    if skip:
        sys.exit(f"[start] 缺少依赖 {missing}，请先执行 pip install -r requirements.txt")

    if core_only:
        lines = core_requirement_lines()
        log(f"缺少依赖 {missing}，只装对话链路需要的 {len(lines)} 个包"
            f"（跳过 torch/funasr/opencv 等）...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                               *lines, "-i", PIP_INDEX])
    else:
        log(f"缺少依赖 {missing}，按项目 requirements.txt 安装。")
        log("  团队的 baseline 含 CUDA 版 torch / funasr，首次可能要几十分钟、数 GB。")
        log("  只想跑对话与决策链路的话，加 --core-only 可以跳过这些重包。")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                               "-r", str(ROOT / "requirements.txt"), "-i", PIP_INDEX])
    log("依赖安装完成")


def start_backend(model: str, port: int, children: list) -> subprocess.Popen:
    env = os.environ.copy()
    # An existing .env may still contain the old tunnel port; local Ollama wins.
    env["POLICY_API_BASE_URL"] = OLLAMA_URL
    env["POLICY_API_MODEL"] = model
    env["POLICY_API_TIMEOUT"] = "60"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env,
    )
    children.append(proc)
    return proc


def shutdown(children: list) -> None:
    for child in children:
        if alive(child):
            child.terminate()
    deadline = time.time() + 8
    for child in children:
        while alive(child) and time.time() < deadline:
            time.sleep(0.2)
        if alive(child):
            child.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="导入本机决策模型并启动后端")
    parser.add_argument("--model-package", type=Path, metavar="ZIP",
                        help="首次运行时传入从 QQ 收到的队友部署 ZIP")
    # Previous local-only instructions used this flag; keep it harmless.
    parser.add_argument("--policy-source", choices=["local"], help=argparse.SUPPRESS)
    parser.add_argument("--backend-port", type=int, default=BACKEND_PORT,
                        help="后端端口，默认 8000")
    parser.add_argument("--skip-install", action="store_true", help="缺依赖时不自动安装")
    parser.add_argument("--core-only", action="store_true",
                        help="装依赖时跳过 torch/funasr/opencv 等重包（只跑对话与决策链路）")
    args = parser.parse_args()

    children: list = []
    try:
        ensure_env()
        ensure_deps(args.skip_install, args.core_only)
        ensure_ollama_running(children)
        if args.model_package is not None:
            import_model_package(args.model_package)
        require_local_model()
        proc = start_backend(MODEL_ID, args.backend_port, children)

        if not wait_http(f"http://127.0.0.1:{args.backend_port}/api/health"):
            shutdown(children)
            sys.exit("[start] 后端启动失败，请看上面的日志")

        print("\n" + "=" * 68)
        print("  已就绪")
        print(f"  决策源    本机 Ollama · {OLLAMA_URL}")
        print(f"  模型名    {MODEL_ID}")
        print(f"  后端      http://127.0.0.1:{args.backend_port}")
        print(f"  API 文档  http://127.0.0.1:{args.backend_port}/docs")
        print("  前端      cd frontend; npm run dev   →  http://localhost:5173")
        print("  停止      Ctrl+C（一次全停）")
        print("=" * 68 + "\n", flush=True)

        while alive(proc):
            time.sleep(1)
        log("后端已退出")
    except KeyboardInterrupt:
        print()
        log("正在停止 ...")
    except LocalPolicyError as exc:
        sys.exit(f"[start] {exc}")
    finally:
        shutdown(children)


if __name__ == "__main__":
    main()
