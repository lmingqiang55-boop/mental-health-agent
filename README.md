# 多模态心理状态筛查 Agent

系统由对话决策、队员 B 的语音与视觉处理、心理状态评估和展示页面组成。对话下一步动作由已训练的决策模型选择；最终评估由 `evaluation_agent/` 处理，输出五维心理状态画像、关注指数和关注等级。危机风险识别独立运行。

> **当前仅适合演示与使用虚构数据。** 面向真实中小学生开放前，需完成身份与权限控制、同意流程、危机识别和人工响应、持久化与恢复、年龄适配和效度验证。详见 [2026-10-01 上线前审查](docs/prelaunch_audit_2026-10-01.md)。评估提示词已同步至 `PROMPT_VERSION=1.2`，但这不等于系统已完成临床验证。

当前前端支持文字输入和摄像头帧采样。队员 B 的自动语音切分与 ASR 尚未接入，以下接口已为它预留。原来的六维规则评估引擎已移除。[三人协作规划 v3](docs/三人协作与接口分工_v3.md)保留在 `docs/`；实际请求与响应以本文件及 [API 数据协议](docs/api_spec.md) 为准。

## 队员 B 需要交付什么

队员 B 在自己的模块内完成语音起止检测、ASR、摄像头采样，以及**每句话和视觉状态的时间对齐**。后端评估接口只接收已经对齐的结构，不用帧时间戳重新推断对应关系。

| 时机 | 队员 B 的输出 | 提交位置 |
| --- | --- | --- |
| 用户说完一句话 | ASR 原文 `text`，必填且非空 | `POST /api/chat` 的 `text` |
| 同一句话 | 该句期间聚合的视觉状态 `vision_snapshot`，有数据时提供 | 同一个 `/api/chat` 请求，后续也放在 `evaluation_input.dialogue_history` 的对应消息内 |
| 整段对话结束 | 基于句级视觉状态计算的 `vision_summary` | `POST /api/assessment` 的 `evaluation_input.vision_summary` |
| 触发最终评估 | 按时间顺序排列的完整 `dialogue_history` | `POST /api/assessment` 的 `evaluation_input.dialogue_history` |

所有请求使用同一个 `session_id`。`dialogue_history` 的 `role` 可为 `user`、`assistant`、`counselor`、`system`；只有 `user` 的话是被评估者自述，其他角色仅作上下文。每条消息的 `vision_snapshot` 必须对应**这条消息**，不能用最近一帧代替。没有采集到视觉时省略快照；缺测值用 `null`，不要填 `0`。语音模块只提供转写文本，不需要提交音频特征。

### 1. 每句话的语音与视觉输出

语音模块至少给出 ASR 原文。视觉模块对这句话的起止区间进行采样和聚合，然后与文本一起提交：

```http
POST /api/chat
Content-Type: application/json
```

```json
{
  "session_id": "会话 ID",
  "text": "最近总是睡不好",
  "vision_snapshot": {
    "face_detected": true,
    "emotion": "sad",
    "emotion_confidence": 0.82,
    "valence": -0.4,
    "arousal": 0.35,
    "engagement": 0.7,
    "attention_score": 0.6,
    "gaze_focus": 0.55,
    "micro_expression_intensity": 0.3
  }
}
```

`text` 是参与对话决策和最终评估的转写文本。`vision_snapshot` 可省略。现有 `POST /api/vision` 和 `POST /api/vision/frame` 仍可供实时状态更新，但帧采样日志不会自动变成某句话的快照，也不会自动生成最终评估的视觉汇总。

句级 `vision_snapshot` 使用 `VisionState`：`emotion` 为可选字符串；`emotion_confidence`、`arousal`、`engagement`、`attention_score`、`gaze_focus`、`micro_expression_intensity` 为可选的 0～1 数值；`valence` 为可选的 -1～1 数值；`face_detected` 为布尔值；`timestamp` 可选，使用 ISO 8601 时间。具体定义见 [`backend/models/states.py`](backend/models/states.py)。

### 2. 整段对话的视觉输出与评估交接

队员 B 把完整对话按顺序交给评估端。每条有视觉数据的消息都带自己的 `vision_snapshot`；整段统计单独放在顶层 `vision_summary`：

```http
POST /api/assessment
Content-Type: application/json
```

```json
{
  "session_id": "会话 ID",
  "evaluation_input": {
    "dialogue_history": [
      {
        "role": "user",
        "content": "最近总是睡不好",
        "vision_snapshot": {
          "face_detected": true,
          "emotion": "sad",
          "valence": -0.4
        }
      },
      {
        "role": "assistant",
        "content": "最近是入睡困难，还是容易醒？"
      }
    ],
    "vision_summary": {
      "dominant_emotion": "sad",
      "mean_valence": -0.4,
      "mean_arousal": 0.35,
      "mean_engagement": 0.7,
      "mean_attention": 0.6,
      "valence_trend": [-0.4],
      "face_present_ratio": 1.0,
      "sample_count": 1
    }
  }
}
```

`dialogue_history` 至少一条消息，每条 `content` 必须非空。`vision_summary` 的均值和 `face_present_ratio` 范围分别为 -1～1 或 0～1；`valence_trend` 按**句级样本**的时间顺序排列；`sample_count` 是参与汇总的句级样本数，不是摄像头帧数。没有视觉能力时省略 `vision_snapshot` 和 `vision_summary`，不要构造全零汇总。`evaluation_input.user_memory` 可选，用于长期背景信息。

语音模块尚未接通时，现有文字界面仍可只提交 `{ "session_id": "会话 ID" }`。后端会使用会话内已保存的文本和准确附着在消息上的快照；缺失的视觉数据保持缺失。评估服务把对话原文和结构化视觉状态发送到配置的 DeepSeek 接口，不发送原始音频或图像。返回的当前结果是五维画像、0～100 关注指数、关注等级和独立风险结果；报告文案、趋势说明与个性化建议尚未实现。

## 本地运行

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.main:app --reload
```

在本地 `.env` 填写真实 `DEEPSEEK_API_KEY`，用于综合评估；不要提交 `.env`。对话动作还需要启动已训练的决策模型服务，并在 `.env` 设置 `POLICY_API_BASE_URL` 等参数。评估 Agent 的 `DEEPSEEK_API_STYLE`、`DEEPSEEK_MAX_OUTPUT_TOKENS`、`DEEPSEEK_TIMEOUT_SECONDS` 等配置见 `.env.example`。缺少密钥或模型服务不可用时，评估接口返回 `503 EVALUATION_UNAVAILABLE`，不会回退到旧六维规则。

前端运行：

```powershell
Set-Location frontend
npm ci
npm run dev
```

后端接口详情见 [API 数据协议](docs/api_spec.md)，当前模块关系见 [架构说明](docs/architecture.md)。
