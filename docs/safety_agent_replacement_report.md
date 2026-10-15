# 新版 LLM Safety Agent 替换旧对话安全机制 —— 最终报告

范围：用新版 `backend/safety/` 彻底替换旧对话 Safety 机制，并在**全部入口**生效后
才删除旧代码。LangGraph **未使用**（仓库未安装、也不在 `requirements.txt`），
新 Safety 是纯 Python + DeepSeek 的独立实现。

---

## 0. 结论速览

| 项目 | 结果 |
| --- | --- |
| 全量测试 `pytest tests evaluation_agent` | **840 passed, 0 failed**（基线 **808 passed**） |
| 前端类型检查 `vue-tsc -b --force` | student **exit 0**、admin **exit 0** |
| 实机端到端（真实 DeepSeek + 真实 `/api/chat`） | 两种部署形态**全部通过** |
| 新安全判定引擎 | `backend/safety/`（DeepSeek，独立于旧 `risk_engine`） |
| 旧安全判定删除 | `risk_engine.py`、`llm/prompts.py`、`healing/safety.py` 三文件整体删除 |

---

## 1. 删除清单

### 1.1 整体删除的文件

| 文件 | 删掉的内容 |
| --- | --- |
| `backend/core/risk_engine.py` | `assess_risk()`、`HIGH_SIGNALS`/`MEDIUM_SIGNALS` 关键词表、`_has_signal()` 否定词处理、多模态困扰计数与升级逻辑 |
| `backend/llm/prompts.py` | `QUESTIONS["crisis_support"]` 固定危机话术（整个文件只为它存在） |
| `backend/healing/safety.py` | `guard_risk()`、`referral_text()`、`severe_is_negated()`、`SEVERE_SIGNAL`、`PLAN_ACTION`、`ESSENTIAL_RISK_FIELDS`、`UNCERTAIN_REASON` —— Healing 自有的第二套关键词风险规则，整体删除 |

### 1.2 删除的字段 / 分支 / 路由

| 位置 | 删除内容 |
| --- | --- |
| `SessionState` | `latest_risk: RiskResult`、`crisis_mode: bool` |
| `SessionStage` 枚举 | `CRISIS = "crisis"` → 替换为 `SAFETY_REVIEW` / `SAFETY_STOP` |
| `DialogueResponsePayload` | `risk` 字段 |
| `ChatResponse` | `risk` 字段 → 替换为 `safety` |
| `DialogueManager` | `assess_risk` + `crisis_mode` 分支、`_reply()` 方法、对 `fuse_turn`/`QUESTIONS`/`RiskResult` 的导入 |
| `HealingMemory` | `risk_input_issues`（旧的关键词溯源缺失阻断） |
| `HealingState.risk` / `HealingResponse.risk` | 类型 `RiskResult` → `SafetyVerdict` |
| `HealingState` 的 `refer` 动作 | → `enter_safety_mode`，危机文案只来自 `SafetyVerdict.messages` |
| `backend/api/healing.py` | `guard_risk`/`referral_text`/`QUESTIONS`/`RiskLevel` 导入、旧的 `risk_priority` 大小比较 |
| `backend/core/healing_adapter.py` | `RISK_FIELDS` 常量与「评估报告风险字段不完整就阻断普通支持」的逻辑 |
| 前端 `student/src/api/types.ts` | `Stage` 里的 `'crisis'`；`latest_risk`/`crisis_mode` |
| 前端 `AssessSafety.vue` | 硬编码 `12356`，改由后端 `safety.hotline_numbers` 下发 |

**残留引用核查**：全仓 grep `crisis_mode` / `latest_risk` / `assess_risk` / `risk_engine` /
`SessionStage.CRISIS` / `crisis_support` / `guard_risk` / `referral_text` /
`risk_input_issues` 后，活跃代码中**零命中**；剩余命中全部是「说明删除了什么」的注释与
历史调研/评审文档（`docs/research/`、`docs/prelaunch_audit_2026-10-01.md` 等，按"历史记录不动"保留）。

---

## 2. 替换清单（旧机制 → 新 Safety）

