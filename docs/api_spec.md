# API 数据协议 v0.5（2026-10-11）

本次新增对话收尾及视觉触发诊断，队友独立前端的接线说明见
[对话修复接线说明](dialogue_flow_handoff.md)。`/api/chat` 新增 `assessment_ready`、
`completion_reason`、`screening_progress` 和 `visual_feedback`。当
`assessment_ready=true` 时停止输入并显示“生成结果”，点击后才调用 `/api/assessment`。
阶段新增 `assessment_ready`；重复原请求仍返回原响应，新普通聊天返回
`SCREENING_FINISHED`（409），新增危机表述仍优先返回现实支持。

每个普通轮把包含当前学生回答的完整对话交给决策模型，输出严格为
`{"target_item":"11项评估小项之一","question_goal":"本轮要补充的信息"}`。
决策模型同时收到实际 `ITEM_RUBRICS`、当前轮数和35轮上限；对话智能体按这两个字段生成问句。
取消8个大话题的次数约束及对话路由复用，不再注入缺失话题补问提醒。
后端维护11项各自收到回复的次数，并传给决策模型。模型返回
`{"target_item":null,"question_goal":"结束访谈"}` 时，仅当11项各至少收到一次回复才接受收尾
（`completion_reason=model_finished`）；尚有未覆盖项时，后端改为提供一个未覆盖目标继续访谈。
只问出、尚未回答不计覆盖，覆盖齐全也不会自动结束。第35轮仍强制收尾（`turn_limit`），
也接受学生主动结束（`user_requested`），安全流程优先。次数不代表有效证据或评分信息充分，评分算法不变。

`GET /api/vision/status` 返回配置及已加载检测器状态；`visual_feedback.reason` 解释
未提及画面的原因。模拟数据和来源未验证的数据不用于口头描述。短回答的口头观察
可读取冻结时同一摄像头最近 5 秒内的真实帧（末帧距发送不超过 2.5 秒）；
用于最终评估的 `vision_snapshot` 仍严格只取发言时间区间。

基础地址：`http://127.0.0.1:8000`，交互文档：`/docs`。

本文件记录当前已实现的**数据契约**。目标接口与职责见
[三人协作与接口分工 v3](三人协作与接口分工_v3.md)。修改共享字段时，
先更新本文档，再更新 `backend/models/` 和调用代码。

## 总览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| POST | `/api/session` | 创建会话 |
| GET | `/api/session/{id}` | 获取会话完整状态 |
| DELETE | `/api/session/{id}` | 删除会话 |
| PUT | `/api/session/{id}/consent` | 更新知情同意 |
| POST | `/api/chat` | 提交一轮文字对话 |
| POST | `/api/vision` | 提交句级视觉状态（merge） |
| GET | `/api/vision/status` | 视觉配置及检测器加载状态 |
| POST | `/api/vision/frame` | 提交一张摄像头帧并即时分析 |
| POST | `/api/vision/capture` | 开启/关闭采集，使用递增代次隔离旧请求 |
| POST | `/api/vision/segment` | 按发言时间区间聚合并冻结视觉快照 |
| POST | `/api/audio` | 兼容现有实时音频状态；队员 B 的评估交接不需要调用 |
| POST | `/api/audio/transcribe` | 上传完整录音，返回原文与采集时间；不创建聊天回合 |
| GET | `/api/audio/status` | 查看 ASR 就绪状态和录音限制 |
| POST | `/api/assessment` | 用户点击生成结果后触发综合评估 |
| GET | `/api/assessment/result/{result_id}` | 获取评估结果 |
| GET | `/api/history/{student_ref}` | 学生查看历史记录 |
| GET | `/api/teacher/records` | 老师：所有记录 |
| GET | `/api/teacher/records/{id}` | 老师：记录详情 |
| GET | `/api/teacher/student/{ref}` | 老师：个体历史 |
| GET | `/api/teacher/high-risk` | 老师：高风险名单 |
| POST | `/api/teacher/records/{id}/notes` | 老师：添加跟进记录 |
| GET | `/api/teacher/group-stats` | 老师：群体统计 |
| POST | `/api/communication` | 发送双向沟通消息 |
| GET | `/api/communication/{student_ref}` | 获取沟通消息 |

---

## 核心数据结构

### 枚举

