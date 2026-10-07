# -*- coding: utf-8 -*-
"""一条命令把整套系统跑起来（队友端）。

    python scripts/start_dev.py
    python scripts/start_dev.py --team 10.254.253.222:11435

它会自动完成这些事：

    1. 没有 .env 就从 .env.example 复制一份
    2. 缺依赖就装（--skip-install 跳过；--core-only 只装对话链路需要的，
       跳过 CUDA torch / funasr / opencv 这些几 GB 的重包）
    3. 自动挑决策源，优先级：
           已有人在 8001  →  队长的模型（--team / 局域网自动发现）
           →  本机 Ollama 真模型  →  内置占位服务
    4. 把选中的源统一接到 127.0.0.1:8001，并自动填对模型名
       —— 所以你的 .env 是什么内容都无所谓，不用改
    5. 启动后端 http://127.0.0.1:8000

**队友全程不下载模型。** 想用真模型就连队长的（上面第 3 步自动发现）；
连不上就退回内置占位服务，一样能跑通整条链路。

Ctrl+C 一次停掉所有子进程。
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from policy_tunnel import DISCOVER_PORT, discover, split_host_port  # noqa: E402

POLICY_PORT = 8001
BACKEND_PORT = 8000
OLLAMA_PORT = 11434
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


def port_open(spec: str, timeout: float = 2.0) -> bool:
    try:
        host, port = split_host_port(spec)
    except ValueError:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def http_json(url: str, timeout: float = 3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_port(spec: str, seconds: float = 25.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(spec, timeout=1.0):
            return True
        time.sleep(0.3)
    return False


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
    for module in ("fastapi", "uvicorn", "pydantic", "httpx", "dotenv"):
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


def pick_source(args: argparse.Namespace) -> tuple[str, str | None]:
    """决定用哪个决策源，返回 (kind, remote)。"""
    want = args.policy_source

    # 1) 8001 上已经有可用服务（比如上次没退干净）——直接复用
    if want == "auto" and http_json(f"http://127.0.0.1:{POLICY_PORT}/v1/models") is not None:
        log(f"127.0.0.1:{POLICY_PORT} 上已有决策服务，直接复用")
        return "reuse", None

    # 2) 队长的模型（没给地址就自动在局域网里找）
    if want in ("auto", "team"):
        team = args.team
        if not team and want == "auto" and not args.no_discover:
            log("正在局域网里寻找队友共享的模型 ...")
            team = discover(port=args.discover_port)
            log(f"找到了：{team}" if team else "没找到共享的模型")
        if team:
            if port_open(team):
                return "team", team
            if want == "team":
                sys.exit(f"[start] 队长模型不可达：{team}")
            log(f"队长模型不可达（{team}），继续往下找")
        elif want == "team":
            sys.exit("[start] --policy-source team 需要同时提供 --team HOST:PORT")

    # 3) 本机 Ollama
    if want in ("auto", "local"):
        if http_json(f"http://127.0.0.1:{OLLAMA_PORT}/api/tags") is not None:
            return "local", f"127.0.0.1:{OLLAMA_PORT}"
        if want == "local":
            sys.exit(f"[start] 本机没有模型服务（127.0.0.1:{OLLAMA_PORT}）")
        log("本机没有模型服务，继续往下找")

    # 4) 内置占位服务
    return "stub", None


def start_policy(kind: str, remote: str | None, children: list) -> str:
    """把选中的决策源挂到 127.0.0.1:8001，返回给用户看的说明。"""
    if kind == "reuse":
        return f"复用 127.0.0.1:{POLICY_PORT} 上已有的服务"

    if kind == "stub":
        cmd = [sys.executable, str(ROOT / "scripts" / "dev_policy_stub.py"),
               "--port", str(POLICY_PORT)]
        label = "内置占位服务（关键词规则，不是训练模型）"
    else:
        cmd = [sys.executable, str(ROOT / "scripts" / "policy_tunnel.py"), "borrow",
               "--remote", remote, "--local", str(POLICY_PORT), "--quiet"]
        label = f"真实模型 · {remote}"

    proc = subprocess.Popen(cmd, cwd=str(ROOT))
    children.append(proc)
    if not wait_port(f"127.0.0.1:{POLICY_PORT}"):
        sys.exit("[start] 决策源启动失败，请看上面的输出")
    return label


def detect_model(kind: str) -> str:
    """从服务里读真实模型名。占位服务对名字不敏感。"""
    if kind == "stub":
        return "policy-model"
    data = http_json(f"http://127.0.0.1:{POLICY_PORT}/v1/models")
    ids = [item.get("id", "") for item in (data or {}).get("data", []) if item.get("id")]
    for model_id in ids:
        if "policy" in model_id.lower():
            return model_id
    return ids[0] if ids else "policy-model"


def start_backend(model: str, port: int, children: list) -> subprocess.Popen:
    env = os.environ.copy()
    # 这两行是关键：无论 .env 里写了什么，都以这里为准，队友不用改配置
    env["POLICY_API_BASE_URL"] = f"http://127.0.0.1:{POLICY_PORT}"
    env["POLICY_API_MODEL"] = model
    env.setdefault("POLICY_API_TIMEOUT", "60")
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
    parser = argparse.ArgumentParser(description="一条命令跑起本地开发环境")
    parser.add_argument("--team", metavar="HOST:PORT", default=os.getenv("TEAM_POLICY_RELAY"),
                        help="队长的模型地址；不填会自动在局域网里找。"
                             "IPv6 要加方括号，例如 [2409:890f:4e08:38c1::1]:11435")
    parser.add_argument("--no-discover", action="store_true",
                        help="不做局域网自动发现，只按 --team / 本机模型 / 占位服务 顺序")
    parser.add_argument("--discover-port", type=int, default=DISCOVER_PORT,
                        help=f"自动发现的 UDP 端口，默认 {DISCOVER_PORT}")
    parser.add_argument("--policy-source", choices=["auto", "team", "local", "stub"],
                        default="auto", help="强制指定决策源，默认自动挑")
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

        kind, remote = pick_source(args)
        label = start_policy(kind, remote, children)
        model = detect_model(kind)
        proc = start_backend(model, args.backend_port, children)

        if not wait_http(f"http://127.0.0.1:{args.backend_port}/api/health"):
            shutdown(children)
            sys.exit("[start] 后端启动失败，请看上面的日志")

        print("\n" + "=" * 68)
        print("  已就绪")
        print(f"  决策源    {label}")
        print(f"  模型名    {model}")
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
    finally:
        shutdown(children)


if __name__ == "__main__":
    main()