| 旧机制 | 新实现 | 说明 |
| --- | --- | --- |
| `assess_risk(fuse_turn(...))` 关键词+多模态分级 | `backend/safety/agent.py::evaluate_safety()` | DeepSeek LLM 判定，**唯一**安全来源 |
| 关键词直接决定等级 | `scan_keywords()` → `keyword_signals` | 关键词**只是线索**，不决定等级；隔离的危险词不单独触发 HIGH |
| 无否定/第三方处理 | `SAFETY_SYSTEM_PROMPT` + `SafetySignal.negated` | 明确要求处理否定（"我不想自杀"）与第三方（"我朋友想自杀"） |
| `RiskResult` 作对话安全结论 | `SafetyVerdict` | `risk_level`(normal/uncertain/high/imminent) + 后端派生 `route` |
| 模型可用性失败 → 静默低风险 | `build_failed_verdict()` | timeout/parse_error/unavailable **一律 fail-to-REVIEW**，`failure_never_continues` 校验器强制 |
| `requires_intervention` 路由 | `SafetyRoute` | `continue` / `safety_review` / `safety_stop` |
| 固定危机话术 | 模型生成 `messages` + `backend/safety/support.py` 兜底 | 兜底文案保证支持模式**永远有回复** |
| 硬编码 `12356`（前 端十余处） | `backend/safety/hotlines.py` | 按**部署地区**下发；缺少核实信息的条目拒绝加载 |
| Healing 自有正则风险规则 | `backend/healing/safety_bridge.py` | **零判定**：只有等级序、只读会话状态、文案兜底 |
| `HealingState.risk: RiskResult` | `HealingState.risk: SafetyVerdict` | 治愈侧不再构造 `RiskResult` |

### 2.1 安全等级语义（本次确立并已文档化）

| 等级 | 路由 | 会话语义 |
| --- | --- | --- |
| `normal` | `continue` | 正常评估流程 |
| `uncertain` | `safety_review` | **澄清模式**：暂停普通评估，后续 `normal` 可恢复 |
| `high` | `safety_stop` | **支持模式**：置 `safety_halted`，**会话内永不自动解除** |
| `imminent` | `safety_stop` | 同上 |

- `safety_stage`（`none`/`review`/`stopped`）是**当前模式**，可回落；
  `safety_halted` 是**单向停止锁**。
- 会话满足 `safety_halted or safety_stage != "none"` 时，阻断一切普通流程（含 Healing）。
- `ChatResponse.safety` 是**本轮结论**，`current_stage` 是**会话锁**，
  因此「本轮 `normal`」与「`current_stage == safety_stop`」可以并存——这正是设计预期。

### 2.2 全部生效入口（先接入、后删除）

| 入口 | 落点 |
| --- | --- |
| `/api/chat` 每一轮 | `backend/api/chat.py` —— 追加用户消息后、进入策略模型前判定，**每轮恰好一次** |
| 会话安全状态推进 | `chat.py`：**每轮无条件执行**（含"恢复正常"那一轮） |
| `/api/assessment` 直接提交转写 | `evaluation_engine.py::_screen_user_messages()` 逐条判定 |
| `/api/assessment` 会话路径 | `evaluation_engine.py::safety_verdicts()` 复用已算好的结论，缺失才补判 |
| Healing 入口一（start/regenerate） | `backend/api/healing.py` 判定 + 守卫 |
| Healing 入口二（chat） | `backend/api/healing.py`：**每条治愈发言都过同一个 `safety_runner`** |
| Healing 智能体内部二次门 | `backend/healing/agent.py` 的 `start` / `reply` |
| 评估报告风险字段 | `backend/safety/projection.py` 单向投影 |
| 学生端安全页 | `frontend-vue/student/src/views/assess/AssessSafety.vue` |
| 学生端治愈页 | `frontend-vue/student/src/views/heal/HealChat.vue` |

### 2.3 入口完备性审计（"不留安全检测空窗"）

已逐个核对所有会接收**学生自由文本**的活跃 HTTP 入口：

| 入口 | 是否覆盖 | 说明 |
| --- | --- | --- |
| `POST /api/chat` | ✅ | 每轮判定，且是 `process_turn` 的**唯一**活跃调用方 |
| `POST /api/assessment` | ✅ | 会话路径复用已有结论，直接提交转写则逐条补判 |
| `POST /api/healing/start` / `/chat` | ✅ | 每条治愈发言过**同一个** `safety_runner` |
| `POST /api/heal/mood`（`note` / `voice_text`） | ❌ **未覆盖** | 见 §6.5，**既有边界**，非本次替换引入 |
| `POST /api/communication`（`content`） | ❌ 未覆盖 | 消息由人工辅导员阅读，本身即升级通道 |
| `POST /api/heal/art/reflect` | 不适用 | 只提交画面客观特征（颜色/涂满度/对称性），非学生叙述 |