```text
RiskLevel          low | medium | high            （评估报告字段，由安全结论单向投影）
SafetyLevel        normal | uncertain | high | imminent
SafetyRoute        continue | safety_review | safety_stop
SessionStage       exploration | safety_review | safety_stop | assessment_ready | assessment | completed
MessageRole        user | assistant | counselor | system
ConsentStatus      not_provided | granted | withdrawn
FollowUpStatus     none | pending | in_progress | resolved
```

### 对话动作（决策模型输出）

对话的下一步提问由已训练的决策模型选择，动作集合固定为 11 个：

```text
其它 / 共情安慰 / 精神状态 / 睡眠 / 情绪 / 自杀倾向 /
躯体症状 / 食欲 / 社会功能 / 兴趣 / 筛查
```

其中没有「结束评估」动作，收尾由模型外的会话控制器负责，并不改动训练动作集合。

### 评估维度（PsychologicalProfile）

新评估 Agent 的五维结果使用 0～100 整数，数值越高表示本次对话中该方面值得关注的信号越突出。对话提问由决策模型选择，不按这些维度固定推进。

| 标识 | 中文名 |
| --- | --- |
| `emotion` | 情绪状态 |
| `interest_motivation` | 兴趣与动力 |
| `sleep_energy` | 睡眠与精力 |
| `attention_thinking` | 专注与思考 |
| `social_daily` | 社交与日常功能 |

### VisionState（句级视觉状态，B → A）

| 字段 | 类型 | 范围 | 说明 |
| --- | --- | --- | --- |
| `emotion` | string \| null | — | 情绪类别 |
| `emotion_confidence` | float \| null | 0~1 | 情绪识别置信度 |
| `valence` | float \| null | -1~1 | 情绪效价 |
| `arousal` | float \| null | 0~1 | 情绪唤醒度 |
| `engagement` | float \| null | 0~1 | 参与度 |
| `attention_score` | float \| null | 0~1 | 眼动注意力 |
| `gaze_focus` | float \| null | 0~1 | 注视点稳定度 |
| `micro_expression_intensity` | float \| null | 0~1 | 微表情强度 |
| `face_detected` | bool | — | 是否检测到人脸 |
| `timestamp` | datetime | — | 服务端 UTC 状态时间，不能替代前端 captured_at_ms |

### AudioState（现有可选状态，不属于评估输入）

| 字段 | 类型 | 范围 | 说明 |
| --- | --- | --- | --- |
| `text` | string \| null | — | ASR 转写文本 |
| `speech_rate` | float \| null | ≥0 | 语速 |
| `pause_ratio` | float \| null | 0~1 | 停顿占比 |
| `energy` | float \| null | 0~1 | 音量能量 |
| `pitch_mean` | float \| null | 0~1（标准化） | 平均音高 |
| `pitch_variability` | float \| null | ≥0 | 音高变化率 |
| `audio_available` | bool | — | 是否有有效音频 |
| `timestamp` | datetime | — | 服务端 UTC 状态时间，不能替代前端 captured_at_ms |

### SessionVisionSummary / SessionAudioSummary（会话级汇总）

视觉汇总由后端从消息快照生成，也支持上游显式提交。字段见
`backend/models/states.py`，包含均值、趋势序列、出现占比和采样数。
评估默认从消息绑定的逐句快照生成 `vision_summary`，sample_count 计句级样本数；无时间帧日志不会直接成为评估输入。完整上游汇总仍可显式提交。

### RiskResult

**评估报告专用字段**。它不再是实时对话的安全结论，而是由当轮安全结论
（`SafetyVerdict`）**单向投影**而来（`backend/safety/projection.py`）：
`normal→low`、`uncertain→medium`、`high`/`imminent→high`。
反向映射（从 RiskResult 推回安全等级）是被禁止的。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `risk_level` | enum | low/medium/high |
| `risk_score` | float 0~1 | 风险分值（非临床概率） |
| `risk_reasons` | string[] | 判定原因 |
| `risk_types` | string[] | 风险类型 |
| `key_evidence` | string[] | 关键对话/行为证据 |
| `requires_intervention` | bool | 是否需要立即干预 |

### SafetyVerdict

