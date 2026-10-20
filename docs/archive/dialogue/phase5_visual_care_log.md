# Phase 5 视觉关怀话术验证（真实模型 + 预设视觉标签）

> 历史记录：本文保留原日期、版本及验收结论，不代表当前代码重新验收。整理于 2026-10-18；返回[归档索引](../README.md)。

> 由 `scripts/phase5_visual_care.py` 生成。

> **视觉帧是脚本预设的测试输入**，用与线上一致的 `VisionState` / `aggregate_frames` / `vision_segments` 结构注入，**不是实时摄像头采集，也不是真实人脸检测器的输出**。这样做的目的是让「哪一轮给了什么线索」完全可控。

> 被验证的是**真模型**：Safety / Router / Dialogue 为 `deepseek-flash`，Decision 为本地 Ollama `policy-qwen3-8b:latest`；`DIALOGUE_ENGINE=graph`。


**本轮结果**：4 组预设场景共 20 轮，其中 **4 轮真的说出了外观关怀**。

### V1：悲伤（说得出口的情绪名字）

预期：走表情名字通道，说出“难过”这一类

预设视觉标签：`{"emotion": "sad", "confidence": 0.92, "valence": -0.62}`

| 轮 | 学生（模拟） | 本轮通道 | feedback.reason | 是否提到外观 | 模型调用 | 冷却标记 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 最近学习有点跟不上 | none | `cooldown` | 否 | 1 | None |
| 2 | 上课听不太进去，作业也拖着 | none | `cooldown` | 否 | 1 | None |
| 3 | 就是提不起劲，什么都不想做 | emotion | `mentioned` | **是** | 1 | 2 |
| 4 | 晚上躺床上会想很多 | none | `cooldown` | 否 | 1 | 2 |
| 5 | 白天又特别困 | none | `cooldown` | 否 | 1 | 2 |

**第 1 轮**　学生：最近学习有点跟不上

预设视觉标签：`{"emotion": "sad", "confidence": 0.92, "valence": -0.62}`　本轮通道：`none`　feedback：`cooldown`

1. 那最近是哪一科感觉最吃力呢？

模型原始返回：

```text
[首答]
那最近是哪一科感觉最吃力呢？
```

**第 2 轮**　学生：上课听不太进去，作业也拖着

预设视觉标签：`{"emotion": "sad", "confidence": 0.92, "valence": -0.62}`　本轮通道：`none`　feedback：`cooldown`

1. 听起来状态确实有点提不起劲。
2. 这种情况大概持续多久了？

模型原始返回：

```text
[首答]
听起来状态确实有点提不起劲。
这种情况大概持续多久了？
```

**第 3 轮**　学生：就是提不起劲，什么都不想做

预设视觉标签：`{"emotion": "sad", "confidence": 0.92, "valence": -0.62}`　本轮通道：`emotion`　feedback：`mentioned`

1. 你看起来挺难过的，这种提不起劲的感觉，大概是从什么时候开始的？

模型原始返回：

```text
[首答]
你看起来挺难过的，这种提不起劲的感觉，大概是从什么时候开始的？
```

**第 4 轮**　学生：晚上躺床上会想很多

预设视觉标签：`{"emotion": "sad", "confidence": 0.92, "valence": -0.62}`　本轮通道：`none`　feedback：`cooldown`

1. 晚上躺下的时候，脑子里一般都在想些什么呢？

模型原始返回：

```text
[首答]
晚上躺下的时候，脑子里一般都在想些什么呢？
```

**第 5 轮**　学生：白天又特别困

预设视觉标签：`{"emotion": "sad", "confidence": 0.92, "valence": -0.62}`　本轮通道：`none`　feedback：`cooldown`

1. 白天困成这样，晚上又睡不好，那平时白天有补觉或者打盹吗？

模型原始返回：

```text
[首答]
白天困成这样，晚上又睡不好，那平时白天有补觉或者打盹吗？
```

### V2：紧张（说得出口的情绪名字）

预期：走表情名字通道，说出“紧张”这一类

预设视觉标签：`{"emotion": "fearful", "confidence": 0.88, "valence": -0.5}`

| 轮 | 学生（模拟） | 本轮通道 | feedback.reason | 是否提到外观 | 模型调用 | 冷却标记 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 下周要上台答辩 | none | `cooldown` | 否 | 1 | None |
| 2 | 一想到就手心出汗 | none | `cooldown` | 否 | 1 | None |
| 3 | 晚上也睡不踏实 | emotion | `mentioned` | **是** | 1 | 2 |
| 4 | 怕自己讲砸了 | none | `cooldown` | 否 | 1 | 2 |
| 5 | 同学都比我准备得好 | none | `cooldown` | 否 | 1 | 2 |

