# Phase 6 多智能体运行轨迹验证（真实模型）

> 由 `scripts/phase6_trace_real.py` 生成。

> 真模型：Safety / Router / Dialogue 为 `deepseek-flash`，Decision 为本地 Ollama `policy-qwen3-8b:latest`；`DIALOGUE_ENGINE=graph`、`AGENT_TRACE=on`。

> 场景 C 的视觉帧是**脚本预设的测试输入**，用与线上一致的 `VisionState` / `aggregate_frames` / `vision_segments` 结构注入，**不是实时摄像头采集，也不是真实人脸检测器的输出**。

> `trace` 只含节点级结论：没有提示词、模型推理文本、密钥或视觉原始数据。

## 场景 A：Dialogue 自主追问 -> Decision 跳过

预期：第 2 轮起 Dialogue 自己决定继续追问，面板显示「复用当前策略」

### 第 1 轮　学生：最近老是睡不好，躺下要很久才能睡着

- 回复：睡不好确实挺熬人的。
这种情况大概持续多久了？
- 气泡（2 条）：睡不好确实挺熬人的。 ｜ 这种情况大概持续多久了？
- 策略：`睡眠`　Safety：`continue`　耗时 8.42s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": false,
    "need_decision": true,
    "reason_code": "no_active_decision",
    "reason_label": "",
    "forced_reason": "no_active_decision",
    "forced_label": "还没有有效策略"
  },
  "decision": {
    "state": "ran",
    "called": true,
    "label": "本轮已调用决策模型",
    "strategy": "睡眠"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "missing_segment"
  },
  "output": {
    "bubbles": 2
  }
}
```

### 第 2 轮　学生：半夜还会醒一两次，早上起来特别累

- 回复：半夜还会醒，早上又缓不过来，这样白天挺难撑的吧。
那白天会犯困或者没精神到什么程度？
- 气泡（2 条）：半夜还会醒，早上又缓不过来，这样白天挺难撑的吧。 ｜ 那白天会犯困或者没精神到什么程度？
- 策略：`睡眠`　Safety：`continue`　耗时 3.25s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": true,
    "need_decision": false,
    "reason_code": "continue_topic",
    "reason_label": "当前话题还值得追问",
    "forced_reason": null,
    "forced_label": null
  },
  "decision": {
    "state": "skipped",
    "called": false,
    "label": "复用当前策略",
    "strategy": "睡眠"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "missing_segment"
  },
  "output": {
    "bubbles": 2
  }
}
```

### 第 3 轮　学生：白天上课就犯困，注意力也集中不了

- 回复：上课犯困、注意力跟不上，这样听讲确实挺吃力的。
除了困，你最近心情怎么样？
- 气泡（2 条）：上课犯困、注意力跟不上，这样听讲确实挺吃力的。 ｜ 除了困，你最近心情怎么样？
- 策略：`情绪`　Safety：`continue`　耗时 2.83s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": false,
    "need_decision": true,
    "reason_code": "topic_budget_exhausted",
    "reason_label": "",
    "forced_reason": "topic_budget_exhausted",
    "forced_label": "当前话题已问满两轮"
  },
  "decision": {
    "state": "ran",
    "called": true,
    "label": "本轮已调用决策模型",
    "strategy": "情绪"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "missing_segment"
  },
  "output": {
    "bubbles": 2
  }
}
```

### 第 4 轮　学生：有时候会想是不是自己太焦虑了

- 回复：会这样想，其实挺正常的，睡不好又累，人本来就容易烦躁。
你说的这种焦虑，是心里一直悬着放不下，还是偶尔冒出来一下？
- 气泡（2 条）：会这样想，其实挺正常的，睡不好又累，人本来就容易烦躁。 ｜ 你说的这种焦虑，是心里一直悬着放不下，还是偶尔冒出来一下？
- 策略：`情绪`　Safety：`continue`　耗时 4.12s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": true,
    "need_decision": true,
    "reason_code": "user_wants_change",
    "reason_label": "学生想换话题",
    "forced_reason": null,
    "forced_label": null
  },
  "decision": {
    "state": "ran",
    "called": true,
    "label": "本轮已调用决策模型",
    "strategy": "情绪"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "missing_segment"
  },
  "output": {
    "bubbles": 2
  }
}
```

## 场景 B：需要换话题 -> Decision 真实调用

预期：学生明确要求换方向时，Dialogue 请求新策略，面板显示「本轮已调用决策模型」

### 第 1 轮　学生：最近吃饭没什么胃口，也不太想吃东西

- 回复：吃饭没胃口确实挺难受的。
这种情况大概持续多久了？
- 气泡（2 条）：吃饭没胃口确实挺难受的。 ｜ 这种情况大概持续多久了？
- 策略：`食欲`　Safety：`continue`　耗时 1.93s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": false,
    "need_decision": true,
    "reason_code": "no_active_decision",
    "reason_label": "",
    "forced_reason": "no_active_decision",
    "forced_label": "还没有有效策略"
  },
  "decision": {
    "state": "ran",
    "called": true,
    "label": "本轮已调用决策模型",
    "strategy": "食欲"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "missing_segment"
  },
  "output": {
    "bubbles": 2
  }
}
```

### 第 2 轮　学生：体重好像掉了几斤

- 回复：体重有变化的话，大概掉了多少斤呢？
- 气泡（1 条）：体重有变化的话，大概掉了多少斤呢？
- 策略：`食欲`　Safety：`continue`　耗时 4.01s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": true,
    "need_decision": false,
    "reason_code": "continue_topic",
    "reason_label": "当前话题还值得追问",
    "forced_reason": null,
    "forced_label": null
  },
  "decision": {
    "state": "skipped",
    "called": false,
    "label": "复用当前策略",
    "strategy": "食欲"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "missing_segment"
  },
  "output": {
    "bubbles": 1
  }
}
```