系统**唯一**的安全结论来源，由新版 Safety Agent 每轮产出。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `risk_detected` | bool | 是否有风险（`risk_level != normal`） |
| `risk_level` | enum | normal/uncertain/high/imminent |
| `route` | enum | continue/safety_review/safety_stop，由等级派生 |
| `messages` | string[] | 面向用户的消息（≤3 条）；不含任何号码 |
| `hotline_numbers` | string[] | 已核实号码，仅 `safety_stop` 时非空 |
| `model_status` | enum | ok/timeout/parse_error/unavailable |
| `keyword_signals` | SafetySignal[] | 关键词线索（含否定标记），**不决定等级** |
| `rationale` | string \| null | 判定理由（面向人工复核，不展示给学生） |
| `evidence_quotes` | string[] | 原文证据 |
| `engine` | string | 判定引擎标识 |

### Message

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `role` | enum | user/assistant/counselor/system |
| `content` | string | 消息文本 |
| `created_at` | datetime | 时间 |
| `vision_snapshot` | VisionState \| null | 该消息对应的视觉快照 |
| `audio_snapshot` | AudioState \| null | 现有可选字段；新评估 Agent 不读取 |
| `safety` | SafetyVerdict \| null | 该条用户消息的安全结论（后端计算，客户端不可写入） |
| `utterance_id` | string \| null | 客户端发言唯一标识，重试复用 |
| `speech` | SpeechMetadata \| null | 客户端单调时间轴上的实际录音区间 |

`SpeechMetadata` 包含非空 `capture_id` 和有限非负毫秒数
`recording_start_ms`、`recording_end_ms`，结束必须大于开始。它表示录音区间，
不是 VAD 开口/停止时间；不能与服务端 UTC 时间直接比较。

### SessionState

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `session_id` | string | 会话 ID（UUID） |
| `student_ref` | string | 匿名学生标识；跨会话复用以读取同一人尚未删除的评估 |
| `conversation_history` | Message[] | 完整对话历史；新会话的第 1 条是固定开场问题 |
| `turn_count` | int | 已完成回合数 |
| `current_stage` | SessionStage | 当前阶段 |
| `latest_vision_state` | VisionState \| null | 最新视觉状态 |
| `latest_audio_state` | AudioState \| null | 最新音频状态 |
| `vision_state_log` | VisionState[] | 视觉状态日志 |
| `audio_state_log` | AudioState[] | 音频状态日志 |
| `vision_summary` | Summary \| null | 会话级视觉汇总 |
| `audio_summary` | Summary \| null | 会话级音频汇总 |
| `latest_safety` | SafetyVerdict \| null | 最新安全结论（系统唯一安全状态来源） |
| `safety_halted` | bool | 是否已进入安全支持模式；**会话内不会自动解除**，仅人工/管理端可解除 |
| `safety_stage` | enum | none/review/stopped（`stopped` 不可回退） |
| `consent` | ConsentRecord | 知情同意记录 |
| `assessment_result_id` | string \| null | 关联的评估结果 ID |
| `created_at` / `updated_at` | datetime | 时间戳 |

---

## 1. Session 接口

### POST /api/session

首次可无请求体，服务端生成匿名 `student_ref`；同一用户下次新建会话时传回它：

```json
{ "student_ref": "a1b2c3d4-..." }
```

现有页面把该标识保存在当前浏览器的 localStorage。它不是登录凭据，
换浏览器或清除站点数据后会得到新标识。

```json
{
  "session_id": "b4fc1bdd-...",
  "student_ref": "a1b2c3d4-...",
  "opening_message": "你好呀，我们先认识一下吧。你今年几岁、读几年级？最近有什么想和我聊聊的吗？",
  "status": "created"
}
```

页面直接显示 `opening_message`；服务端已把同一句保存为会话第一条助手消息。
它不计入 `turn_count`，第一次用户回答后才由决策模型选择下一步动作。

### GET /api/session/{session_id}

返回完整 `SessionState`。新建会话 `turn_count=0`、`current_stage="exploration"`。

### DELETE /api/session/{session_id}

```json
{ "status": "deleted" }
```

### PUT /api/session/{session_id}/consent

请求：

```json
{ "session_id": "...", "granted": true, "scope": ["screening", "result_storage"] }
```

响应：

```json
{ "session_id": "...", "consent": { "status": "granted", "scope": [...], ... } }
```

---

## 2. Chat 接口

### POST /api/chat

请求：

```json
{
  "session_id": "b4fc1bdd-...",
  "text": "最近总是觉得没什么精神",
  "vision_snapshot": { "face_detected": true, "valence": -0.4 }
}
```

成功响应：

