# API 数据协议 v0.2

基础地址：`http://127.0.0.1:8000`，交互文档：`/docs`。

本文件是三个模块之间的**数据契约**。修改任何字段都必须走
`development_rules.md` 第 4 节的公共接口变更流程：先改本文档 → 再改
`backend/models/` → 最后改代码。

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
| POST | `/api/vision/frame` | 提交一张摄像头帧并即时分析 |
| POST | `/api/audio` | 提交句级音频状态（merge） |
| POST | `/api/assessment` | 触发综合评估（对话没有自动结束信号，这是唯一入口） |
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
RiskLevel          low | medium | high
SessionStage       exploration | crisis | assessment | completed
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

其中没有「结束评估」动作，因此聊天不产生自动结束信号。

### 评估维度（AssessmentDimension）

最终评估输出使用的维度；对话提问不再按这些维度固定推进。

| 标识 | 中文名 |
| --- | --- |
| `mood` | 情绪 |
| `pressure` | 压力 |
| `interpersonal` | 人际关系 |
| `self_cognition` | 自我认知 |
| `study_life` | 学习生活 |
| `duration` | 持续时间 |

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
| `timestamp` | datetime | — | 采样时间 |

### AudioState（句级音频状态，B → A）

| 字段 | 类型 | 范围 | 说明 |
| --- | --- | --- | --- |
| `text` | string \| null | — | ASR 转写文本 |
| `speech_rate` | float \| null | 0~1（标准化） | 语速 |
| `pause_ratio` | float \| null | 0~1 | 停顿占比 |
| `energy` | float \| null | 0~1 | 音量能量 |
| `pitch_mean` | float \| null | 0~1（标准化） | 平均音高 |
| `pitch_variability` | float \| null | 0~1 | 音高变化率 |
| `audio_available` | bool | — | 是否有有效音频 |
| `timestamp` | datetime | — | 采样时间 |

### SessionVisionSummary / SessionAudioSummary（会话级汇总）

触发综合评估时由全部句级状态聚合，字段见 `backend/models/states.py`，
包含均值、趋势序列、出现占比和采样数，供综合评估 Agent 使用。

### RiskResult

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `risk_level` | enum | low/medium/high |
| `risk_score` | float 0~1 | 风险分值（非临床概率） |
| `risk_reasons` | string[] | 判定原因 |
| `risk_types` | string[] | 风险类型 |
| `key_evidence` | string[] | 关键对话/行为证据 |
| `requires_intervention` | bool | 是否需要立即干预 |

### Message

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `role` | enum | user/assistant/counselor/system |
| `content` | string | 消息文本 |
| `created_at` | datetime | 时间 |
| `vision_snapshot` | VisionState \| null | 该消息对应的视觉快照 |
| `audio_snapshot` | AudioState \| null | 该消息对应的音频快照 |

### SessionState

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `session_id` | string | 会话 ID（UUID） |
| `student_ref` | string \| null | 匿名学生标识 |
| `conversation_history` | Message[] | 完整对话历史 |
| `turn_count` | int | 已完成回合数 |
| `current_stage` | SessionStage | 当前阶段 |
| `latest_vision_state` | VisionState \| null | 最新视觉状态 |
| `latest_audio_state` | AudioState \| null | 最新音频状态 |
| `vision_state_log` | VisionState[] | 视觉状态日志 |
| `audio_state_log` | AudioState[] | 音频状态日志 |
| `vision_summary` | Summary \| null | 会话级视觉汇总 |
| `audio_summary` | Summary \| null | 会话级音频汇总 |
| `latest_risk` | RiskResult | 最新风险结果 |
| `crisis_mode` | bool | 危机模式标志 |
| `consent` | ConsentRecord | 知情同意记录 |
| `assessment_result_id` | string \| null | 关联的评估结果 ID |
| `created_at` / `updated_at` | datetime | 时间戳 |

---

## 1. Session 接口

### POST /api/session

无请求体。

