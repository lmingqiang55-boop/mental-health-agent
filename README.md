# 多模态心理状态筛查与知识增强对话系统 v0.2

比赛用本地 Demo。当前版本已按目标效果图搭好**完整框架骨架与数据协议**：
实时对话闭环、多模态综合评估、评估记忆库、学生端与心理老师端双入口。
视觉/音频/LLM 等具体算法用 Mock 或规则占位，模块间通过统一数据结构连接。

系统只提供初步状态筛查演示和风险提示，不提供临床诊断。

## 三人分工

| 成员 | 角色 | 负责模块 | 主要交接接口 |
| --- | --- | --- | --- |
| A 对话 | 写"大脑"：问什么 | `core/dialogue_manager`、`risk_engine`、`assessment_engine`、`llm/`、`rag/` | `DialogueResponsePayload`、`AssessmentResult` |
| B 多模态 | 写"眼睛和耳朵"：用户状态 | `vision/`、`audio/`、`core/multimodal_fusion` | `VisionState`、`AudioState`、会话级 Summary |
| C 系统 | 写"身体和界面"：怎么使用 | `frontend/`、`core/session_manager`、`memory_store`、`communication`、`api/` | `SessionState`、`AssessmentRecord` |

协作规则见 [三人协作框架](docs/development_rules.md)，数据契约见
[API 数据协议](docs/api_spec.md)，模块映射见 [架构说明](docs/architecture.md)。

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
创建会话 → 多轮文字对话（六维依次询问）
        → 可选开启摄像头/麦克风（提交 Mock 状态）
        → 对话结束自动生成评估结果（维度得分/风险/建议）
        → 老师端查看记录、高风险名单、群体统计
```

无摄像头、麦克风或 LLM Key 均可跑完整流程。

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

- 接入真实 LLM Provider，保留 DialogueManager 的策略决定权。
- 接入真实视觉（表情/眼动）与音频（ASR/副语言）模型。
- 引入持久化数据库、身份认证与权限管理。
- 审核后接入标准量表（PHQ-9 等）与心理健康知识。
- 完善人工复核、双向沟通与长期跟踪闭环。
