# 多模态心理状态筛查 Agent

结合文字对话、语音转写和摄像头表情信息的心理状态筛查原型，提供学生端对话、
综合评估报告和心理老师端历史记录查询。

## 主要功能

- **多轮对话**：由训练的决策模型选择对话动作，使用本地话术生成回复。
- **语音与视觉**：SenseVoice 转写完整录音，CosyVoice 提供助手回复的语音合成接口；EmotiEffLib 分析表情，并按录音区间聚合视觉状态。
- **综合评估**：生成五维心理状态画像、关注指数、关注等级和建议，独立识别危机风险。
- **结果与历史**：展示评估报告，使用 SQLite 保存每位学生最近三次完整评估结果。

项目用于研究与演示，演示使用虚构数据；筛查结果不作为临床诊断。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端 | Python、FastAPI |
| 前端 | React、Vite |
| 语音 | FunASR、SenseVoiceSmall、PyAV、阿里云 CosyVoice |
| 视觉 | EmotiEffLib、OpenCV |
| 对话与评估 | 训练的决策模型服务、DeepSeek |
| 环境 | Conda、PyTorch CUDA 12.8 |

## 本地运行

团队使用 Windows x64 + NVIDIA GPU，Miniforge 和 Anaconda 均可。
Python 3.11.16 由 Conda 配置统一安装；前端推荐 Node.js 22.14.0、npm 10.9.2。
以下命令均在项目根目录执行。

### 1. 首次安装

只需执行一次；后续拉取代码时，如依赖变更，参见 [环境更新说明](docs/environment.md#更新环境)。

```powershell
conda env create -f environment.yml
npm --prefix frontend ci
```

首次运行将 `.env.example` 复制为 `.env`；已有 `.env` 时保留原文件。
填写用于综合评估的 DeepSeek 密钥，并启用语音和视觉：

```dotenv
DEEPSEEK_API_KEY=你的密钥
ASR_PROVIDER=sensevoice
ASR_DEVICE=cuda:0
VISION_PROVIDER=emotiefflib
# 可选：启用助手回复的语音合成接口（华北2/北京的百炼业务空间）
DASHSCOPE_API_KEY=你的百炼密钥
DASHSCOPE_WORKSPACE_ID=你的业务空间ID
```

对话还需要启动小组训练的决策模型服务，默认地址为 `http://127.0.0.1:8001`；
地址不同时修改 `.env` 中的 `POLICY_API_BASE_URL`。
完整配置见 [环境配置与验证](docs/environment.md)。真实密钥只保存在本地 `.env`。
语音合成接口默认使用 `cosyvoice-v3-flash` 的 `longyingtao_v3` 预置音色；
未配置时文字对话仍可使用。前端播放由页面开发者接入；音频不进入评估记录。

### 2. 启动后端

```powershell
conda activate mental-health-agent
python -m uvicorn backend.main:app --reload
```

后端地址：<http://127.0.0.1:8000> · API 文档：<http://127.0.0.1:8000/docs>

### 3. 启动前端

另开一个终端：

```powershell
npm --prefix frontend run dev
```

打开 <http://127.0.0.1:5173>，可切换学生端和心理老师端。
首次启用语音与视觉时会下载并加载模型，准备完成后再使用设备功能。

## 项目结构

```text
backend/           后端服务、对话编排、语音与视觉处理
evaluation_agent/  综合评估与评分
frontend/          学生端与心理老师端界面
tests/             后端测试
scripts/           验证与基准脚本
docs/              架构、接口与协作说明
environment.yml    Conda 环境配置
requirements.txt   完整后端依赖（含语音、视觉与基础测试）
```

## 开发与测试

激活 Conda 环境后，在项目根目录执行：

```powershell
python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

集成测试使用可控的外部模型响应；验收范围见
[对话数据流验收](docs/environment.md#对话数据流验收mvb)。

## 项目文档

- [环境配置与验证](docs/environment.md)
- [系统架构](docs/architecture.md)
- [API 数据协议](docs/api_spec.md)
- [三人协作与接口分工](docs/三人协作与接口分工_v3.md)
- [语音识别说明](docs/speech_recognition.md)
- [摄像头与录音对接](docs/vision_alignment.md)
- [评估结果页面交接](docs/assessment_output_page_handoff.md)
- [真实用户上线前审查](docs/prelaunch_audit_2026-10-01.md)