`dialogue_manager.process_turn` 在活跃代码中只有 `backend/api/chat.py:142` 一处调用，
且位于**普通分支内**（安全分支提前返回，不进入对话链路）——因此不存在绕过 Safety 的路径。

其他路由（`vision` / `audio` / `tts` / `teacher` / `profile` / `history` / `session` /
`heal_journal` 的其余端点 / `counseling` 的预约端点）不接收学生叙述性自由文本。

---

## 3. 保留清单（有实际用途，**未删**）

| 保留项 | 为什么保留 |
| --- | --- |
| `RiskResult` 类型本身 | 最终心理评估报告的风险字段词汇，已写进 SQLite 与 811 条历史记录 |
| `EvaluationResult.risk` 及其风险评分/`report` 生成逻辑 | 评估 Agent 自身的报告逻辑，与管理端预警列表共用 |
| `project_to_risk_result()` | Safety→报告的**单向**投影：`normal→low`、`uncertain→medium`、`high/imminent→high` |
| `EvaluationResult.risk.requires_intervention` | 管理端预警列表与跟进状态依赖它（UNCERTAIN 及以上为 True） |
| 管理端读取 `result.risk` 的 4 处 | `ReportViewer.vue`、`WarningList.vue`、`ReportDetail.vue`、`StudentDetail.vue` 全部照常 |
| `backend/api/counseling.py` 的 `12356` | CBT 标注提示词里引用的热线，与 Safety 下发机制无关 |
| `backend/core/counseling_store.py` 的 `12356` | iCBT 课程静态步骤文本，非安全下发 |
| `INITIAL_QUESTIONS`（`healing/agent.py`） | Healing 自己的场景开场问句，与已删的 `QUESTIONS` 无任何关系 |
| `build_vision_summary()` / `VisionState` / 视觉观察链路 | 评估报告与对话语气仍在使用 |
| `DIALOGUE_ENGINE=legacy\|graph` 开关 | 会话状态权威性不变，仍默认 `legacy` |
| 811 条历史记录 | 未做任何改写 |

### 3.1 刻意保留但已成死代码（建议后续清理，本轮不删）

- `backend/core/multimodal_fusion.py` 的 `fuse_turn()` / `FusedTurn`：
  唯一调用方是已删除的 `risk_engine.py`，现**无任何调用方**。
  它不在你明确要求删除的清单内，且属于通用多模态整理逻辑，故保留并在报告标注，
  避免误删可能被复用的部分。

---

## 4. 本轮修掉的三个真实 Bug（都有回归测试守着）

| # | Bug | 后果 | 修法 |
| --- | --- | --- | --- |
| 1 | `AsyncOpenAI` 单例被绑在第一个事件循环上，而项目每个请求用 `asyncio.run()` | **实机 5 次调用有 2 次静默返回 `unavailable`** | `SafetyAgent` 改为持有**客户端工厂**，每次 `judge()` 新建并关闭客户端。实机复测 5/5 `ok` |
| 2 | `/api/assessment` 的 `_prepare_history` 重建消息时漏掉 `safety`，而它会覆盖会话历史 | 提交一次评估就能把整个会话的逐条安全结论**清空**；客户端还能伪造安全结论 | 排除客户端提交的 `safety`，并从原消息恢复；新增 2 条回归测试 |
| 3 | `chat.py` 只在安全分支内推进 `safety_stage` | "恢复正常"那一轮之后 `safety_stage` 永远停在 `review`，**Healing 被永久误判为安全暂停** | 安全状态推进改为**每轮无条件执行**，普通分支把 `current_stage` 从 `safety_review` 复位为 `exploration` |

### 4.1 本轮修掉的架构缺口（安全空窗）

**问题**：`/api/assessment` 直接提交转写时，安全结论只被单向投影进报告的 `risk` 字段，
**不写** `session.latest_safety`。而 Healing 等入口的守卫只看**会话上的安全状态**，
于是"只存在于提交转写里的高危"会被当作普通会话继续。

**修法**：`evaluation_engine.record_safety_conclusion()` 把**最严重的那份
`SafetyVerdict`** 回写会话（`api/assessment.py::link` 负责落到真实会话）。
回写的是**结论本身**，不是从 `RiskResult` 反推等级，单向投影约定不破；
且只在更严重时覆盖，安全状态**单向往严**。