```json
{ "session_id": "b4fc1bdd-...", "status": "created" }
```

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
{ "session_id": "b4fc1bdd-...", "text": "最近总是觉得没什么精神" }
```

成功响应：

```json
{
  "session_id": "b4fc1bdd-...",
  "reply": "听起来这段时间对你并不容易。最近睡眠怎么样？入睡或早醒有没有困扰你？",
  "next_strategy": "睡眠",
  "current_stage": "exploration",
  "risk": { "risk_level": "low", "risk_score": 0.1, ... },
  "turn_count": 1
}
```

`next_strategy` 是决策模型本轮输出的最后一个动作，取值即上面 11 个动作之一
（危机时为 `crisis_support`），不再是按维度推进的规则策略名。

约定：

- 每轮会把截至当前用户发言的对话历史发给本机决策模型，由模型决定下一步动作。
- 每次成功请求保存一条 user + 一条 assistant 消息，`turn_count` +1。
- 前端只显示 `reply`，不得根据关键词自行决定下一问。
- 决策模型不可用（服务未启动、超时、输出不符合约定）时返回
  `503 POLICY_UNAVAILABLE`，本轮不落库，不会退回规则提问。
- 检测到高风险时进入 `crisis` 阶段并只给出现实支持话术。
- 对话没有自动结束信号（模型的 11 个动作里没有「结束评估」），
  最终评估由 `POST /api/assessment` 显式触发。

---

## 3. Vision / Audio 接口

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

服务端按 `VISION_PROVIDER` 选择 Mock 或 EmotiEffLib，返回与 `POST /api/vision`
相同的 `VisionState`，并将原始帧丢弃。帧接口写入检测器返回的完整快照，
不会把缺失字段与上一帧做 merge；没有检测到人脸时，情绪、VA 和参与度等字段
会返回 `null`。图片解码后的像素数超过 `1920×1080` 时返回 `422 INVALID_FRAME`。
默认 provider 为 `mock`；启用真实模型需安装
`requirements-vision.txt` 并设置 `VISION_PROVIDER=emotiefflib`。

---

## 4. Assessment 接口

### POST /api/assessment

显式触发综合评估。对话不再有自动结束信号，因此这是生成评估结果的唯一入口
（学生端按钮「生成初步结果」调用它）。生成结果后仍可继续对话，需要刷新结果
时再次调用本接口：

```json
{ "session_id": "..." }
```

响应：

```json
{
  "session_id": "...", "status": "completed",
  "result": {
    "result_id": "...",
    "session_id": "...",
    "dimension_scores": [
      {
        "dimension": "mood", "dimension_label": "情绪",
        "score": 0.55, "confidence": 0.6,
        "evidence": ["会话平均效价：-0.42"], "trend": null
      }
    ],
    "overall_score": 0.55,
    "risk": { ... },
    "recommendations": [
      {
        "category": "emotion_regulation",
        "content": "可以尝试规律的深呼吸放松……",
        "priority": 2, "source": "rule"
      }
    ],
    "summary": "本次初步筛查中……",
    "key_concerns": ["情绪：0.55"],
    "assessment_method": "rule",
    "is_ai_generated": true,
    "counselor_reviewed": false,
    "created_at": "..."
  }
}
```

### GET /api/assessment/result/{result_id}?session_id=...

返回同一结构。

### AssessmentResult 字段说明

| 字段 | 说明 |
| --- | --- |
| `dimension_scores` | 各维度得分、置信度、证据、趋势 |
| `overall_score` | 综合困扰程度 0~1 |
| `risk` | 最终风险结果 |
| `recommendations` | 个性化建议（情绪调节/学习生活/求助资源） |
| `summary` | 文字摘要 |
| `key_concerns` | 重要关注点 |
| `assessment_method` | mock/rule/model |
| `counselor_reviewed` | 是否经人工复核 |

---

## 5. History 接口

### GET /api/history/{student_ref}

```json
{
  "student_ref": "...",
  "records": [ { "record_id": "...", "result": {...}, ... } ],
  "total": 1
}
```

---

## 6. Teacher 接口

### GET /api/teacher/records

返回所有记录的摘要列表。

### GET /api/teacher/records/{record_id}

返回单条完整 `AssessmentRecord`（含结果与跟进记录）。

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
| 400 | `HTTP_ERROR` | 其他请求错误 |
| 503 | `POLICY_UNAVAILABLE` | 决策模型不可用或输出无效（对话不会退回规则提问） |

不向前端返回 Python traceback。

---

## 数据边界

- Session 与记忆库当前均为进程内存，重启清空，TTL 2 小时。
- 所有风险/评估结果均为**初步筛查提示**，不得表述为临床诊断或治疗建议。
- `session_id` 是会话定位符，不是身份认证或授权凭据。
- 不提交 `.env`、密钥、原始音视频或真实个人对话。