### 第 3 轮　学生：这些先不聊了吧，我们换个话题好吗

- 回复：好呀，那我们就聊点别的。
最近有没有什么事让你心里挺不好受的？
- 气泡（2 条）：好呀，那我们就聊点别的。 ｜ 最近有没有什么事让你心里挺不好受的？
- 策略：`情绪`　Safety：`continue`　耗时 2.53s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": false,
    "need_decision": true,
    "reason_code": "topic_budget_exhausted",
    "reason_label": "",
    "forced_reason": "topic_budget_exhausted",
    "forced_label": "当前话题已问满两轮"
  },
  "decision": {
    "state": "ran",
    "called": true,
    "label": "本轮已调用决策模型",
    "strategy": "情绪"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "missing_segment"
  },
  "output": {
    "bubbles": 2
  }
}
```

### 第 4 轮　学生：我想说说和室友相处的事

- 回复：和室友相处的事，你愿意说说吗？
- 气泡（1 条）：和室友相处的事，你愿意说说吗？
- 策略：`情绪`　Safety：`continue`　耗时 3.53s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": true,
    "need_decision": true,
    "reason_code": "user_wants_change",
    "reason_label": "学生想换话题",
    "forced_reason": null,
    "forced_label": null
  },
  "decision": {
    "state": "ran",
    "called": true,
    "label": "本轮已调用决策模型",
    "strategy": "情绪"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "missing_segment"
  },
  "output": {
    "bubbles": 1
  }
}
```

## 场景 C：视觉关怀 -> 线索被采用

预期：预设视觉标签有效时，Dialogue 真的说出「你看起来……」

预设视觉标签（**测试输入，非实时摄像头**）：`{"emotion": "sad", "confidence": 0.92, "valence": -0.62}`

### 第 1 轮　学生：最近做什么都提不起劲

- 回复：你平时一般什么时候会觉得特别没劲，是白天多一些还是晚上？
- 气泡（1 条）：你平时一般什么时候会觉得特别没劲，是白天多一些还是晚上？
- 策略：`其它`　Safety：`continue`　耗时 2.42s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": false,
    "need_decision": true,
    "reason_code": "no_active_decision",
    "reason_label": "",
    "forced_reason": "no_active_decision",
    "forced_label": "还没有有效策略"
  },
  "decision": {
    "state": "ran",
    "called": true,
    "label": "本轮已调用决策模型",
    "strategy": "其它"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "cooldown"
  },
  "output": {
    "bubbles": 1
  }
}
```

### 第 2 轮　学生：以前喜欢打篮球，现在也不想去了

- 回复：篮球以前对你来说应该挺重要的吧，现在连这个都不想碰了。
是身体上觉得累，还是想到要去打球就没什么兴致了？
- 气泡（2 条）：篮球以前对你来说应该挺重要的吧，现在连这个都不想碰了。 ｜ 是身体上觉得累，还是想到要去打球就没什么兴致了？
- 策略：`兴趣`　Safety：`continue`　耗时 2.87s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": false,
    "need_decision": true,
    "reason_code": "no_active_topic",
    "reason_label": "",
    "forced_reason": "no_active_topic",
    "forced_label": "还没有当前话题"
  },
  "decision": {
    "state": "ran",
    "called": true,
    "label": "本轮已调用决策模型",
    "strategy": "兴趣"
  },
  "vision": {
    "state": "ran",
    "cue_valid": false,
    "channel": null,
    "channel_label": null,
    "cue": null,
    "spoken": false,
    "reason": "cooldown"
  },
  "output": {
    "bubbles": 2
  }
}
```

### 第 3 轮　学生：就是觉得很累，什么都不想做

- 回复：你看起来挺难过的，这种累可能不只是身体上的。
那除了篮球，以前还有什么事是你愿意做的，现在也完全不想碰了吗？
- 气泡（2 条）：你看起来挺难过的，这种累可能不只是身体上的。 ｜ 那除了篮球，以前还有什么事是你愿意做的，现在也完全不想碰了吗？
- 策略：`兴趣`　Safety：`continue`　耗时 3.35s

本轮 `trace`（面板就是照这个渲染的）：

```json
{
  "engine": "graph",
  "safety": {
    "placement": "pre_graph",
    "placement_label": "前置安全检查（LangGraph 之外）",
    "engine": "graph_safety_v1",
    "risk_level": "normal",
    "route": "continue",
    "model_status": "ok",
    "state": "ran",
    "outcome": "continue"
  },
  "dialogue": {
    "state": "ran",
    "routed": true,
    "need_decision": false,
    "reason_code": "continue_topic",
    "reason_label": "当前话题还值得追问",
    "forced_reason": null,
    "forced_label": null
  },
  "decision": {
    "state": "skipped",
    "called": false,
    "label": "复用当前策略",
    "strategy": "兴趣"
  },
  "vision": {
    "state": "ran",
    "cue_valid": true,
    "channel": "emotion",
    "channel_label": "表情名字",
    "cue": "难过",
    "spoken": true,
    "reason": "mentioned"
  },
  "output": {
    "bubbles": 2
  }
}
```
