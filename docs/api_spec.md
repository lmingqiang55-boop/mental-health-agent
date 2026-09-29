# API：基础 Demo 与测评状态机原型

基础地址：`http://127.0.0.1:8000`。交互文档：`/docs`。本文只列**当前已实现**的接口；专业端所需接口列在文末“待设计”，不得当作已存在。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| POST | `/api/session` | 创建 Session，返回 `session_id` 和 `status`；HTTP 200 |
| GET | `/api/session/{session_id}` | 获取完整 Session 与历史 |
| DELETE | `/api/session/{session_id}` | 删除 Session |
| POST | `/api/chat` | 提交 `{ "session_id": "...", "text": "..." }` |
| POST | `/api/vision` | 提交 `session_id` 与 VisionState 字段 |
| POST | `/api/audio` | 提交 `session_id` 与 AudioState 字段 |
| POST | `/api/assessment` | 创建独立的九项测评会话，返回第一问 |
| POST | `/api/assessment/{session_id}/turn` | 提交测评回答并获得下一问及当前报告 |
| GET | `/api/assessment/{session_id}` | 查看测评状态与逐轮证据 |
| GET | `/api/assessment/{session_id}/report` | 查看逐项结果；未完成时总分为 `null` |
| DELETE | `/api/assessment/{session_id}` | 删除测评会话 |

## 对话式 PHQ-A 条目映射原型

这组新接口独立于旧的 `/api/chat` 六维 Demo。默认使用确定性规则 Mock，也可通过 `ASSESSMENT_EXTRACTOR=openai_compatible`、`ASSESSMENT_LLM_BASE_URL`、`ASSESSMENT_LLM_MODEL` 和可选的 `ASSESSMENT_LLM_API_KEY` 接入云端或本地模型。模型返回的结构化候选须经服务端证据校验；尚未用真实模型端到端验收，也未接前端。题目中文措辞是概念演示，不是已锁定的正式量表译文。规则依据见 [测评契约](assessment_contract.md)。

调用顺序：

1. `POST /api/assessment`（无请求体），取 `session_id` 与 `reply`（第一问）。
2. 逐轮 `POST /api/assessment/{session_id}/turn`，请求体为 `{ "text": "有几天" }`。响应含 `status`、`current_item_id`、`reply`、`report`。
3. `GET /api/assessment/{session_id}/report` 可随时查看已确认条目。九项齐全且状态为 `complete` 时 `mapped_total` 才是 0～27 的整数；否则为 `null`。
4. `GET /api/assessment/{session_id}` 返回逐轮记录和每题证据历史；`DELETE` 删除本进程内的会话。

状态允许 `in_progress`、`complete`、`stopped`、`safety_paused`。自伤相关信号使流程暂停，并返回支持信息；这不构成自动临床风险分级。已关闭会话再次提交回答返回 HTTP 409 和 `ASSESSMENT_CLOSED`。不存在的测评会话返回 HTTP 404 和 `ASSESSMENT_NOT_FOUND`。模型服务不可用或响应格式无效时返回 HTTP 503 和 `EXTRACTION_UNAVAILABLE`，本轮不写入会话，可以重试。测评会话目前也只保存在单个 Python 进程内。

## 会话与文字聊天

创建：`POST /api/session`，无请求体。响应示例：

```json
{"session_id":"b4fc1bdd-f906-43cc-8210-34333d18728b","status":"created"}
```

获取：`GET /api/session/{session_id}`，返回整个 `SessionState`。创建后 `turn_count=0`、`current_stage="exploration"`、六个 `assessment_state` 均为 `pending`，历史为空。`conversation_history` 中每条消息包括 `role`、`content`、`created_at`。删除：`DELETE /api/session/{session_id}`，成功返回 `{ "status": "deleted" }`。

聊天：`POST /api/chat`。

```json
{"session_id":"b4fc1bdd-f906-43cc-8210-34333d18728b","text":"最近总是觉得没什么精神"}
```

成功响应示例：

