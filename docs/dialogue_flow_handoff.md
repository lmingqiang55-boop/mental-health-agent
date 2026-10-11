# 对话修复与独立前端接线（2026-10-11）

## 摄像头表述

开启摄像头预览不代表后端已收到真实识别结果。先读取 `GET /api/vision/status`，
`provider=mock` 时不会生成表情观察。真实识别使用 `.env` 中的
`VISION_PROVIDER=emotiefflib`；已有 `.env` 不会随 Git 更新。
也可以用 `python scripts/start_dev.py --vision-provider emotiefflib` 明确启动。
真实模型依赖或权重缺失时接口返回错误，不自动生成模拟情绪。

独立前端必须完成以下接线：

1. 开启摄像头后调用 `/api/vision/capture`（采集 ID、递增 generation、active）。
2. 定期上传 `/api/vision/frame`，包含真实图片、`frame_id`、`capture_id`、
   `captured_at_ms`。时间字段使用同一客户端的单调毫秒时钟。
3. 发送文字或录音前调用 `/api/vision/segment`，包含唯一 `utterance_id` 和发言区间。
4. 将返回的 `vision_snapshot` 连同同一个 `utterance_id` 原样传给 `/api/chat`。
   录音同时传 `speech`。仅提交 `/api/vision` 或聊天文字不会形成可信帧证据。

为避免“没有触发但不知道原因”，每轮聊天返回 `visual_feedback`：

| reason | 含义 |
| --- | --- |
| `mentioned` | 生成回复已提及外观观察 |
| `cooldown` | 尚未到约四轮一次的允许时机 |
| `missing_segment` | 没有发言 ID 或未冻结对应区间 |
| `capture_inactive` | 摄像头已经关闭或换代 |
| `snapshot_mismatch` | 聊天快照与冻结结果不一致 |
| `no_frames` / `too_few_frames` | 近期没有画面或不足三帧 |
| `unverified_source` | 模拟帧或来源未验证 |
| `stale_frames` | 最近画面距发送超过 2.5 秒 |
| `no_face` | 可靠窗口内有效人脸不足 |
| `unsupported_emotion` | 主要情绪不在四类范围内 |
| `low_confidence` / `unstable_emotion` | 置信分数不足或多帧结果不稳定 |
| `generation_omitted` | 提供了线索，但生成器改写后仍未提及 |
| `crisis` / `closing` | 危机支持或本轮收尾不插入视觉观察 |

仅最近 5 秒、同一仍然开启的摄像头的真实帧可用于口头观察；至少三帧、
至少 70% 有效人脸、至少 70% 帧属于同一支持类别且置信分数不低于 0.8。
这些是原型筛选参数，未做真人校准。不会为凑次数降低门槛。
四类口头用语对应 happy→开心、sad→难过、fearful→紧张、angry→烦躁，
只是外观线索的表达，尤其“紧张/烦躁”不是直接测量真实内心状态。

最近窗口在冻结区间时一并冻结，失败重试不会吸收迟到画面；
最终评估仍只用原发言区间的快照，不混入前面几秒的画面。
替换 B 的检测器时继承 `VisionDetector`；真实实现的 `is_simulated=False`，
模拟实现必须声明 `True`。来源记录在每帧上，不再仅检查 EmotiEffLib 类名。

## 承接与重复

对话生成器不再被要求每次先复述再提问。短回答直接推进；明确痛苦或话题转换时才
做简短必要回应。生成后检查近期主问题的文字相似度，以及连续套用同一开头；
命中时保持话题不变、请求改写一次。此检查不能证明语义完全不重复，仍需真人对话验收。

## 停止对话与显示按钮

`/api/chat` 返回示例（省略其他原有字段）：

```json
{
  "current_stage": "assessment_ready",
  "assessment_ready": true,
  "completion_reason": "topic_coverage",
  "next_strategy": "结束本次筛查",
  "reply": "谢谢你愿意分享，我们这次先聊到这里。可以生成本次对话的初步结果。"
}
```

独立前端收到 `assessment_ready=true` 后应：保留收尾回复、停止输入和录音、
关闭摄像头、显示“生成结果”按钮。按钮点击 `POST /api/assessment`
（请求体 `{"session_id":"..."}`）；评估失败仍保留收尾状态并允许再次生成。
不要根据聊天回合数显示“PHQ-9 第 n/9 题”，此对话不是九道固定量表题。

`screening_progress` 包含 `topic_turns`、`pending_topic`、`end_reason`。
计数只表示对应话题下的交流，不等于回答有效或信息完整。
普通话题包含情绪、兴趣、睡眠、精神状态、食欲、社会功能、躯体症状、自杀倾向。
训练模型继续选择动作；话题到两次交流后控制器转向尚未覆盖的话题。
主要话题都交流过且至少十轮时收尾，二十轮为总上限。
`completion_reason=turn_limit` 表示到达上限，报告只依据已聊内容；
`user_requested` 表示用户主动停止。所有参数均为演示交互设置，不是临床规范。

重复原 `utterance_id` 的成功请求仍幂等返回原结果；收尾后新普通输入返回
409 `SCREENING_FINISHED`。新危机表述会优先进入危机支持，不被上限拦截。
这些新增字段需独立前端接入才能改变截图中的按钮和输入状态。
