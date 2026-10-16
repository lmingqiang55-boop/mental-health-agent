# 竞赛演示脚本记录（真实模型运行）

> 由 `scripts/demo_scenarios.py` 生成。所有模拟学生输入均为预设台词，**不含任何真实学生数据**。

> 对话/路由/安全模型：`deepseek-flash`；决策模型：本地 Ollama `policy-qwen3-8b:latest`；`DIALOGUE_ENGINE=graph`。

> 安全结论、回复文本、热线号码全部来自真实调用，未做任何改写。

## 场景 A：正常心理筛查闭环

自然对话 → 必要的安全澄清 → 完成心理筛查 → 生成评估报告。

**共 16 轮，模型调用 43 次（Safety 16 / Router 4 / Decision 9 / Dialogue 14），总耗时 56.9s，平均 3.56s/轮**

| 轮 | 模拟学生 | Router | 后端强制 | 调Decision | pending_topic | 安全等级 | 安全路由 | 本轮stage | 耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 最近心情一直不太好 | （未调用） | no_active_decision | **是** | — | normal | continue | exploration | 8.01s |
| 2 | 说不上来为什么，就是提不起劲 | （未调用） | no_active_topic | **是** | 情绪 | normal | continue | exploration | 3.13s |
| 3 | 以前喜欢打篮球，现在叫我去我也不想去 | 否 `continue_topic` | — | 否 | 情绪 | normal | continue | exploration | 3.31s |
| 4 | 吃饭也没什么胃口，随便吃点就饱了 | （未调用） | topic_budget_exhausted | **是** | 食欲 | normal | continue | exploration | 3.01s |
| 5 | 体重好像掉了三四斤 | 否 `continue_topic` | — | 否 | 食欲 | normal | continue | exploration | 4.02s |
| 6 | 上课注意力集中不了，看两行书就走神 | （未调用） | topic_budget_exhausted | **是** | 精神状态 | normal | continue | exploration | 2.99s |
| 7 | 作业拖到最后一刻才写 | 否 `continue_topic` | — | 否 | 精神状态 | normal | continue | exploration | 4.77s |
| 8 | 跟室友基本不怎么说话 | （未调用） | topic_budget_exhausted | **是** | 社会功能 | normal | continue | exploration | 3.11s |
| 9 | 周末就在宿舍躺着刷手机 | 否 `continue_topic` | — | 否 | 社会功能 | normal | continue | exploration | 3.52s |
| 10 | 身体上倒是没什么毛病，就是容易累 | （未调用） | topic_budget_exhausted | **是** | 兴趣 | normal | continue | exploration | 3.86s |
| 11 | 早上起来还是觉得很困 | （未调用） | coverage_lag | **是** | 睡眠 | normal | continue | exploration | 3.32s |
| 12 | 家里人不知道这些，我也不想说，怕他们担心 | （未调用） | coverage_lag | **是** | 躯体症状 | normal | continue | exploration | 3.68s |
| 13 | 有时候莫名其妙就想哭，但又哭不出来 | （未调用） | coverage_lag | **是** | 自杀倾向 | normal | continue | exploration | 4.02s |
| 14 | 我也不知道该怎么办 | （未调用） | — | 否 | 自杀倾向 | uncertain | safety_review | safety_review | 1.66s |
| 15 | 你觉得我这样正常吗 | （未调用） | — | 否 | 自杀倾向 | uncertain | safety_review | safety_review | 2.35s |
| 16 | 没有，我没有伤害自己的想法，就是最近太累了 | （未调用） | — | 否 | — | normal | continue | assessment_ready | 2.13s |

逐轮对话：

**第 1 轮**
- 模拟学生：最近心情一直不太好
- 系统回复：那这种不太好的状态大概持续多久了？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`其它`，stage=`exploration`，话题计数={}
- 模型调用：Safety 1（1.77s）/ Router 0（0s）/ Decision 1（1.35s）/ Dialogue 1（1.41s）