```json
{
  "session_id":"b4fc1bdd-f906-43cc-8210-34333d18728b",
  "reply":"最近心情整体怎么样？有没有觉得情绪比平时低落？",
  "next_strategy":"explore_mood",
  "current_stage":"exploration",
  "risk":{"risk_level":"low","risk_score":0.1,"risk_reasons":[],"requires_intervention":false},
  "turn_count":1
}
```

`reply` 是给学生显示的文本，`next_strategy` 是 A 的内部提问策略，C 不自行重新计算。策略集合：`explore_mood`、`explore_interest`、`explore_sleep`、`explore_energy`、`explore_concentration`、`explore_duration`、`clarify_answer`、`follow_up`、`finish_assessment`。`current_stage` 当前为 `exploration` 或 `completed`；评估维度状态为 `pending`、`in_progress`、`covered`。每次成功聊天会保存一条 user 和一条 assistant 消息，并使 `turn_count` 加 1。

`risk_level` 当前允许 `low`、`medium`、`high`。分值和原因来自演示规则，不能解读为临床概率或量表分数。`requires_intervention=true` 时前端应醒目显示支持信息，但实际人工转介流程尚未实现。

## Vision / Audio 状态接口

`POST /api/vision` 接收 `session_id` 加以下可选字段：`emotion`、`emotion_confidence`、`valence`、`arousal`、`engagement`、`face_detected`。示例：

```json
{"session_id":"b4fc1bdd-f906-43cc-8210-34333d18728b","emotion":"sad","emotion_confidence":0.8,"valence":-0.4,"arousal":0.3,"engagement":0.6,"face_detected":true}
```

`emotion_confidence`、`arousal`、`engagement` 范围为 0～1；`valence` 范围为 -1～1。响应包含 `session_id`、`status="updated"`、`vision_state`。当前不接收图像或视频文件，传入值由调用方提供，不代表后端已经完成识别。

`POST /api/audio` 接收 `session_id` 加可选字段：`text`、`speech_rate`、`pause_ratio`、`energy`、`pitch_mean`、`audio_available`。示例：

```json
{"session_id":"b4fc1bdd-f906-43cc-8210-34333d18728b","speech_rate":0.7,"pause_ratio":0.3,"energy":0.4,"pitch_mean":0.5,"audio_available":true}
```

`pause_ratio`、`energy` 范围为 0～1；`speech_rate`、`pitch_mean` 当前没有统一单位，B 在接入真实模型前必须定下单位和标准化方式。响应包含 `session_id`、`status="updated"`、`audio_state`。当前不接收录音文件，不提供语音转写或合成。

Vision/Audio 接口只覆盖该 Session 的最新状态；未提交时分别为 `null`。聊天在两个状态均为 `null` 时必须正常工作。

## 错误约定

不存在的 Session 返回 HTTP 404：

```json
{"error":{"code":"SESSION_NOT_FOUND","message":"Session does not exist."}}
```

请求字段无效或空白文本返回 HTTP 422：`error.code="VALIDATION_ERROR"`。错误统一使用 `{ "error": { "code": "...", "message": "..." } }`，不向前端返回 Python traceback。Session 数据仅保存在进程内存。

## 双前端接口边界

当前学生聊天页使用 `POST /api/session`、`POST /api/chat`；可以通过 `GET /api/session/{session_id}` 读取当前 Session。音视频接入通过同一 Session ID 写入结构化状态。`session_id` 只定位会话，不代表学生身份或专业人员查看权限。

**尚无专业端 API**，也没有账户、跨学生会话列表、评估结果、历史趋势、人工反馈、群体统计接口。医生/心理老师端的页面骨架只能使用合成数据。C 先在 [MVP 范围与双端规划](mvp_scope.md) 的数据契约基础上起草这些接口，A/B 审阅结果字段；确定身份、授权和同意流程后才实现跨用户读取。不要将现有 `GET /api/session/{session_id}` 作为专业端获取任意学生资料的正式接口。