```json
{
  "session_id": "b4fc1bdd-...",
  "reply": "最近睡觉时，主要是入睡困难还是容易醒？",
  "next_strategy": "睡眠",
  "current_stage": "exploration",
  "safety": {
    "risk_detected": false,
    "risk_level": "normal",
    "route": "continue",
    "messages": [],
    "hotline_numbers": [],
    "model_status": "ok",
    "keyword_signals": [],
    "rationale": "未出现人身安全相关线索。",
    "evidence_quotes": [],
    "engine": "graph_safety_v1"
  },
  "messages": ["最近睡觉时，主要是入睡困难还是容易醒？"],
  "turn_count": 1
}
```

`vision_snapshot` 可选；语音模块提供转写文本，视觉模块完成该句话的对齐后
填写视觉快照。省略时消息的视觉快照保持为空，不自动取最近一帧。
`next_strategy` 是本轮 `target_item` 的中文名称；收尾时为 `结束本次筛查`。
`screening_progress.pending_topic` 和 `topic_turns` 保留原API字段名，新记录的键为
11个评估小项的英文名称。次数只表示回答归属，不代表有效证据或充分性。

约定：

- **每个用户消息先做安全判定**（新版 Safety Agent，系统唯一安全来源），
  普通对话每轮调用一次本机决策模型。学生主动结束和35轮强制收尾在决策前处理；
  模型主动结束则是本轮决策的结果。安全分支不调用决策模型。
- 每次成功请求保存一条 user + 一条 assistant 消息，`turn_count` +1。
- 前端显示 `reply`（安全分支为 1~3 条 `messages` 的首条），读取
  `assessment_ready` 控制收尾；不得根据关键词自行决定下一问。
- 决策模型不可用（服务未启动、超时、输出不符合约定）时返回
  `503 POLICY_UNAVAILABLE`，本轮不落库，不会退回规则提问。
- 安全判定不可用时**不放行**：按 fail-to-REVIEW 口径进入 `safety_review`。
- `risk_level` 为 `normal` / `uncertain` / `high` / `imminent`，
  `route` 由后端按等级派生（`normal→continue`、`uncertain→safety_review`、
  `high`/`imminent→safety_stop`），模型无法自行指定路由。
- `hotline_numbers` 只来自后端已核实的部署地区配置，仅在 `safety_stop` 时非空；
  面向学生的 `messages` 中不出现任何号码。
- `uncertain` 进入 `safety_review`（暂停普通评估，下一轮 `normal` 可恢复）；
  `high` / `imminent` 进入 `safety_stop` 并置 `safety_halted`，
  **会话内永不自动解除**，后续正常的表达也不会恢复普通评估。
- 主要话题交流完成、达到轮数上限或用户明确要求停止时，返回
  `assessment_ready=true`，停止追问。最终评估仍由用户点击按钮后
  `POST /api/assessment` 显式触发。完整响应字段及阈值见本文开头。

---

## 3. Vision / Audio 接口

### POST /api/audio/transcribe

使用 `multipart/form-data`，必填字段为 `file`、`session_id`、`utterance_id`、
`capture_id`、`recording_start_ms`、`recording_end_ms`。浏览器发送完整录音，
FormData 的 Content-Type 和 boundary 由浏览器设置，不继承 JSON 请求头。

```json
{
  "session_id": "session-uuid",
  "utterance_id": "utterance-uuid",
  "text": "最近晚上经常睡不着",
  "speech": {
    "capture_id": "capture-uuid",
    "recording_start_ms": 12000,
    "recording_end_ms": 16800
  }
}
```

该接口只转写，不修改回合数、不保存原始音频。成功后由前端与本句视觉结果
汇合，自动调用一次 `/api/chat`，沿用响应中的 `utterance_id`、`speech`。
缺少本句视觉时省略 `vision_snapshot`，语音路径不回退到最新视觉/音频状态。
旧文字请求仍可只发送 `session_id` 和 `text`。

聊天新增可选 `utterance_id` 和 `speech`；提供 `speech` 时必须提供
`utterance_id`。同一会话与发言标识的相同文本、录音元数据和视觉内容重试，
返回首次成功响应，回合数不增加；任一内容改变返回 `409 UTTERANCE_CONFLICT`。
视觉快照的服务端默认 `timestamp` 不参与去重；重试应复用原快照。
策略失败不保存半轮消息或成功缓存。