**第 1 轮**　学生：下周要上台答辩

预设视觉标签：`{"emotion": "fearful", "confidence": 0.88, "valence": -0.5}`　本轮通道：`none`　feedback：`cooldown`

1. 上台答辩确实挺让人紧张的。
2. 准备得怎么样了？

模型原始返回：

```text
[首答]
上台答辩确实挺让人紧张的。
准备得怎么样了？
```

**第 2 轮**　学生：一想到就手心出汗

预设视觉标签：`{"emotion": "fearful", "confidence": 0.88, "valence": -0.5}`　本轮通道：`none`　feedback：`cooldown`

1. 这种身体上的紧张反应，很多人上台前都会有。
2. 一般是从什么时候开始有这种感觉的，是这几天准备的时候，还是更早？

模型原始返回：

```text
[首答]
这种身体上的紧张反应，很多人上台前都会有。
一般是从什么时候开始有这种感觉的，是这几天准备的时候，还是更早？
```

**第 3 轮**　学生：晚上也睡不踏实

预设视觉标签：`{"emotion": "fearful", "confidence": 0.88, "valence": -0.5}`　本轮通道：`emotion`　feedback：`mentioned`

1. 你看起来一直绷着，连晚上都松不下来。
2. 这种睡不踏实的情况，大概持续多久了？

模型原始返回：

```text
[首答]
你看起来一直绷着，连晚上都松不下来。
这种睡不踏实的情况，大概持续多久了？
```

**第 4 轮**　学生：怕自己讲砸了

预设视觉标签：`{"emotion": "fearful", "confidence": 0.88, "valence": -0.5}`　本轮通道：`none`　feedback：`cooldown`

1. 怕讲砸是很正常的，说明你在意这件事。
2. 那睡不踏实大概持续多久了，是这几天才开始的吗？

模型原始返回：

```text
[首答]
怕讲砸是很正常的，说明你在意这件事。
那睡不踏实大概持续多久了，是这几天才开始的吗？
```

**第 5 轮**　学生：同学都比我准备得好

预设视觉标签：`{"emotion": "fearful", "confidence": 0.88, "valence": -0.5}`　本轮通道：`none`　feedback：`cooldown`

1. 别人准备得怎么样，其实说明不了你的水平。
2. 睡眠这块我还有点想确认的，你是躺下半天睡不着，还是睡着了容易醒？

模型原始返回：

```text
[首答]
别人准备得怎么样，其实说明不了你的水平。
睡眠这块我还有点想确认的，你是躺下半天睡不着，还是睡着了容易醒？
```

### V3：疲惫/低落（说不出情绪名字，只有连续效价）

预期：走整体语气通道，说出“累/没精神”这一类

预设视觉标签：`{"emotion": "neutral", "confidence": 0.42, "valence": -0.38}`

| 轮 | 学生（模拟） | 本轮通道 | feedback.reason | 是否提到外观 | 模型调用 | 冷却标记 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 最近就是有点累 | none | `unsupported_emotion` | 否 | 1 | None |
| 2 | 睡得也一般 | none | `unsupported_emotion` | 否 | 1 | None |
| 3 | 白天老打瞌睡 | tone | `tone` | **是** | 1 | 2 |
| 4 | 没什么想做的事 | none | `unsupported_emotion` | 否 | 1 | 2 |
| 5 | 周末基本都在宿舍躺着 | none | `unsupported_emotion` | 否 | 1 | 2 |

**第 1 轮**　学生：最近就是有点累

预设视觉标签：`{"emotion": "neutral", "confidence": 0.42, "valence": -0.38}`　本轮通道：`none`　feedback：`unsupported_emotion`

1. 那平时是几点睡、几点起呢？

模型原始返回：

```text
[首答]
那平时是几点睡、几点起呢？
```

**第 2 轮**　学生：睡得也一般

预设视觉标签：`{"emotion": "neutral", "confidence": 0.42, "valence": -0.38}`　本轮通道：`none`　feedback：`unsupported_emotion`

1. 那一般能睡几个小时？
2. 中间会醒吗？

模型原始返回：

```text
[首答]
那一般能睡几个小时？
中间会醒吗？
```

**第 3 轮**　学生：白天老打瞌睡

预设视觉标签：`{"emotion": "neutral", "confidence": 0.42, "valence": -0.38}`　本轮通道：`tone`　feedback：`tone`

1. 白天打瞌睡确实挺影响状态的。你看起来也有点累，没什么精神。
2. 那这种白天犯困的情况，大概是从什么时候开始的？

模型原始返回：

