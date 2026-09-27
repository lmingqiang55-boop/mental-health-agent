# 三人协作框架 v2

## 1. 三个人只记住一句话

- **A**：决定"问什么"
- **B**：提供"用户现在是什么状态"
- **C**：负责"用户怎么使用整个系统"

实际数据流：

```text
               C：前端 / Session / 系统集成
                          │
                          │ /api
                          ↓
                 ┌────────────────┐
                 │    FastAPI     │
                 └────────┬───────┘
                          │
              ┌───────────┴───────────┐
              ↓                       ↓
    A：Dialogue / RAG / LLM       B：Vision / Audio
        Risk Engine              Multimodal Fusion
              ↑                       │
              └──── VisionState ──────┘
                   AudioState
```

## 2. 三个人到底改哪些代码

| 人 | 负责什么 | 主要修改目录 | 最终交付 |
| --- | --- | --- | --- |
| A 对话负责人 | 对话策略、RAG、LLM、风险提示 | `backend/core/dialogue_manager.py`、`risk_engine.py`、`backend/llm/`、`backend/rag/`、`backend/api/chat.py` | `DialogueResponse` |
| B 多模态负责人 | 摄像头、表情、VA、参与度、语音、ASR、多模态融合 | `backend/vision/`、`backend/audio/`、`backend/core/multimodal_fusion.py`、`backend/api/vision.py`、`audio.py` | `VisionState`、`AudioState` |
| C 系统负责人 | React 前端、Session、API 集成、以后数据库 | `frontend/`、`backend/core/session_manager.py`、`backend/api/session.py`、`backend/main.py` | 能实际使用的完整 Demo |

这三个职责**不要互相穿透**。

例如 B 为了方便视觉模型，不应该直接去修改 `dialogue_manager.py`；A 也不能因为想使用一个新视觉指标，就直接跑去改 `vision/detector.py`。正确方式是通过公共数据结构连接。

## 3. 三个人的接口关系

### B → A

B 不给 A 模型代码。B 只给：

```json
{
  "emotion": "sad",
  "emotion_confidence": 0.86,
  "valence": -0.42,
  "arousal": 0.31,
  "engagement": 0.67
}
```

也就是 `VisionState`。语音同理：

```json
{
  "text": "最近总是没有精神",
  "speech_rate": 0.72,
  "pause_ratio": 0.31,
  "energy": 0.40,
  "pitch_mean": 0.48
}
```

也就是 `AudioState`。

A 不关心 B 是用 OpenFace、MediaPipe、自己训练的模型还是别的方案。

### A → C

A 不负责页面。A 最终只给 C：

```json
{
  "reply": "这种状态大概持续多久了？",
  "next_strategy": "explore_duration",
  "current_stage": "exploration",
  "risk": {
    "risk_level": "low"
  }
}
```

C 只负责：显示回复、显示进度、显示风险、展示状态。

C 不能在 React 里自己写"如果出现'睡不着' → 下一步询问睡眠"这种规则，这属于 A。

## 4. 哪些文件三个人都不能随便改

你们现在最重要的几个公共文件是：

- `backend/models/states.py`
- `backend/models/response.py`
- `backend/main.py`
- `docs/api_spec.md`
- `docs/architecture.md`

尤其 `backend/models/states.py`，这是你们三个模块之间的"插头标准"。

假设 B 突然想增加 `fatigue_score: float`，不能直接加完就 Push。正确流程：

```text
B：我需要新增 fatigue_score
        ↓
A：确认 Dialogue 是否需要使用
        ↓
C：确认 API / 页面是否受影响
        ↓
更新 api_spec.md
        ↓
修改 states.py
        ↓
修改代码
```

这样不会出现三个人各自理解一个版本。

## 5. Git 分支怎么用

你们就保持最简单的四条：

```text
main
│
├── dev-dialogue
├── dev-multimodal
└── dev-frontend
```

其中：

- A → `dev-dialogue`
- B → `dev-multimodal`
- C → `dev-frontend`

`main` 的定义非常重要：**main 永远是当前能运行、能演示的版本。** 所以不要直接让 Codex 在 main 上疯狂改。

每天开始工作：

```bash
git checkout main
git pull
git checkout dev-dialogue
git merge main
```