支持格式、限制、环境设置和联调步骤见 [语音接入说明](speech_recognition.md)。
默认录音上限为 60 秒、文件限额为 10 MiB；允许配置更低时长上限，最高 60 秒。
上传时同时校验采集区间与实际解码时长，超限返回 `422 AUDIO_TOO_LONG`。
`GET /api/audio/status` 单独报告 ASR 状态；通用 `/api/health` 不代表模型已就绪。

### GET /api/tts/status、POST /api/tts/probe 与 POST /api/tts

语音 provider 由 `TTS_PROVIDER` 选择（默认 `cosyvoice`，备选 `edge`）；配置的那
个不可用时自动退到另一个，因此状态接口把两者都报出来。`GET /api/tts/status`
的字段：

| 字段 | 含义 |
| --- | --- |
| `state` | `ready` / `degraded` / `unconfigured` |
| `provider` | 当前实际生效的 provider |
| `configured_provider` | `TTS_PROVIDER` 指定的 provider |
| `fallback_reason` | 两者不同时说明配置的那个为什么没就绪，否则为 `null` |
| `model` / `voice` | 生效 provider 的模型与音色；不可用时为 `null` |
| `reason` | 生效 provider 不可用时缺的是什么 |
| `last_error` | 最近一次真实合成失败的原因 |
| `last_probe` | 最近一次 `POST /api/tts/probe` 的结果快照；没探测过为 `null` |

`state` 只描述配置与最近一次真实结果：`ready` 表示配置与依赖齐全，`degraded`
表示齐全但最近一次真实合成失败过（看 `last_error`），`unconfigured` 表示连回退
后的 provider 都不可用（看 `reason`）。`state=ready` 不代表上游此刻可达。

`POST /api/tts/probe` 真合成两个字的短文本，回答"现在到底能不能出声"；结果按
provider 缓存 60 秒（用 `cached` 区分是否命中缓存），不写数据库、不返回音频：

```json
{ "ok": true, "provider": "cosyvoice", "voice": "longyingtao_v3",
  "model": "cosyvoice-v3-flash", "latency_ms": 812, "audio_bytes": 16384,
  "error": null, "checked_at": 1760000000.0, "cached": false }
```

为什么单独做一个探测接口：`/voices/list` 之类的轻量探测**不算数**——实测它一直
返回 200，而真合成一直返回 403；唯一可信的验证是真合成一次。前端可在用户点
"测试语音"时调用，或让老师端在开课前自检。

`POST /api/tts` 请求：

```json
{ "session_id": "会话 ID", "turn_count": 1 }
```

传 `turn_count: 0` 可合成新会话的固定开场问题；传 `1` 及以上可合成对应回合的助手回复。后端只读取已保存的助手文本，并向当前 provider 请求合成；成功时返回
`audio/mpeg` 音频。前端可在 `POST /api/chat` 返回 `turn_count` 后，携带同一
`session_id` 调用本接口并播放收到的二进制音频。前端播放尚未接入。
密钥不返回浏览器，合成失败不影响聊天或评估，音频不写入数据库。
未配置或上游不可用返回 `503 TTS_UNAVAILABLE`，不存在的回合返回
`404 REPLY_NOT_FOUND`。

### POST /api/vision

请求（状态字段全部嵌套在 `state` 中，支持部分更新）：

```json
{
  "session_id": "b4fc1bdd-...",
  "state": {
    "emotion": "sad", "emotion_confidence": 0.8,
    "valence": -0.4, "arousal": 0.3, "engagement": 0.6,
    "face_detected": true
  }
}
```

响应：

```json
{
  "session_id": "...", "status": "updated",
  "vision_state": { ... }
}
```

**merge 语义**：只更新 `state` 中传入的字段，未传字段保持原值；同时追加到
`vision_state_log`。当前不接收图像/视频文件。

### POST /api/audio

```json
{
  "session_id": "...",
  "state": { "speech_rate": 0.7, "energy": 0.4, "audio_available": true }
}
```

同样为 merge 语义。当前不接收录音文件。

Vision/Audio 未提交时分别为 `null`，聊天必须正常工作。

### POST /api/vision/frame

请求体：

```json
{
  "session_id": "b4fc1bdd-...",
  "image_base64": "data:image/jpeg;base64,..."
}
```

这是兼容旧客户端的无时间请求。新页面使用文末“带时间的视觉采集”协议，
无时间帧不能进入录音区间聚合。

