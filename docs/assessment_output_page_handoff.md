# 评估结果页面交接文档

交接对象：负责结果页面展示的同学。本文只说明**当前已接通的接口与字段**，不要求改评估算法。联调以 `backend/models/evaluation.py`、`backend/models/responses.py` 和 `backend/api/assessment.py` 为准。

## 1. 页面要展示什么

评估完成后，页面拿到 `AssessmentResponse`。外层是 `session_id`、`status: "completed"`、`result`；页面主要读取 `result`。一份完整的虚构响应在 [assessment_response.json](examples/assessment_response.json)，可作为静态模拟数据。

建议按以下顺序展示：

1. 标题“本次心理状态初步筛查结果”、生成时间 `result.created_at`。
2. `result.concern_index`（0～100）及 `result.overall_level` 对应的中文关注等级。
3. `result.psychological_profile` 的五项分数，逐项标明名称和数值。**分数越高表示该方面越值得关注**，不是健康分。
4. 单独展示 `result.risk.risk_level` 风险提示。它与关注等级是两套结果，不能互相替代；`risk_score` 不是患病概率。
5. 如需给老师看，可展示非空的 `risk_reasons`、`risk_types`、`key_evidence` 和 `requires_intervention`；`key_evidence` 可能包含对话原文。

当前没有自动生成的总体说明、关键发现、趋势解读或个性化建议。仓库中的 `EvaluationOutput` 是预留的完整报告 Schema，**不是当前 `/api/assessment` 的响应**。页面不要从五维分数自行编造这些内容，也不要把“关注等级”写成抑郁症诊断等级。

## 2. 字段与展示文案

| JSON 路径 | 类型与范围 | 推荐显示 | 备注 |
| --- | --- | --- | --- |
| `result.result_id` | 字符串 | 不必直接展示 | 保存下来，供结果详情接口查询。 |
| `result.session_id` | UUID 字符串 | 不必直接展示 | 与响应外层 `session_id` 相同。 |
| `result.student_ref` | 字符串或 `null` | 不必直接展示 | 当前公开的创建会话接口不传学生标识，正常页面流程中通常为 `null`。 |
| `result.psychological_profile.emotion` | 0～100 整数 | 情绪状态 | 分数越高，相关信号越突出。 |
| `result.psychological_profile.interest_motivation` | 0～100 整数 | 兴趣与动力 | 同上。 |
| `result.psychological_profile.sleep_energy` | 0～100 整数 | 睡眠与精力 | 同上。 |
| `result.psychological_profile.attention_thinking` | 0～100 整数 | 专注与思考 | 同上。 |
| `result.psychological_profile.social_daily` | 0～100 整数 | 社交与日常功能 | 同上。 |
| `result.concern_index` | 0～100 整数 | 关注指数 | 由五维分数计算，不是患病概率。 |
| `result.overall_level` | 下表四个枚举之一 | 本次关注等级 | 由关注指数分档。 |
| `result.risk.risk_level` | `low` / `medium` / `high` | 风险提示：低 / 中 / 高 | 独立的规则式风险识别。 |
| `result.risk.risk_score` | 0～1 数值 | 可不展示 | 不是临床概率，也不要直接显示成“患病概率 50%”。 |
| `result.risk.risk_reasons` | 字符串数组 | 风险原因 | 空数组时不显示该区块。 |
| `result.risk.risk_types` | 字符串数组 | 风险类型 | 空数组时不显示该区块。 |
| `result.risk.key_evidence` | 字符串数组 | 关键依据 | 可能含对话原文；仅在需要的页面显示。 |
| `result.risk.requires_intervention` | 布尔值 | 需要人工关注标记 | `true` 时醒目标注，不要据此声称已有人处理。 |
| `result.assessment_method` | 固定为 `evaluation_agent` | 不必展示 | 技术字段。 |
| `result.created_at` | ISO 8601 时间 | 生成时间 | 可以按本地时区格式化。 |

关注等级使用以下映射，与 `evaluation_agent/scoring.py` 的展示文案一致：