B/C 换成自己的分支即可。

## 6. 每次 Codex 只能完成"小任务"

以后不要再给 Codex"帮我继续优化整个项目"这种 Prompt。统一使用这种格式：

```text
你现在负责成员 B 的多模态模块。

本次目标：
实现摄像头画面到 VisionState 的基本分析。

允许修改：
backend/vision/
backend/api/vision.py
tests/

禁止修改：
backend/core/dialogue_manager.py
backend/llm/
backend/rag/
frontend/
公共接口字段

完成标准：
1. 可以正常读取摄像头
2. 输出符合 VisionState
3. 没有摄像头时不能导致整个后端崩溃
4. 添加测试
5. 运行 pytest
6. 总结修改文件
```

以后你们三个人都按这个格式 Vibe Coding。

## 7. 不等队友，全部使用 Mock

这是三人协作最关键的一条。

假如 B 的视觉模型三天才能做完，A 不等，直接用：

```json
{
  "emotion": "sad",
  "valence": -0.5,
  "arousal": 0.3,
  "engagement": 0.6
}
```

假如 A 的 DialogueManager 还没写好，C 也不等，直接 Mock：

```json
{
  "reply": "最近这种状态大概持续多久了？",
  "next_strategy": "explore_duration",
  "current_stage": "exploration",
  "risk": {
    "risk_level": "low"
  }
}
```

所以：

- A ← Mock VisionState
- B ← Mock Session
- C ← Mock DialogueResponse

三个人始终可以同时开发。

## 8. 第一轮三个人分别干什么

结合现在 GitHub 里的真实代码，第一轮就这么分。

### A：先把"脑子"做出来

现在仓库里已经有：

- `backend/core/dialogue_manager.py`
- `backend/core/risk_engine.py`
- `backend/llm/client.py`
- `backend/llm/prompts.py`
- `backend/rag/retriever.py`

A 第一阶段负责：

```text
固定六维询问
    ↓
更合理的 Dialogue Strategy
    ↓
RAG
    ↓
LLM 自然表达
```

重点先解决：

- 是否会重复问
- 什么时候追问
- 什么时候切换维度
- 什么时候结束
- 历史回答怎么影响下一问

先不要折腾多 Agent。

### B：先把 Vision 做真实

现在 `backend/vision/detector.py` 基本还是占位。所以 B 第一个真正任务：

```text
摄像头
    ↓
人脸
    ↓
Emotion
    ↓
Valence
    ↓
Arousal
    ↓
Engagement
    ↓
VisionState
```

视觉跑通以后，再接 Audio。不要视觉、语音同时开坑。

### C：把现在的 Demo 做成人能用的东西

当前 `frontend/src/App.jsx` 已经有最基础页面。第一阶段就负责把它做成真正学生端：

- 创建 Session
- 聊天
- 当前测评进度
- 当前风险等级
- 摄像头状态
- 麦克风状态
- 重新开始测评
- 错误提示

专业端、数据库、历史趋势先放第二阶段。

## 9. 每次合并 main 前只有两个硬要求

后端：

```bash
python -m pytest -q
```

前端：

```bash
cd frontend
npm run build
```

然后手测：

```text
创建 Session
    ↓
发第一条消息
    ↓
获得回复
    ↓
再发第二条
    ↓
turn_count 正常
    ↓
没有 Vision / Audio 也可以继续聊天
```

如果这一条主链断了，不合 main。

## 10. 每天群里只汇报这五行

你们甚至不用每天开长会，统一：

```text
【A / B / C】

今天完成：
-

正在做：
-

改公共接口了吗：
- 没有 / 有：

需要别人配合：
-

现在可以合 main 吗：
- 可以 / 不可以
```

这样作为总体负责人一眼就知道三条线是什么状态。

---

最终整个开发逻辑：

```text
                 用户
                   │
                   ↓
           C：Frontend
                   │
                   ↓
            Session / API
                   │
          ┌────────┴─────────┐
          │                  │
          ↓                  ↓
  A：DialogueManager     B：Multimodal
  RAG / LLM / Risk      Vision / Audio
          ↑                  │
          └──── State ───────┘
                   │
                   ↓
             下一轮问题
```

A 写"大脑"，B 写"眼睛和耳朵"，C 写"身体和界面"。