> 补充说明：Healing 每条发言本身也会过真实 Safety 判定，所以这条路径是"双保险"。

---

## 5. 真实测试结果

```
$ python -m pytest -q tests evaluation_agent
840 passed in 51.23s
```

- 改动前基线：**808 passed**
- 净增 **32** 条测试（含新文件 `tests/test_safety_agent.py`）
- **0 failed / 0 error**

前端：

```
$ npx vue-tsc -b --force        # frontend-vue/student  → exit 0
$ npx vue-tsc -b --force        # frontend-vue/admin    → exit 0
```

### 5.1 实机端到端（真实 DeepSeek，`scripts/smoke_safety_live.py`）

真实模型、真实 `/api/chat`，**不使用任何测试替身**：

| 步骤 | 结果 |
| --- | --- |
| 普通表达 | `level=normal` `route=continue` `current_stage=exploration`，`safety_halted=False` |
| 高风险表达 | `level=imminent` `route=safety_stop` `current_stage=safety_stop`，`safety_halted=True` `safety_stage=stopped`，**面向学生的文案不含任何数字号码** |
| 之后表达正常内容 | 仍在 `safety_stop`，`safety_halted` 保持，`safety_stage` 不回退 |

两种部署形态均**全部通过**：

- **未配置 `SAFETY_DEPLOYMENT_REGION`**：不下发号码（刻意设计），并有启动告警；
- **`SAFETY_DEPLOYMENT_REGION=CN`**：下发 `12356`，学生文案里仍然**没有**号码。

### 5.2 关于"不为测试通过而删断言"

- 未删除任何有效安全断言。旧的关键词/否定/计划类用例按新语义**重写**为等级驱动用例，
  并补了反向对照（"治愈已无自有规则"）。
- 旧 `test_crisis_preempts_policy` → `test_high_risk_turn_preempts_policy`：
  仍断言**策略模型未被调用**、`current_stage == "safety_stop"`、安全判定恰好调用一次。
- 旧 `test_earlier_context_never_hides_later_risk` 等 → 新语义同名改写
  （`test_earlier_context_never_hides_later_safety_stop`、`test_more_severe_safety_conclusion_always_wins`）。
- 确实有 3 处断言被替换，原因是被断言的能力**已按你的决策移除**，属于必要修改而非削弱：
  1. `tests/test_vision_alignment.py`、`tests/test_speech_flow.py`：
     由 `risk_score == 0.1`（视觉曾参与分级的代理断言）改为
     `visual_observation is None`（直接断言"没有视觉被送进对话生成"），**断言更直接**；
  2. `tests/test_conversation_data_flow.py`：视觉负效价 → `medium` 的期望改为
     安全 `route == "continue"` + 报告低风险（非低风险投影由别处覆盖）;
  3. `tests/test_chat.py`：新增 `test_safety_level_ignores_vision_and_depends_on_text`
     把"等级只看文本"这条新契约**显式固定**。

### 5.3 "支持安全支持模式持续对话"的验证

| 层面 | 证据 |
| --- | --- |
| 单元/集成 | `tests/test_chat.py::test_high_risk_message_enters_safety_stop_and_never_auto_resumes`：HIGH 之后**第二轮**强制判为 `normal`，断言 `current_stage` 仍为 `safety_stop`、`next_strategy == "safety_support"`、`reply` **等于**支持模式续接文案（不是空气泡、也不是普通问诊话术）、`turn_count == 2`，并且**普通对话生成器一次都没被调用** |
| 兜底文案 | 该轮 Safety 未给文案时回落 `SUPPORT_MODE_CONTINUATION_MESSAGE`（`backend/safety/support.py:36`），保证支持模式**永远有回应** |
| 实机 | 真实模型下第 3 轮（`uncertain`）仍返回支持性回应并持续确认学生当下是否安全，状态不回退 |

---

## 6. 需要你决策 / 注意的事项

### 6.1 ⚠️ 能力变化：视觉/听觉不再影响风险等级

- **旧**：`assess_risk(fuse_turn(text, vision, audio))`，`valence ≤ -0.5`、
  `energy ≤ 0.25`、`pause_ratio ≥ 0.5`、`engagement ≤ 0.3` 会调整风险；
  其中**两项以上**偏低可单独把等级抬到 `medium`。