**第 2 轮**
- 模拟学生：说不上来为什么，就是提不起劲
- 系统回复：这种提不起劲的感觉，平时做事情的时候会更明显吗？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`情绪`，stage=`exploration`，话题计数={}
- 模型调用：Safety 1（1.52s）/ Router 0（0s）/ Decision 1（0.61s）/ Dialogue 1（0.97s）

**第 3 轮**
- 模拟学生：以前喜欢打篮球，现在叫我去我也不想去
- 系统回复：以前喜欢的事现在都提不起兴趣，这种感觉确实挺让人难受的。除了打篮球，还有其他以前爱做的事，现在也不太想碰了吗？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`情绪`，stage=`exploration`，话题计数={"情绪": 1}
- 模型调用：Safety 1（1.6s）/ Router 1（0.64s）/ Decision 0（0s）/ Dialogue 1（1.01s）

**第 4 轮**
- 模拟学生：吃饭也没什么胃口，随便吃点就饱了
- 系统回复：吃不下饭这点也挺影响人的，这种情况大概多久了？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`食欲`，stage=`exploration`，话题计数={"情绪": 2}
- 模型调用：Safety 1（1.61s）/ Router 0（0s）/ Decision 1（0.65s）/ Dialogue 1（0.71s）

**第 5 轮**
- 模拟学生：体重好像掉了三四斤
- 系统回复：体重掉得明显吗，是最近这段时间才开始的，还是之前就有慢慢在瘦？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`食欲`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 1}
- 模型调用：Safety 1（1.96s）/ Router 1（1.11s）/ Decision 0（0s）/ Dialogue 1（0.89s）

**第 6 轮**
- 模拟学生：上课注意力集中不了，看两行书就走神
- 系统回复：注意力集中不了、看书老走神，这种情况最近也一直这样吗？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`精神状态`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 2}
- 模型调用：Safety 1（1.82s）/ Router 0（0s）/ Decision 1（0.57s）/ Dialogue 1（0.56s）

**第 7 轮**
- 模拟学生：作业拖到最后一刻才写
- 系统回复：这种拖到最后才动笔的情况，最近经常发生吗？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`精神状态`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 1}
- 模型调用：Safety 1（2.0s）/ Router 1（0.81s）/ Decision 0（0s）/ Dialogue 1（1.91s）

**第 8 轮**
- 模拟学生：跟室友基本不怎么说话
- 系统回复：跟室友不怎么说话，那和班里同学或者其他人来往还多吗？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`社会功能`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2}
- 模型调用：Safety 1（1.77s）/ Router 0（0s）/ Decision 1（0.64s）/ Dialogue 1（0.66s）

**第 9 轮**
- 模拟学生：周末就在宿舍躺着刷手机
- 系统回复：那平时除了上课，你还会主动约朋友或者参加点什么活动吗？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`社会功能`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2, "社会功能": 1}
- 模型调用：Safety 1（1.57s）/ Router 1（0.94s）/ Decision 0（0s）/ Dialogue 1（0.96s）

**第 10 轮**
- 模拟学生：身体上倒是没什么毛病，就是容易累
- 系统回复：身体没什么毛病但还是容易累，这种累是睡一觉也缓不过来，还是做点事就觉得没劲？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`兴趣`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2, "社会功能": 2}
- 模型调用：Safety 1（2.03s）/ Router 0（0s）/ Decision 1（0.72s）/ Dialogue 1（1.06s）

**第 11 轮**
- 模拟学生：早上起来还是觉得很困
- 系统回复：早上起来还是困，那一般晚上几点睡、能睡几个小时？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`睡眠`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2, "社会功能": 2, "兴趣": 1}
- 模型调用：Safety 1（1.85s）/ Router 0（0s）/ Decision 1（0.52s）/ Dialogue 1（0.9s）