服务端按 `VISION_PROVIDER` 选择 Mock 或 EmotiEffLib，返回与 `POST /api/vision`
相同的 `VisionState`，并将原始帧丢弃。帧接口写入检测器返回的完整快照，
不会把缺失字段与上一帧做 merge；没有检测到人脸时，情绪、VA 和参与度等字段
会返回 `null`。图片解码后的像素数超过 `1920×1080` 时返回 `422 INVALID_FRAME`。
新配置默认 provider 为 `emotiefflib`，真实检测需要依赖和模型权重；
既有 `.env` 不会随 Git 更新，请检查 `VISION_PROVIDER` 或使用启动参数
`--vision-provider emotiefflib`。显式 `mock` 仅用于接线测试，不触发表情描述。
安装方式见 [README](../README.md#本地运行)。

---

## 4. Assessment 接口

### POST /api/assessment

显式触发综合评估。上游语音/视觉模块完成逐句对齐后，直接提供
`evaluation_input`：每句话的 `vision_snapshot` 放在对应消息内，整段对话的
`vision_summary` 放在顶层。评估服务直接接收这些结构，不用摄像头帧的时间戳
重新猜测逐句对应关系。当前文字和语音页面均可只传 `session_id`，
服务端从已保存的消息及绑定快照构造输入和会话汇总；没有对应快照的消息保持为空。

```json
{
  "session_id": "...",
  "evaluation_input": {
    "dialogue_history": [
      {
        "role": "user",
        "content": "最近总睡不好",
        "vision_snapshot": {
          "face_detected": true,
          "emotion": "sad",
          "valence": -0.4
        }
      }
    ],
    "vision_summary": {
      "dominant_emotion": "sad",
      "mean_valence": -0.4,
      "valence_trend": [-0.4],
      "sample_count": 1
    }
  }
}
```

响应：

```json
{
  "session_id": "...", "status": "completed",
  "result": {
    "result_id": "...",
    "session_id": "...",
    "psychological_profile": {
      "emotion": 42,
      "interest_motivation": 34,
      "sleep_energy": 67,
      "attention_thinking": 0,
      "social_daily": 25
    },
    "concern_index": 44,
    "overall_level": "mild_concern",
    "risk": { ... },
    "report": {
      "overall_status": { "level": "mild_concern", "concern_index": 44, "summary": "..." },
      "psychological_profile": { ... },
      "primary_concern": { "dimension": "sleep_energy", "description": "..." },
      "key_findings": [
        { "title": "...", "description": "..." },
        { "title": "...", "description": "..." }
      ],
      "multimodal_observation": {
        "consistency_score": null, "consistency_level": "unknown", "summary": "..."
      },
      "trend_and_suggestions": {
        "trend": "unclear", "trend_summary": "...", "suggestions": ["...", "..."]
      },
      "metadata": { "schema_version": "1.0", "assessment_id": "...", "generated_at": "..." }
    },
    "assessment_method": "evaluation_agent",
    "created_at": "..."
  }
}
```

### GET /api/assessment/result/{result_id}?session_id=...

返回同一结构。

### EvaluationResult 字段说明

| 字段 | 说明 |
| --- | --- |
| `age` | 用户第一句明确说明的年龄，整数岁 |
| `grade` | 用户第一句明确说明的年级，例如 `初一` |
| `psychological_profile` | 评估 Agent 的五维画像，各维 0~100 |
| `concern_index` | 五维派生的关注指数，0~100 |
| `overall_level` | 关注等级 |
| `risk` | 独立风险识别结果 |
| `report` | 六个报告区块及技术元信息；完整结构见 [评估结果页面交接文档](assessment_output_page_handoff.md) |
| `assessment_method` | 固定为 `evaluation_agent` |

报告文案由后端按已计算分数生成。缺少前后对比时趋势为 `unclear`。视觉一致性由后端逐句比对文字极性与人脸效价得出：可比较的句子达到 2 句时给出 0～100 的 `consistency_score` 与 `low` / `moderate` / `high` 等级（两路信号完全同向为 100，方向相反为 0）；没有视觉数据、或可比较的句子不足 2 句时 `consistency_level` 为 `unknown`、`consistency_score` 为 `null`，并在 `summary` 里写明是哪一种情况。该分数只表示文字自述与面部表现是否对得上，不代表诊断置信度，也不表示受访者是否诚实。以上响应片段省略了部分字段与数组项；可直接用于页面模拟的完整响应见 [示例 JSON](examples/assessment_response.json)。
未配置 `DEEPSEEK_API_KEY` 或评估服务不可用时，接口返回
`503 EVALUATION_UNAVAILABLE`，不会生成规则式六维结果。评估调用会向配置的
DeepSeek 接口发送对话原文及结构化视觉状态；不发送原始音频和图像。

---

## 5. History 接口

### GET /api/history/{student_ref}

每次成功评估会自动保存完整结果到本机 SQLite。每个 `student_ref` 只保留最近
3 次，第四次保存时移除最早一次；后端重启后仍可查询。历史结果不会自动作为
本次评估的打分依据。数据库位于未纳入 Git 的 `data/evaluation_memory.sqlite3`。

```json
{
  "student_ref": "...",
  "records": [ { "record_id": "...", "result": {...}, ... } ],
  "total": 3
}
```

---

## 6. Teacher 接口

### GET /api/teacher/records

返回所有记录的摘要列表。

### GET /api/teacher/records/{record_id}

返回单条完整 `EvaluationRecord`（含结果与跟进记录）。

### GET /api/teacher/student/{student_ref}

返回该学生全部历史记录。

### GET /api/teacher/high-risk

返回中/高风险学生名单及风险类型、原因、关键证据。

### POST /api/teacher/records/{record_id}/notes

```json
{ "counselor_ref": "teacher-01", "content": "已电话联系，建议下周面询。" }
```

### GET /api/teacher/group-stats

```json
{
  "total_students": 3,
  "risk_distribution": { "low": 2, "medium": 1, "high": 0 },
  "dimension_averages": { "mood": 0.32, "pressure": 0.41 }
}
```

---

## 7. Communication 接口

### POST /api/communication

```json
{
  "student_ref": "...", "counselor_ref": "teacher-01",
  "direction": "student_to_counselor",
  "content": "老师，我想约一次咨询。"
}
```

### GET /api/communication/{student_ref}

返回该学生与老师的全部人工沟通消息。人工消息与 AI 消息分别标识。

---

## 8. 错误约定

统一格式：

```json
{ "error": { "code": "...", "message": "..." } }
```

| HTTP | code | 触发场景 |
| --- | --- | --- |
| 404 | `SESSION_NOT_FOUND` | 会话不存在/已过期 |
| 404 | `RESULT_NOT_FOUND` | 评估结果不存在 |
| 404 | `RECORD_NOT_FOUND` | 记忆库记录不存在 |
| 422 | `VALIDATION_ERROR` | 字段缺失/空白/越界 |
| 409 | `UTTERANCE_CONFLICT` | 同一发言 ID 的聊天输入变化，或标识已存在于导入历史 |
| 409 | `HISTORY_CONFLICT` | 完整评估输入改动已标识的消息或评估期间发生新的聊天 |
| 415 | `UNSUPPORTED_AUDIO_FORMAT` | 不支持的 MIME 或实际容器不匹配 |
| 413 | `AUDIO_TOO_LARGE` | 文件或 multipart 总上传字节超限 |
| 422 | `INVALID_AUDIO` / `AUDIO_TOO_LONG` / `AUDIO_TIME_MISMATCH` | 解码、实际时长或时间轴校验失败 |
| 422 | `NO_SPEECH` / `TRANSCRIPT_TOO_LONG` | 无有效语音或转写超过聊天文本限制 |
| 503 | `ASR_UNAVAILABLE` / `ASR_BUSY` | 模型未就绪、推理失败或队列已满 |
| 504 | `ASR_TIMEOUT` | 识别等待超时，客户端可保留原录音重试 |
| 400 | `HTTP_ERROR` | 其他请求错误 |
| 503 | `POLICY_UNAVAILABLE` | 决策模型不可用或输出无效（对话不会退回规则提问） |

不向前端返回 Python traceback。

---

## 数据边界

- Session 与治愈陪伴状态为进程内存，重启清空，TTL 2 小时；评估结果使用 SQLite 持久保存，直到用户主动删除。
- 所有风险/评估结果均为**初步筛查提示**，不得表述为临床诊断或治疗建议。
- `session_id` 是会话定位符，不是身份认证或授权凭据。
- 不提交 `.env`、密钥、原始音视频或真实个人对话。


## 2026-10-03：带时间的视觉采集与录音页面

旧不带时间的帧请求仍用于实时展示。新页面先调用以下采集接口，再提交带时间的帧；未知帧字段会拒收，防止拼写错误静默丢失时间。

### POST /api/vision/capture

```json
{"session_id":"...","capture_id":"capture-1","generation":1,"active":true}
```

关闭使用 active=false 并递增 generation。迟到的低 generation 命令不改变当前采集；同代次相同内容可重试，不同内容返回 409 VISION_CAPTURE_CONFLICT。关闭清空 latest_vision_state。响应为当前 session_id/capture_id/generation，关闭时 capture_id=null。

### POST /api/vision/frame（扩展）

```json
{"session_id":"...","image_base64":"data:image/jpeg;base64,...","frame_id":"frame-1","capture_id":"capture-1","captured_at_ms":12500.5}
```

frame_id/capture_id 为 1～128 字符非空标识，captured_at_ms 为有限非负数；三者同时提供或同时省略。带时间的帧要求当前活动 capture_id 匹配。响应在原 vision_state 之外回显这三项。旧帧在推理前和写回前被拒绝为 409 VISION_CAPTURE_INACTIVE；相同 frame_id 改图像/时间返回 409 VISION_FRAME_CONFLICT。保留最近 512 条结构化帧，不保存图像。

### POST /api/vision/segment

```json
{"session_id":"...","utterance_id":"utterance-1","capture_id":"capture-1","start_ms":12000,"end_ms":16800}
```

区间正时长且不超过 60000 ms，只选同 capture_id 上 [start_ms,end_ms) 的帧。响应示例：

```json
{"session_id":"...","utterance_id":"utterance-1","capture_id":"capture-1","start_ms":12000,"end_ms":16800,"frame_count":8,"valid_frame_count":6,"vision_snapshot":{"face_detected":true,"emotion":"sad","valence":-0.4}}
```

首次结果冻结；重试不吸收晚到帧，改变区间返回 409 UTTERANCE_CONFLICT。无帧 vision_snapshot=null；全无脸为 face_detected=false 且数值为 null。有脸指标只平均非缺失数值。聊天须复用冻结快照；speech 存在时也必须匹配其 capture_id 与区间。

### 聊天与评估保留规则

新页面传递 utterance_id、vision_snapshot（可为 null），语音还传递 speech。显式 null 不借用旧视觉。旧文字客户端的实时风险计算仅借用最近 5 秒的视觉状态，不将它存为句级证据。

简单评估 {session_id} 从消息上的用户快照构造汇总，sample_count 计句级样本，按句等权；face_present_ratio 是句级有效人脸比例。完整输入省略或 null 的视觉快照不会删除既有快照，改写已绑定视觉返回 HISTORY_CONFLICT；省略汇总时按已有快照生成。简单与完整评估均拒绝将评估期间已过时的历史结果链接到会话。

前端 FormData 上传 /api/audio/transcribe 时不设置 JSON Content-Type；须由浏览器附加 multipart boundary。已提供录音按钮、取消、最长时长、收尾、视觉等待和失败重试，细节见 [当前对接说明](vision_alignment.md)。

## 2026-10-04：治愈 Agent 后端接口

新增 `POST /api/healing/start`、`GET /api/healing/{session_id}` 和 `POST /api/healing/chat`。
这三项接口维护独立陪伴状态，不改动原筛查聊天、评估结果或老师跟进字段。
请求、响应、幂等约定、错误码和前端接入要求见 [治愈 Agent 交接](healing_agent.md)。

2026-10-05 补充：接口字段保持兼容。多诉求进入时可先返回无方法的优先方向确认；明确方向后生成支持报告。新限制会调整方法可用性，明确无效反馈保留原关联；有经来源校验的简短表达时可简化同一方法。风险字段缺失、默认来源无法确认或相互矛盾时暂停普通支持，`status=referred` 不表示已通知任何现实人员。报告的知识来源及内部反馈关联仍只留在后端。

2026-10-06 年龄与年级接通：`/api/healing/start` 从最新持久评估的 `result.age` 读取年龄，从 `result.grade` 映射已识别的学段。`background.age` 已移除，显式传入返回 422；通常只需 `session_id`、`request_id`，其他背景按需传入。缺失年龄不根据年级或旧记录补齐；记忆年龄超出当前支持的 6–18 岁或与最终学段冲突返回 422 `VALIDATION_ERROR`，缺少评估记录仍返回 409。恢复沿用原绑定，显式重生成成功后才绑定最新评估；具体学段兼容和未知字段约定见 [治愈 Agent 交接](healing_agent.md)。
