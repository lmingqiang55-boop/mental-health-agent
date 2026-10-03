# 多模态心理状态筛查 Agent

系统由对话决策、队员 B 的语音与视觉处理、心理状态评估和展示页面组成。对话下一步动作由已训练的决策模型选择；最终评估由 `evaluation_agent/` 计算五维心理状态画像、关注指数和关注等级，再由后端生成总体说明、关键发现、趋势说明与建议。危机风险识别独立运行。

> **MVB 演示只使用虚构数据。** 对话到评估的数据流可按下文的离线集成测试验收。面向真实中小学生开放所需的权限、同意、危机响应和效度验证另见 [真实用户上线前审查](docs/prelaunch_audit_2026-10-01.md)。评估提示词已同步至 `PROMPT_VERSION=1.2`。

**语音与摄像头对接已接入页面（2026-10-03）。** 当前支持文字输入、按住/松开完整录音、语音与录音区间视觉聚合、聊天去重、失败重试和逐句视觉会话汇总。摄像头开启/关闭及权限等待取消已处理；最终评估保留原录音信息和冻结的视觉快照。具体行为与验收边界见 [摄像头与录音对接](docs/vision_alignment.md)。

保留 FunASR + SenseVoiceSmall 和 EmotiEffLib，统一环境默认安装语音与视觉依赖；运行时通过 `.env` 启用真实模型。当前没有自动 VAD、流式 ASR、眼动或微表情模型。历史语音识别质量实测见 [2026-10-02 验证记录](docs/speech_validation_2026-10-02.md)。页面联调和自动化测试不能替代真实麦克风、摄像头的质量验收。[三人协作分工](docs/三人协作与接口分工_v3.md)已更新；实际协议以 [API 数据协议](docs/api_spec.md) 为准。

## 队员 B 需要交付什么

前端记录实际录音与帧的共同时间轴，上传完整文件，并汇合 ASR 与冻结的视觉聚合结果后自动聊天。后端语音模块执行整段 ASR；视觉模块按区间聚合结构化帧。评估模块从消息上已绑定的逐句快照生成汇总，不重新推断帧与消息的对应关系。

| 时机 | 队员 B 的输出 | 提交位置 |
| --- | --- | --- |
| 用户说完一句话 | ASR 原文 `text`，必填且非空 | `POST /api/chat` 的 `text` |
| 同一句话 | 该句期间聚合的视觉状态 `vision_snapshot`，有数据时提供 | 同一个 `/api/chat` 请求，后续也放在 `evaluation_input.dialogue_history` 的对应消息内 |
| 整段对话结束 | 基于句级视觉状态计算的 `vision_summary` | 通常由后端从消息快照生成；外部也可提交 `evaluation_input.vision_summary` |
| 触发最终评估 | 按时间顺序排列的完整 `dialogue_history` | `POST /api/assessment` 的 `evaluation_input.dialogue_history` |

所有请求使用同一个 `session_id`。`dialogue_history` 的 `role` 可为 `user`、`assistant`、`counselor`、`system`；只有 `user` 的话是被评估者自述，其他角色仅作上下文。每条消息的 `vision_snapshot` 必须对应**这条消息**，由 `/api/vision/segment` 冻结，不能用最近一帧代替。没有采集到视觉时省略快照；缺测值用 `null`，不要填 `0`。语音模块只提供转写文本，不需要提交音频特征。

### 1. 每句话的语音与视觉输出

语音模块至少给出 ASR 原文。视觉模块对这句话的起止区间进行采样和聚合，然后与文本一起提交：

```http
POST /api/chat
Content-Type: application/json
```

```json
{
  "session_id": "会话 ID",
  "text": "最近总是睡不好",
  "vision_snapshot": {
    "face_detected": true,
    "emotion": "sad",
    "emotion_confidence": 0.82,
    "valence": -0.4,
    "arousal": 0.35,
    "engagement": 0.7,
    "attention_score": 0.6,
    "gaze_focus": 0.55,
    "micro_expression_intensity": 0.3
  }
}
```

`text` 是参与对话决策和最终评估的转写文本。`vision_snapshot` 可省略。`POST /api/vision/frame` 提供单帧分析；新页面先登记 `/api/vision/capture`，再提交带 `frame_id/capture_id/captured_at_ms` 的帧，并用 `/api/vision/segment` 聚合为句级快照。已绑定消息的快照会在评估时生成会话汇总；旧无时间帧日志不参与该过程。

