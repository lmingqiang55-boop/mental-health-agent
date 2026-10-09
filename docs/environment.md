# 环境配置与验证

团队使用 Windows x64 + NVIDIA GPU。Miniforge 和 Anaconda 均可创建同一套项目环境。
首次安装与日常启动见 [README](../README.md#本地运行)。

## 统一环境说明

- Python 3.11.16、pip 26.2.1，使用 `conda-forge` 软件源。
- PyTorch 和 torchaudio 均为 2.8.0+cu128，显卡驱动需支持 CUDA 12.8。
- PyTorch wheel 包含 CUDA 运行库，无需额外安装 CUDA Toolkit。
- 前端推荐 Node.js 22.14.0、npm 10.9.2，通过 `package-lock.json` 安装依赖。

`environment.yml` 引用 `requirements.txt`，一次安装后端、语音、视觉及基础测试包。
Python 包使用 PyPI 和官方 PyTorch CUDA 12.8 wheel 源。直接依赖固定版本，
间接依赖仍由 pip 解析；这不是完整锁文件，不能保证所有间接依赖每次安装都完全一致。
项目包应安装在专用环境中。

## 更新环境

已有同名 Conda 环境时，在项目根目录执行：

```powershell
conda env update -n mental-health-agent -f environment.yml
conda activate mental-health-agent
```

更新会调整 Python、pip 和直接依赖版本；其他项目的包应使用其他环境。
前端锁文件更新后执行：

```powershell
npm --prefix frontend ci
```

## 检查环境

遇到安装或启动问题时，在激活的项目环境中检查：

```powershell
python --version
python -m pip check
python -c "import torch, torchaudio; print(torch.__version__, torchaudio.__version__); print('CUDA:', torch.version.cuda, 'available:', torch.cuda.is_available())"
nvidia-smi
```

Python 应为 3.11.16，torch 和 torchaudio 应为 2.8.0+cu128，
CUDA 应为 12.8 且 `available: True`。若为 False，检查当前 Python 环境和显卡驱动。
Windows 下可在 Miniforge/Anaconda Prompt 中运行 Conda 命令。

## 运行配置

首次运行前将 `.env.example` 复制为 `.env`，已有配置则保留。
在 PowerShell 中可用以下命令避免覆盖原文件：

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

| 配置 | 作用 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 对话 Agent、综合评估和治愈 Agent 共用的真实密钥 |
| `POLICY_API_BASE_URL` | 本机 Ollama 地址，默认 `http://127.0.0.1:11434`；只接受回环地址 |
| `POLICY_API_MODEL` | 本机导入的训练模型，默认 `policy-qwen3-8b:latest` |
| `POLICY_API_KEY` | 本机 Ollama 无须密钥，留空 |
| `ASR_PROVIDER=sensevoice` | 启用真实语音转写 |
| `ASR_DEVICE=cuda:0` | 使用 NVIDIA GPU 进行语音推理 |
| `VISION_PROVIDER=emotiefflib` | 启用真实表情分析 |
| `DASHSCOPE_API_KEY` | 阿里云百炼语音合成密钥；只在后端使用 |
| `DASHSCOPE_WORKSPACE_ID` | 华北2（北京）业务空间 ID，例如 `ws-...` |
| `TTS_MODEL` / `TTS_VOICE` | 默认 `cosyvoice-v3-flash` / `longyingtao_v3` |

`.env.example` 保留 `ASR_PROVIDER=disabled`、`ASR_DEVICE=cpu` 和
`VISION_PROVIDER=mock` 的默认值；复制后需要按实际用途配置。
其余参数及含义见 `.env.example`，真实密钥只保存到本地 `.env`。

每位队友从 QQ 接收训练模型 ZIP，首次执行
`python scripts/start_dev.py --model-package "ZIP路径" --skip-install`。
脚本校验模型 SHA-256、导入本机 Ollama，启动后端时自动使用本机地址和模型名；
后续只需运行 `python scripts/start_dev.py --skip-install`。
找不到训练模型时启动失败，不会改用关键词占位服务。
对话 Agent 也需要 `DEEPSEEK_API_KEY`；缺少密钥或生成服务不可用时，
`POST /api/chat` 返回 `503 DIALOGUE_UNAVAILABLE`，不会改用固定话术。
详见 [队友本地运行指南](队友本地运行指南.md)。

综合评估还使用 `DEEPSEEK_API_STYLE`、`DEEPSEEK_MAX_OUTPUT_TOKENS`、
`DEEPSEEK_TIMEOUT_SECONDS` 等配置。缺少密钥或评估服务不可用时，
评估接口返回 `503 EVALUATION_UNAVAILABLE`。

首次启用真实语音与视觉需要联网下载模型并预留缓存空间。
`GET /api/audio/status` 的 `state=ready` 表示语音模型可以接收请求；
`GET /api/tts/status` 的 `state=ready` 表示语音播报已配置；
`/api/health` 只表示 Web 服务可用。使用 `--reload` 时，重载也会重新加载模型。

可选 faster-whisper 对照工具的安装与运行见
[语音识别说明](speech_recognition.md#验证方法与来源)。

## 对话数据流验收（MVB）

在已激活的项目环境中运行：

```powershell
python -m pytest -q tests/test_conversation_data_flow.py
```

该测试仅在**两个外部模型接口**返回可控响应，项目内部仍实际执行：创建会话 → 接收视觉状态和逐句对齐快照 → 调用策略客户端 → 保存用户与助手消息 → 构造评估输入 → 评估 Agent 解析 11 项并计算五维和关注指数 → 保存评估 → 按结果 ID 和学生历史查询。另一路测试验证上游直接提交完整 `dialogue_history` 与 `vision_summary` 时，这两层视觉数据进入评估请求。

这些测试没有连接真实训练决策模型或 DeepSeek，因此通过不代表外部模型可用。新增对接回归测试见 `tests/test_vision_alignment.py`；前端媒体生命周期与上传协议测试使用 `cd frontend; npm test`。实际设备、光照与真人发音仍需验收。