- **新**：Safety 只判**文本**（+关键词线索）。视觉/听觉**完全不参与**安全等级。
- **影响**：一个"表情明显低落但文字平稳"的会话，报告风险从 `medium` 变为 `low`。
  视觉数据本身没有丢——它仍进入对话语气观察与报告的 `vision_summary`，
  只是不再抬升风险等级。
- **建议**：如果这条能力是产品需要的，正确做法是让视觉特征作为**额外信号**进入
  Safety 的输入（新建一个明确的信号契约），而**不是**恢复旧的 `risk_engine`。

### 6.2 ⚠️ 上线前必须配置 `SAFETY_DEPLOYMENT_REGION`

当前 `.env` **没有**设置该变量。后果：安全支持模式下**不会下发任何热线号码**
（学生仍会看到不含号码的支持话术与"联系可信任的人/去急诊"的指引）。

这是刻意设计（绝不假定未知地区适用中国大陆号码），且已加**启动告警**不再静默。
要下发号码，请在部署环境设置 `SAFETY_DEPLOYMENT_REGION=CN`。

注册表当前只有一条已核实条目：`12356`（全国心理援助热线，
来源：国家卫生健康委员会新闻发布会，`verified_at=2025-12-26`）。
调研文档里出现过的 `010-82951332`、`400-161-9995` **未登记**——仓库内没有官方来源可依，
补齐 `verified_at`/`verified_by`/`source_url` 后才会加载。

### 6.3 可用性 = DeepSeek 可用性

已确认接受：DeepSeek 故障时所有会话停在 `SAFETY_REVIEW`（fail-to-REVIEW，不放行）。
同时每轮多了一次远程调用，实测 Safety 延迟 **1.5–3.8 秒/轮**。

### 6.4 未验证项

- `scripts/validate_healing_current.py` 需要真实模型，**离线未跑**。
  其中 `unknown-age-new-risk` 用例的期望仍然成立（现在由真实 Safety 判定驱动，
  比原先依赖已删的关键词规则更稳），但请在有模型的环境跑一次确认。
- `frontend-vue/` **没有任何 `.test`/`.spec` 文件**，前端协议改动没有自动化守卫，
  仅靠 `vue-tsc` 类型检查。
- `docs/healing_agent.md` 只改写了已知与旧 `risk_input_fields` 相关的段落，
  其余段落是否残留旧关键词行为描述，未逐段通读。

### 6.5 ⚠️ 发现：心情日记的 `note` / `voice_text` 是未覆盖的自由文本入口

**这是既有边界，不是本次替换造成的空窗**——旧 `assess_risk` 也从未覆盖它。
但它是本次入口审计中唯一"既不过 Safety、也没有人工看到"的路径：

- `POST /api/heal/mood` 接受 `note`（≤200 字）与 `voice_text`（≤200 字）；
- `backend/api/heal_journal.py:3` 明确写着该模块"与学生心理筛查主链路相互独立……
  **不参与风险判定**"；
- `heal_store` / `MoodEntry` 只在心情日记模块内部使用，**没有任何教师端出口**
  （与管理端预警列表完全不通）。

**后果**：学生在心情日记里写下高危内容时，既不会触发安全支持模式，
也不会有任何人被通知。

**为什么没有顺手改**：这属于**扩大范围**，代价与产品影响都很实在——
每次保存心情都会多一次 LLM 调用（实测 1.5–3.8 秒延迟），
且会改变"日记是私密空间"这一产品承诺（若接入 Safety，是否要通知教师？
是否要展示安全干预页？）。这些需要你决定。

**可选方案**（按侵入性递增）：
1. 只对关键词做一次本地扫描，命中则在响应里返回一条温和的求助提示
   （不调模型、不通知任何人、不改会话状态）；
2. 接入 Safety 但只用于**向学生本人**展示支持资源（不进教师预警）；
3. 接入 Safety 并写入会话安全状态 + 进教师预警（与主链路一致）。

### 6.6 已修复的小瑕疵（原报告列为"已知瑕疵"，本轮已处理）

`backend/healing/safety_bridge.py::session_safety_verdict()` 从会话状态复原停止结论时，
原先标 `model_status=unavailable`。这会让 `project_to_risk_result` 往报告的
`risk_reasons` 里写入「安全判定服务状态：unavailable」，而停止锁其实是
**一次成功的判定**建立的，对复核者是误导。现改为 `model_status=ok`，
并有 `test_reconstructed_stop_is_not_reported_as_model_failure` 守着。
