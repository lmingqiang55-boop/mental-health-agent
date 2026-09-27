# 多模态心理状态筛查与知识增强对话系统 v0.1

本项目是比赛用的本地 Demo：文字聊天、内存 Session、六维度简单提问、Mock LLM、关键词知识检索和视觉/音频状态接口。无需 API Key。它只提供初步状态筛查演示和风险提示，不提供临床诊断。

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

## 配置

默认使用 `LLM_PROVIDER=mock`，不需要复制 `.env.example` 或设置密钥。若需明确设置，可在启动后端的终端设置环境变量；v0.1 尚未接入真实 LLM Provider，设置其他值会报错。`.env.example` 是后续对接的配置样例。

Session 保存在单个 Python 进程中，后端重启后会清空。当前音视频接口只接收并保存结构化 Mock 状态，不处理摄像头画面或麦克风音频。详见 [架构](docs/architecture.md)、[API](docs/api_spec.md)、[协作手册](docs/development_rules.md) 和 [产品范围](docs/mvp_scope.md)。

## 后续 TODO

- 接入经审核的心理知识资料与真实检索策略。
- 替换 Mock LLM，同时保留 DialogueManager 的策略决定权。
- 接入真实视觉/音频模型并验证各状态量的意义。
- 引入持久化 Session 与更可靠的风险评估流程。
- 建立学生端结果/历史页与医生/心理老师端，并在真实数据接入前完成身份、授权和同意流程。
