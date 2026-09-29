# 多模态心理状态筛查与知识增强对话系统

本项目是比赛用的本地 Demo：文字聊天、内存 Session、六维度简单提问、Mock LLM、关键词知识检索和视觉/音频状态接口。另有一个独立的**对话式 PHQ-A 条目映射状态机原型**，提供逐题证据与完整时的程序计分。测评默认无需 API Key，也可接云端或本地的 OpenAI 兼容模型做结构化证据抽取。它只提供筛查流程演示，不提供临床诊断。

项目目标有两个前端：**学生端**负责对话、查看自身筛查结果与建议；**医生/心理老师端（专业端）**负责授权范围内的个体查看、风险人工跟进和群体概览。当前 v0.1 仅实现学生端的基础文字聊天页，专业端与长期用户数据仍是待开发模块。图中功能与代码现状对照见 [MVP 范围与双端规划](docs/mvp_scope.md)。

## 三人分工

| 成员 | 负责范围 | 主要交接接口 |
| --- | --- | --- |
| A：项目对话 | 状态机、下一问、知识检索、LLM 接口、初步风险提示 | `DialogueManager.process_turn()`、`POST /api/chat` |
| B：多模态输入 | 视觉、音频状态与融合接口 | `VisionState`、`AudioState`、`fuse()`、`POST /api/vision`、`POST /api/audio` |
| C：双前端与用户数据 | 学生端、专业端、Session/结果数据设计与管理 | `SessionState`、Session API、两个前端的 `/api` 调用 |

修改共享模型或接口前，先看 [三人协作开发手册](docs/development_rules.md) 和 [API 契约](docs/api_spec.md)。

## 环境要求

- Python 3.11 或更新版本
- Node.js 20.19+ 或 22.12+

## 后端启动

在 `mental-health-agent` 目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

macOS/Linux 激活命令：`source .venv/bin/activate`。后端地址：<http://127.0.0.1:8000>，API 文档：<http://127.0.0.1:8000/docs>。

## 前端启动

另开终端：

```powershell
cd frontend
npm install
npm run dev
```

前端地址：<http://127.0.0.1:5173>。Vite 将 `/api` 请求代理到本机后端；先启动后端再打开网页。页面初次打开会自动创建 Session。

## 测试与构建

```powershell
python -m pytest -q
cd frontend
npm run build
```

## 对话式九项测评

测评契约见 [assessment_contract.md](docs/assessment_contract.md)。新接口 `POST /api/assessment` 返回第一问；用响应中的 `session_id` 调用 `POST /api/assessment/{session_id}/turn`，请求体为 `{ "text": "有几天" }`。响应包含下一问和逐项报告。九项全部明确确认时才生成 `mapped_total`；含糊、冲突、停止或安全暂停时总分为 `null`。`GET /api/assessment/{session_id}/report` 可查看当前结果。

默认规则 Mock 能演示状态转移与计分约束，不能理解任意自然语言。启用模型后，模型只定位本轮原话和候选条目；服务端重新核对引文、条目线索、回顾期和四档频率，再由状态机计分及决定下一问。模型返回格式无效或服务不可用时，本轮返回 503，原会话不变。现有前端仍使用旧的 `/api/chat`。API 细节见 [api_spec.md](docs/api_spec.md)。

## 配置

旧 `/api/chat` 仍使用 `LLM_PROVIDER=mock`。独立的 `/api/assessment` 默认 `ASSESSMENT_EXTRACTOR=mock`。要为测评接入一个支持 `/chat/completions` 和 JSON 对象响应的 OpenAI 兼容服务，在**启动后端的同一终端**设置：

```powershell
$env:ASSESSMENT_EXTRACTOR = 'openai_compatible'
$env:ASSESSMENT_LLM_BASE_URL = 'http://127.0.0.1:8001/v1'
$env:ASSESSMENT_LLM_MODEL = 'your-model-id'
# 云端服务需要密钥时再设置：$env:ASSESSMENT_LLM_API_KEY = '...'
$env:ASSESSMENT_QUESTION_GENERATOR = 'openai_compatible'
$env:ASSESSMENT_DECIDER_MODEL = 'your-decision-model'
$env:ASSESSMENT_GENERATOR_MODEL = 'your-question-model'
uvicorn backend.main:app --reload
```

`ASSESSMENT_LLM_BASE_URL` 可换成所选云端服务的兼容 API 地址；本地服务通常不需要密钥。`.env.example` 只是配置示例，程序不自动读取它。测评回答会发送给所配置的模型服务，因此使用真实个人信息前须完成服务选择、数据授权及隐私方案。当前尚未接入真实服务做端到端验收，也未验证该对话方式的测量效度。

决策器和问句生成器可分别设置 `ASSESSMENT_DECIDER_BASE_URL/MODEL/API_KEY/THINKING` 与 `ASSESSMENT_GENERATOR_BASE_URL/MODEL/API_KEY/THINKING`；未设置的字段回退到 `ASSESSMENT_LLM_*`，后者也供证据抽取器使用。当前本地演示配置是 DeepSeek V4 Pro 负责选择主题和提问意图，DeepSeek Flash 负责问句措辞，Flash 还负责证据抽取。启动脚本 `run_deepseek.ps1` 会加载被 Git 忽略的本地 `.env`。模型服务若截断或返回无效 JSON，本轮会报 503 且不会改动测评状态。

Session 保存在单个 Python 进程中，后端重启后会清空。当前音视频接口只接收并保存结构化 Mock 状态，不处理摄像头画面或麦克风音频。详见 [架构](docs/architecture.md)、[API](docs/api_spec.md)、[协作手册](docs/development_rules.md) 和 [产品范围](docs/mvp_scope.md)。

## 后续 TODO

- 接入经审核的心理知识资料与真实检索策略。
- 替换 Mock LLM，同时保留 DialogueManager 的策略决定权。
- 接入真实视觉/音频模型并验证各状态量的意义。
- 引入持久化 Session 与更可靠的风险评估流程。
- 建立学生端结果/历史页与医生/心理老师端，并在真实数据接入前完成身份、授权和同意流程。