句级 `vision_snapshot` 使用 `VisionState`：`emotion` 为可选字符串；`emotion_confidence`、`arousal`、`engagement`、`attention_score`、`gaze_focus`、`micro_expression_intensity` 为可选的 0～1 数值；`valence` 为可选的 -1～1 数值；`face_detected` 为布尔值；`timestamp` 可选，使用 ISO 8601 时间。具体定义见 [`backend/models/states.py`](backend/models/states.py)。

### 2. 整段对话的视觉输出与评估交接

队员 B 把完整对话按顺序交给评估端。每条有视觉数据的消息都带自己的 `vision_snapshot`；整段统计单独放在顶层 `vision_summary`：

```http
POST /api/assessment
Content-Type: application/json
```

```json
{
  "session_id": "会话 ID",
  "evaluation_input": {
    "dialogue_history": [
      {
        "role": "user",
        "content": "最近总是睡不好",
        "vision_snapshot": {
          "face_detected": true,
          "emotion": "sad",
          "valence": -0.4
        }
      },
      {
        "role": "assistant",
        "content": "最近是入睡困难，还是容易醒？"
      }
    ],
    "vision_summary": {
      "dominant_emotion": "sad",
      "mean_valence": -0.4,
      "mean_arousal": 0.35,
      "mean_engagement": 0.7,
      "mean_attention": 0.6,
      "valence_trend": [-0.4],
      "face_present_ratio": 1.0,
      "sample_count": 1
    }
  }
}
```

`dialogue_history` 至少一条消息，每条 `content` 必须非空。`vision_summary` 的均值和 `face_present_ratio` 范围分别为 -1～1 或 0～1；`valence_trend` 按**句级样本**的时间顺序排列；`sample_count` 是参与汇总的句级样本数，不是摄像头帧数。没有视觉能力时省略 `vision_snapshot` 和 `vision_summary`，不要构造全零汇总。`evaluation_input.user_memory` 可选，用于长期背景信息。

当前页面触发最终评估时只需提交 `{ "session_id": "会话 ID" }`。后端会使用会话内已保存的文本和准确附着在消息上的快照；缺失的视觉数据保持缺失。评估服务把对话原文和结构化视觉状态发送到配置的 DeepSeek 接口，不发送原始音频或图像。当前响应包含五维画像、0～100 关注指数、关注等级、独立风险结果，以及 `result.report` 中的总体说明、关键发现、趋势说明与建议。文案为规则模板：缺少可靠纵向数据时，趋势会明确标为 `unclear`；不会把视觉缺测当作一致性 0 分。页面字段见 [评估结果页面交接文档](docs/assessment_output_page_handoff.md)。

评估记忆按匿名 `student_ref` 自动保存每人最近 3 次完整结果到本机 SQLite。
页面在同一浏览器的新会话中复用该标识；`GET /api/history/{student_ref}` 可读取结果，
后端重启后仍保留。历史结果目前用于查询，不自动改变新一次评估的打分。

## 对话数据流验收（MVB）

按下文创建并激活统一 Conda 环境后运行：

```powershell
python -m pytest -q tests/test_conversation_data_flow.py
```

该测试仅在**两个外部模型接口**返回可控响应，项目内部仍实际执行：创建会话 → 接收视觉状态和逐句对齐快照 → 调用策略客户端 → 保存用户与助手消息 → 构造评估输入 → 评估 Agent 解析 11 项并计算五维和关注指数 → 保存评估 → 按结果 ID 和学生历史查询。另一路测试验证上游直接提交完整 `dialogue_history` 与 `vision_summary` 时，这两层视觉数据进入评估请求。

这些测试没有连接真实训练决策模型或 DeepSeek，因此通过不代表外部模型可用。新增对接回归测试见 `tests/test_vision_alignment.py`；前端媒体生命周期与上传协议测试使用 `cd frontend; npm test`。实际设备、光照与真人发音仍需验收。

## 本地运行

### 环境要求

- Windows x64 + NVIDIA 显卡，驱动需支持 CUDA 12.8；可用 `nvidia-smi` 检查驱动状态。
- Miniforge 或 Anaconda 均可，团队统一使用 Python 3.11.16、pip 26.2.1。
- PyTorch 和 torchaudio 均为 2.8.0+cu128；安装包含 CUDA 运行库，无需另装 CUDA Toolkit。
- 前端统一推荐 Node.js 22.14.0、npm 10.9.2，分别用 `node --version`、`npm --version` 检查。