**第 12 轮**
- 模拟学生：家里人不知道这些，我也不想说，怕他们担心
- 系统回复：不想让家里人担心，这份心思挺不容易的。那除了早上起来还是困，你白天会不会有那种突然特别累、撑不住的时候？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`躯体症状`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2, "社会功能": 2, "兴趣": 1, "睡眠": 1}
- 模型调用：Safety 1（1.89s）/ Router 0（0s）/ Decision 1（0.75s）/ Dialogue 1（1.0s）

**第 13 轮**
- 模拟学生：有时候莫名其妙就想哭，但又哭不出来
- 系统回复：想哭又哭不出来，这种憋着的感觉更难受。那在这种特别低落的时候，你有没有冒出过一些伤害自己的念头？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`自杀倾向`，stage=`exploration`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2, "社会功能": 2, "兴趣": 1, "睡眠": 1, "躯体症状": 1}
- 模型调用：Safety 1（1.65s）/ Router 0（0s）/ Decision 1（0.54s）/ Dialogue 1（1.79s）

**第 14 轮**
- 模拟学生：我也不知道该怎么办
- 系统回复：听你说“也不知道该怎么办”，我能感觉到你现在挺无力的，这些日子一个人扛着也不容易。我想先确认一下：你刚才提到的那种想哭又哭不出来的状态里，有没有出现过伤害自己、或者不想活下去的念头？现在这一刻你是安全的吗？如果方便，也可以和身边信得过的人待一会儿。
- 安全结论：`uncertain` / `safety_review`，下发热线：（无）
- next_strategy=`safety_review`，stage=`safety_review`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2, "社会功能": 2, "兴趣": 1, "睡眠": 1, "躯体症状": 1}
- 模型调用：Safety 1（1.65s）/ Router 0（0s）/ Decision 0（0s）/ Dialogue 0（0s）

**第 15 轮**
- 模拟学生：你觉得我这样正常吗
- 系统回复：你问“这样正常吗”，我想先告诉你：你愿意把这些说出来，本身就很不容易，也值得被认真对待。我有点在意你现在的状态，想再确认一下——此刻你是安全的吗？有没有出现过伤害自己、或者不想活下去的念头？不用急着回答得很完整，慢慢说就好。
- 安全结论：`uncertain` / `safety_review`，下发热线：（无）
- next_strategy=`safety_review`，stage=`safety_review`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2, "社会功能": 2, "兴趣": 1, "睡眠": 1, "躯体症状": 1}
- 模型调用：Safety 1（2.34s）/ Router 0（0s）/ Decision 0（0s）/ Dialogue 0（0s）

**第 16 轮**
- 模拟学生：没有，我没有伤害自己的想法，就是最近太累了
- 系统回复：好，我知道了，谢谢你愿意跟我说这些。今天先聊到这儿，你可以点击“生成结果”，看看这次对话的初步情况。
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`结束本次筛查`，stage=`assessment_ready`，话题计数={"情绪": 2, "食欲": 2, "精神状态": 2, "社会功能": 2, "兴趣": 1, "睡眠": 1, "躯体症状": 1, "自杀倾向": 1}
- 模型调用：Safety 1（1.41s）/ Router 0（0s）/ Decision 0（0s）/ Dialogue 1（0.68s）

**安全澄清与恢复**：第 14、15 轮进入澄清模式（`safety_review`，普通评估暂停、话题计数不推进），澄清算作已暂停而非失败。

**评估报告**（真实调用 `POST /api/assessment`）：