```text
[首答]
白天打瞌睡确实挺影响状态的。你看起来也有点累，没什么精神。
那这种白天犯困的情况，大概是从什么时候开始的？
```

**第 4 轮**　学生：没什么想做的事

预设视觉标签：`{"emotion": "neutral", "confidence": 0.42, "valence": -0.38}`　本轮通道：`none`　feedback：`unsupported_emotion`

1. 那平时有没有什么以前喜欢做的事，现在也提不起劲了？

模型原始返回：

```text
[首答]
那平时有没有什么以前喜欢做的事，现在也提不起劲了？
```

**第 5 轮**　学生：周末基本都在宿舍躺着

预设视觉标签：`{"emotion": "neutral", "confidence": 0.42, "valence": -0.38}`　本轮通道：`none`　feedback：`unsupported_emotion`

1. 那躺着的时候，心里一般是什么感觉？

模型原始返回：

```text
[首答]
那躺着的时候，心里一般是什么感觉？
```

### V4：嘴上说还好、画面明显偏负（矛盾核对）

预期：走温和核对通道，试探地确认一次

预设视觉标签：`{"emotion": "neutral", "confidence": 0.4, "valence": -0.65}`

| 轮 | 学生（模拟） | 本轮通道 | feedback.reason | 是否提到外观 | 模型调用 | 冷却标记 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 我还好，没什么事 | none | `unsupported_emotion` | 否 | 1 | None |
| 2 | 真的挺好的，就是有点忙 | none | `unsupported_emotion` | 否 | 1 | None |
| 3 | 都挺正常的 | discordance | `discordance` | **是** | 1 | 2 |
| 4 | 不用担心我 | none | `unsupported_emotion` | 否 | 1 | 2 |
| 5 | 最近就是事情多了点 | none | `unsupported_emotion` | 否 | 1 | 2 |

**第 1 轮**　学生：我还好，没什么事

预设视觉标签：`{"emotion": "neutral", "confidence": 0.4, "valence": -0.65}`　本轮通道：`none`　feedback：`unsupported_emotion`

1. 好，那我们随便聊聊。你平时不上课的时候喜欢做点什么？

模型原始返回：

```text
[首答]
好，那我们随便聊聊。你平时不上课的时候喜欢做点什么？
```

**第 2 轮**　学生：真的挺好的，就是有点忙

预设视觉标签：`{"emotion": "neutral", "confidence": 0.4, "valence": -0.65}`　本轮通道：`none`　feedback：`unsupported_emotion`

1. 那忙起来的时候，一般都在忙些什么呀？

模型原始返回：

```text
[首答]
那忙起来的时候，一般都在忙些什么呀？
```

**第 3 轮**　学生：都挺正常的

预设视觉标签：`{"emotion": "neutral", "confidence": 0.4, "valence": -0.65}`　本轮通道：`discordance`　feedback：`discordance`

1. 你说都挺正常的，不过看你好像有点累，是这样吗？
2. 平时忙的那些事里，有没有哪件让你觉得心里挺沉的？

模型原始返回：

```text
[首答]
你说都挺正常的，不过看你好像有点累，是这样吗？
平时忙的那些事里，有没有哪件让你觉得心里挺沉的？
```

**第 4 轮**　学生：不用担心我

预设视觉标签：`{"emotion": "neutral", "confidence": 0.4, "valence": -0.65}`　本轮通道：`none`　feedback：`unsupported_emotion`

1. 好，那我们聊点轻松的。你平时有没有什么喜欢做的事，比如打游戏、听歌、看剧之类的？

模型原始返回：

```text
[首答]
好，那我们聊点轻松的。你平时有没有什么喜欢做的事，比如打游戏、听歌、看剧之类的？
```

**第 5 轮**　学生：最近就是事情多了点

预设视觉标签：`{"emotion": "neutral", "confidence": 0.4, "valence": -0.65}`　本轮通道：`none`　feedback：`unsupported_emotion`

1. 事情多的时候，晚上一般几点能睡下？

模型原始返回：

```text
[首答]
事情多的时候，晚上一般几点能睡下？
```

## 读法提醒

- `feedback.reason` 是后端给出的通道判定；`是否提到外观` 是按回复正文实测的，两者不一致就说明模型拿了线索却没说出来；
- `冷却标记`（`last_visual_observation_turn`）只在**真的说出口**之后才推进，所以「模型沉默」不会让后面四轮失去机会；
- `模型调用` 大于 1 表示命中了既有的重写兜底（重复 / 漏提外观 / 收尾仍提问），不是新增的独立调用；
- 条数与气泡由 Dialogue 自己决定，视觉话术只影响措辞，不改话题与策略。
