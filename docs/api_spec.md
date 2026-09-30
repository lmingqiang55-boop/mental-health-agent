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
| POST | `/api/vision/frame` | 提交单张摄像头帧，返回该帧提取的 VisionState |
| POST | `/api/audio` | 提交 `session_id` 与 AudioState 字段 |
| POST | `/api/assessment` | 创建独立的九项测评会话，返回第一问 |
| POST | `/api/assessment/{session_id}/turn` | 提交测评回答并获得下一问及当前报告 |
| GET | `/api/assessment/{session_id}` | 查看测评状态与逐轮证据 |
| GET | `/api/assessment/{session_id}/report` | 查看逐项结果；未完成时总分为 `null` |
| DELETE | `/api/assessment/{session_id}` | 删除测评会话 |

## 对话式 PHQ-A 条目映射原型

这组新接口独立于旧的 `/api/chat` Demo（后者已改为策略模型决策，见下节）。默认使用确定性规则 Mock，也可通过 `ASSESSMENT_EXTRACTOR=openai_compatible`、`ASSESSMENT_LLM_BASE_URL`、`ASSESSMENT_LLM_MODEL` 和可选的 `ASSESSMENT_LLM_API_KEY` 接入云端或本地模型。模型返回的结构化候选须经服务端证据校验；尚未用真实模型端到端验收，也未接前端。题目中文措辞是概念演示，不是已锁定的正式量表译文。规则依据见 [测评契约](assessment_contract.md)。

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
  "reply":"谢谢你愿意分享。还有什么最近的变化想补充吗？",
  "next_strategy":"情绪",
  "current_stage":"exploration",
  "risk":{"risk_level":"low","risk_score":0.0,"risk_reasons":[],"requires_intervention":false},
  "actions":["情绪"],
  "turn_count":1
}
```

`actions` 是后端给回复生成器（Response Agent）的下一步动作指令，按执行顺序排列，来自 `DialogueAction` 的 11 个取值：`其它`、`共情安慰`、`精神状态`、`睡眠`、`情绪`、`自杀倾向`、`躯体症状`、`食欲`、`社会功能`、`兴趣`、`筛查`。这些取值同时也是策略决策模型（Policy Model）系统提示中的动作词表，客户端只读取、不重新计算。`next_strategy` 是同一串动作用 `" -> "` 连接后的内部策略字符串（单个动作时与 `actions[0]` 相同），保留旧字段名只为兼容。

回复生成器尚未正式接入：当前 `reply` 固定使用 `follow_up` 临时占位文案，不随 `actions` 变化。决策模型只决定动作，不生成问句。

`POST /api/chat` 默认用 `POLICY_PROVIDER=mock`（固定返回 `情绪`）；改为 `POLICY_PROVIDER=http` 后，后端用完整对话历史调用位于 `POLICY_API_BASE_URL` 的 OpenAI 兼容 Policy API，请求固定 `temperature=0`、`max_tokens=64`，并只接受 `{"actions":[...]}` 形式的 JSON。

话题约束（`backend/policy/topic_constraint.py`）是动作的后处理：8 个核心话题（`精神状态`、`睡眠`、`情绪`、`自杀倾向`、`躯体症状`、`食欲`、`社会功能`、`兴趣`）各自最多被选中 3 次；同一话题第 4 次出现时优先改选从未出现过的话题，否则改选出现次数少于 3 的话题。改写后的那一项不再是动作名，而是转场指令字符串，例如 `当前话题从睡眠转到食欲`。因此 `actions` 中可能同时出现动作名和转场指令，前端不应假设它只含 11 个枚举值。当其余话题都达到上限时不再改写，原动作照常输出。计数是单个进程内的全局计数器，换 Session 时清零，不支持并行会话。

`current_stage` 当前为 `exploration` 或 `completed`；`assessment_state` 是旧规则状态机遗留的六维字段（`mood`、`interest`、`sleep`、`energy`、`concentration`、`duration`），`/api/chat` 不再更新它，新测评请用 `/api/assessment` 的九项状态。每次成功聊天会保存一条 user 和一条 assistant 消息，并使 `turn_count` 加 1。

`risk` 暂时保留为兼容字段；当前聊天不运行风险评分，也不依据这些字段中断对话。接口返回默认值（`low`、`0.0`、空原因、`false`），不代表实际风险判断。

## Vision / Audio 状态接口

`POST /api/vision` 接收 `session_id` 加以下可选字段：`emotion`、`emotion_confidence`、`valence`、`arousal`、`engagement`、`face_detected`。示例：

```json
{"session_id":"b4fc1bdd-f906-43cc-8210-34333d18728b","emotion":"sad","emotion_confidence":0.8,"valence":-0.4,"arousal":0.3,"engagement":0.6,"face_detected":true}
```

`emotion_confidence`、`arousal`、`engagement` 范围为 0～1；`valence` 范围为 -1～1。响应包含 `session_id`、`status="updated"`、`vision_state`。此 `/api/vision` 接口不接收图像或视频文件，传入值由调用方提供，不代表后端已经完成识别。

`POST /api/vision/frame` 接收 `{ "session_id": "...", "speech_segment_id": "可选的语音片段 ID", "image_base64": "..." }`。后续语音模块可在开始说话时生成 `speech_segment_id`，采集的帧携带同一个 ID；接口原样返回该 ID 供调用方关联，不执行语音检测。`image_base64` 可为 JPEG/PNG 的纯 Base64 或对应的 `data:image/...;base64,...` URL；解码后最多 1920×1080 像素。响应只返回结构化 `VisionState`、Session ID、状态和可选的语音片段 ID，原始帧不写入 Session 或磁盘。每帧是完整快照：未检测到人脸时 `face_detected=false`，其余视觉指标为 `null`，覆盖上一帧结果。无效图片返回 HTTP 422 `INVALID_FRAME`；模型未安装或不可用时返回 HTTP 503 `VISION_UNAVAILABLE`。默认 `VISION_PROVIDER=mock` 不推断面部状态；安装可选视觉依赖并设置 `VISION_PROVIDER=emotiefflib` 后启用真实模型。单帧只输出表情类别、置信度、效价和唤醒度，不输出参与度或眼动指标。

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
