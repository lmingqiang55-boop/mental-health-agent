# 多模态心理状态筛查与知识增强对话系统 v0.2

比赛用本地 Demo。当前版本已按目标效果图搭好**完整框架骨架与数据协议**：
实时对话闭环、多模态综合评估、评估记忆库、学生端与心理老师端双入口。
对话的下一步提问由已训练的决策模型决定，视觉/音频等具体算法用 Mock 或
规则占位，模块间通过统一数据结构连接。

系统只提供初步状态筛查演示和风险提示，不提供临床诊断。

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

macOS/Linux：`source .venv/bin/activate`。后端地址：<http://127.0.0.1:8000>，
API 文档：<http://127.0.0.1:8000/docs>。

## 前端启动

另开终端：

```powershell
cd frontend
npm install
npm run dev
```

前端地址：<http://127.0.0.1:5173>。顶部可切换「学生端 / 心理老师端」。
先启动后端再打开网页，页面初次打开会自动创建会话。

## 主链路验证

```text
创建会话 → 多轮文字对话（下一步提问由本机决策模型决定）
        → 可选开启摄像头/麦克风（提交 Mock 状态）
        → 点「生成初步结果」显式触发综合评估（维度得分/风险/建议）
        → 老师端查看记录、高风险名单、群体统计
```

无摄像头、麦克风或 LLM Key 均可跑完整流程；对话本身需要本机决策模型服务
（见下文「决策模型」），服务不可用时接口返回明确错误而不是退回规则提问。

## 测试与构建

```powershell
python -m pytest -q
cd frontend
npm run build
```

## 配置

默认 `LLM_PROVIDER=mock`，无需密钥；设置未接入的 Provider 会自动降级为 Mock。
Session 与记忆库保存在进程内存中，TTL 2 小时，重启清空。
CORS 来源可用环境变量 `CORS_ORIGINS` 配置。

### 决策模型（对话的必需依赖）

对话的下一步动作全部由已训练的决策模型决定。六维固定提问状态机与
`POLICY_PROVIDER=legacy` 回退路径已删除：模型不可用时 `/api/chat` 返回
`503 POLICY_UNAVAILABLE`，不会改回按维度规则提问。在项目根目录的本地
`.env` 设置：

```dotenv
POLICY_API_BASE_URL=http://127.0.0.1:8001
POLICY_API_MODEL=你的模型名称
```

模型服务需在本机回环地址提供 OpenAI 兼容的
`POST /v1/chat/completions`，输出如 `{"actions":["共情安慰","睡眠"]}`。
本机服务如需密钥，可在 `.env` 设置 `POLICY_API_KEY`。每轮会将截至当前
用户发言的对话历史发送给本机决策模型；危机消息优先走现有风险处理。
模型选出的动作由本地基础话术执行，不会再次将对话发给回复生成服务。

模型的 11 个动作里没有「结束评估」动作，因此对话没有自动结束信号：
会话级多模态汇总与综合评估由学生端的「生成初步结果」调用
`POST /api/assessment` 显式触发。

### 摄像头情绪识别（EmotiEffLib）

学生端开启摄像头后，会每 1.5 秒将一张压缩帧提交到
`POST /api/vision/frame`。后端只保存结构化 `VisionState`，不保存原始图像。
默认 `VISION_PROVIDER=mock`，不安装模型也能运行完整流程。

要启用 EmotiEffLib 的 ONNX 情绪模型：

```powershell
pip install -r requirements-vision.txt
$env:VISION_PROVIDER = "emotiefflib"
```

首次分析会自动下载模型到用户缓存目录。当前单帧接口输出情绪、置信度和
VA（valence/arousal）；EmotiEffLib 要求 128 帧滑动窗口才能计算 engagement，
眼动相关字段也尚未接入连续帧处理，因此这些字段返回 `null`，不会伪装成真实测量。

## 后续 TODO

- 接入真实 LLM Provider 负责「怎么表达」；提问方向继续由决策模型决定。
- 决策模型只输出动作。若以后要支持「结束评估」，先在训练侧补一个显式动作
  再由 `/api/chat` 识别，不要拿「筛查」当结束信号。
- 接入真实视觉（表情/眼动）与音频（ASR/副语言）模型。
- 引入持久化数据库、身份认证与权限管理。
- 审核后接入标准量表（PHQ-9 等）与心理健康知识。
- 完善人工复核、双向沟通与长期跟踪闭环。