| `overall_level` | `concern_index` | 中文展示 |
| --- | --- | --- |
| `low_concern` | 0～24 | 状态较平稳 |
| `mild_concern` | 25～49 | 可以留意 |
| `moderate_concern` | 50～74 | 建议关注 |
| `high_concern` | 75～100 | 建议重点关注 |

示例 JSON 的五维分数为 67、50、44、33、50。按当前公式计算，关注指数为 54，对应 `moderate_concern`。`risk_level: "medium"` 是另一条规则的输出，不能用它反推关注指数。

## 3. 页面如何取到结果

当前文字对话流程：

1. `POST /api/session`，无请求体，得到 `session_id`。
2. 每轮调用 `POST /api/chat`，请求体为 `{ "session_id": "...", "text": "..." }`。可选的 `vision_snapshot` 由上游负责与该句话对齐。响应中的 `reply` 是对话回复，`risk` 是**本轮**风险提示，不是最终评估结果。
3. 用户明确点击“生成初步结果”后，调用 `POST /api/assessment`，请求体最简单为 `{ "session_id": "..." }`。对话不会自动触发最终评估；至少需要一条已保存的消息。
4. 请求成功时显示 `response.result`，保存 `result_id` 和 `session_id`。再次取同一结果：`GET /api/assessment/result/{result_id}?session_id={session_id}`。该接口返回与第 3 步相同的外层结构。

上游多模态模块也可以在 `POST /api/assessment` 中提供完整的 `evaluation_input`（逐句对话与句级视觉快照、整段视觉汇总）。单纯上传摄像头帧不会自动把帧变成逐句快照或最终评估的视觉汇总；未接入对齐数据时，页面不要宣称结果已经综合了摄像头信息。

现有前端已经封装 `api.triggerAssessment(sessionId)`、`api.getResult(resultId, sessionId)`，并有 `AssessmentResultView` 组件。页面同学可以从这些现有入口继续做展示，不需要另造接口。

## 4. 加载、失败与历史记录

- 成功响应才有 `status: "completed"` 和 `result`；接口没有 `pending` 的评估结果对象。请求处理中由页面自行显示加载状态，并阻止重复触发。重复调用 `POST /api/assessment` 会生成另一条评估记录。
- 统一错误体形如 `{ "error": { "code": "...", "message": "..." } }`。常见错误：`404 SESSION_NOT_FOUND`（会话不存在或过期）、`404 RESULT_NOT_FOUND`（结果 ID 与会话不匹配或不存在）、`422 INVALID_EVALUATION_INPUT`（例如空会话）、`422 VALIDATION_ERROR`（请求字段不合法）、`503 EVALUATION_UNAVAILABLE`（评估模型配置缺失或不可用）。`POST /api/chat` 还可能返回 `503 POLICY_UNAVAILABLE`。
- `GET /api/history/{student_ref}` 返回 `{ "student_ref": "...", "records": [...], "total": 数字 }`。当前公开的创建会话接口不会指定 `student_ref`，记录暂以 `session_id` 为查询键；不同会话不会自动归到同一个学生名下。
- 会话与评估记录目前保存在后端进程内存里。会话有约 2 小时 TTL；后端重启后历史记录清空。不要把这一版页面做成依赖永久历史数据的流程。

## 5. 交接验收

- 用 [示例 JSON](examples/assessment_response.json) 能显示五维、关注指数、两套等级和生成时间；`student_ref: null`、空数组不显示成“null”或空白标签。
- 页面能区分对话接口的本轮 `risk` 与评估接口的最终 `result.risk`。
- 只传 `session_id` 即可触发有历史消息的文字评估；成功后可用 `result_id` 加 `session_id` 再次读取。
- `503`、`404`、`422` 时展示明确错误，不显示上一份结果为本次结果。
- 页面文案称“初步筛查”“关注提示”，不称“确诊”或“抑郁症严重程度”。演示数据只使用虚构对话。

接口详情见 [API 数据协议](api_spec.md)，字段源代码见 `backend/models/evaluation.py`、`backend/models/responses.py`、`backend/models/states.py`。