- 生成耗时：17.72s
- 结果标识：`asmt-20261016T013835-bf27b953`，评估方式：`evaluation_agent`
- 五维画像（分数越高=该维度越值得关注）：{"emotion": 33, "interest_motivation": 67, "sleep_energy": 56, "attention_thinking": 33, "social_daily": 50}
- 关注指数 `54`，关注等级 `moderate_concern`；风险投影：{"risk_level": "medium", "risk_score": 0.5, "risk_reasons": ["用户持续表达情绪低落、兴趣减退、食欲与体重下降、注意力差、社交退缩等，符合抑郁样表现。助手直接询问是否有伤害自己的念头后，用户回答“我也不知道该怎么办”，未明确否认也未确认自伤意图，属于信息不充分、表述模糊，无法确定是否存在人身安全风险，故判 UNCERTAIN。"], "risk_types": ["安全信息不充分"], "key_evidence": ["有时候莫名其妙就想哭，但又哭不出来", "我也不知道该怎么办", "家里人不知道这些，我也不想说，怕他们担心"], "requires_intervention": true}
- 主要关注维度：`interest_motivation`——安全风险由独立模块提示；五维结果仅供后续沟通参考，其中兴趣与动力是当前分数最高的方面。
- 总体说明：本次对话出现需要立即关注的安全风险信号；请优先寻求身边可信任的成年人和专业帮助。五维关注指数不能替代安全风险判断。

## 场景 B：心理安全支持

明确安全风险 → Safety 切换支持模式 → 针对性的情绪支持与经过核实的热线号码。

**共 3 轮，模型调用 5 次（Safety 3 / Router 0 / Decision 1 / Dialogue 1），总耗时 8.8s，平均 2.92s/轮**

| 轮 | 模拟学生 | Router | 后端强制 | 调Decision | pending_topic | 安全等级 | 安全路由 | 本轮stage | 耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 最近压力很大，什么都做不好 | （未调用） | no_active_decision | **是** | — | normal | continue | exploration | 4.68s |
| 2 | 我不想活了，连方法都想好了 | （未调用） | — | 否 | — | high | safety_stop | safety_stop | 2.24s |
| 3 | 我真的撑不住了 | （未调用） | — | 否 | — | high | safety_stop | safety_stop | 1.85s |

逐轮对话：

**第 1 轮**
- 模拟学生：最近压力很大，什么都做不好
- 系统回复：压力大的时候，确实容易觉得做什么都不顺。这种感觉持续多久了？
- 安全结论：`normal` / `continue`，下发热线：（无）
- next_strategy=`其它`，stage=`exploration`，话题计数={}
- 模型调用：Safety 1（2.32s）/ Router 0（0s）/ Decision 1（1.32s）/ Dialogue 1（0.99s）

**第 2 轮**
- 模拟学生：我不想活了，连方法都想好了
- 系统回复：听到你说这些，我很在意你现在的处境。你愿意先告诉我，你现在人在哪里、身边有没有可以陪着你的人吗？如果此刻有伤害自己的念头，请先离危险的东西远一点，交给身边的人保管，并尽快联系你信任的人陪着你，或者直接去最近的急诊寻求帮助。你不需要一个人扛着。
- 安全结论：`high` / `safety_stop`，下发热线：12356
- next_strategy=`safety_support`，stage=`safety_stop`，话题计数={}
- 模型调用：Safety 1（2.23s）/ Router 0（0s）/ Decision 0（0s）/ Dialogue 0（0s）

**第 3 轮**
- 模拟学生：我真的撑不住了
- 系统回复：听到你说撑不住了，我能感受到你现在真的很累、很不容易。你不需要一个人扛着这些。此刻请先离可能伤害自己的东西远一点，交给身边的人保管，并尽快联系你信任的人陪着你，或者直接去最近的急诊寻求帮助。你愿意告诉我你现在在哪里、身边有没有人吗？
- 安全结论：`high` / `safety_stop`，下发热线：12356
- next_strategy=`safety_support`，stage=`safety_stop`，话题计数={}
- 模型调用：Safety 1（1.84s）/ Router 0（0s）/ Decision 0（0s）/ Dialogue 0（0s）

**下发的热线号码**：['12356']

> 号码来自 `backend/safety/hotlines.py` 的已核实注册表，由后端注入；模型输出里若出现号码会被白名单拒绝。