`environment.yml` 固定 Python、pip 和 Conda 软件源，并引用 `requirements.txt`。
后者是正式功能依赖的唯一来源，包含后端、语音、视觉及基础测试包，统一使用
PyPI 和官方 PyTorch CUDA 12.8 wheel 源。直接依赖已固定版本，间接依赖由 pip
解析，因此这不是完整锁文件，不能保证每次安装的所有间接依赖完全一致。
不要在 `base` 中安装项目包。执行以下命令前，切换到 `mental-health-agent` 项目目录。

### 首次安装

```powershell
conda env create -f environment.yml
conda activate mental-health-agent
python --version
python -m pip check
python -c "import torch, torchaudio; print(torch.__version__, torchaudio.__version__); print('CUDA:', torch.version.cuda, 'available:', torch.cuda.is_available())"
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

Python 应为 3.11.16，torch 和 torchaudio 应为 2.8.0+cu128，CUDA 应为 12.8 且
`available: True`。如果为 False，先检查驱动、显卡和当前 Python 环境。
Windows 下可在 Miniforge/Anaconda Prompt 中使用 Conda；上面的 `.env` 文件复制
命令使用 PowerShell，且不会覆盖已有配置。

### 已有同名环境

先检查现有环境，再按统一配置更新；不需要删除环境。更新会调整 Python、pip
和直接依赖版本，已有其他项目使用的包应放在其他环境中。

```powershell
conda env list
conda list -n mental-health-agent
conda env update -n mental-health-agent -f environment.yml
conda activate mental-health-agent
python --version
python -m pip check
```

后端、语音、视觉及基础测试依赖只维护 `requirements.txt`，通过
`environment.yml` 一次安装。faster-whisper 仅用于可选对照，不属于正式功能；
确需对照时按 [语音对照说明](docs/speech_recognition.md) 安装。

### 启用真实语音、视觉与外部模型

统一环境已安装语音与视觉所需的包。在本地 `.env` 中设置：

```dotenv
ASR_PROVIDER=sensevoice
ASR_DEVICE=cuda:0
VISION_PROVIDER=emotiefflib
```

`.env.example` 仍保留 `ASR_PROVIDER=disabled`、`ASR_DEVICE=cpu`、
`VISION_PROVIDER=mock` 的默认值；复制文件后需要手动启用真实功能。
首次使用会下载 SenseVoice 和 EmotiEffLib 模型，需联网并预留缓存空间。
`GET /api/audio/status` 的 `state=ready` 才表示语音模型可用；详细配置见
[语音识别说明](docs/speech_recognition.md)。

在本地 `.env` 填写真实 `DEEPSEEK_API_KEY`，用于综合评估；不要提交 `.env`。对话动作还需要启动已训练的决策模型服务，并在 `.env` 设置 `POLICY_API_BASE_URL` 等参数。评估 Agent 的 `DEEPSEEK_API_STYLE`、`DEEPSEEK_MAX_OUTPUT_TOKENS`、`DEEPSEEK_TIMEOUT_SECONDS` 等配置见 `.env.example`。缺少密钥或模型服务不可用时，评估接口返回 `503 EVALUATION_UNAVAILABLE`，不会回退到旧六维规则。

### 每次启动后端

```powershell
conda activate mental-health-agent
python -m uvicorn backend.main:app --reload
```

后端地址：<http://127.0.0.1:8000>，API 文档：<http://127.0.0.1:8000/docs>。
语音模型会在启动阶段加载；`--reload` 重载时也会重新加载模型。

### 前端安装与启动

另开终端，在项目目录执行；首次安装或 `package-lock.json` 更新后运行 `npm ci`，
日常启动只需在 `frontend` 目录运行 `npm run dev`。前端包由 npm 管理，不放入
Python 依赖清单。

```powershell
Set-Location frontend
npm ci
npm run dev
```

前端地址：<http://127.0.0.1:5173>。

### 测试与构建

后端在已激活的 Conda 环境中执行 `python -m pytest -q`；前端在 `frontend`
目录执行 `npm test` 和 `npm run build`。离线测试不要求真实模型服务、密钥或设备。

后端接口详情见 [API 数据协议](docs/api_spec.md)，结果页字段与展示交接见 [评估结果页面交接文档](docs/assessment_output_page_handoff.md)，当前模块关系见 [架构说明](docs/architecture.md)。
