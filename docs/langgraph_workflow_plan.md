# LangGraph 多智能体工作流实施计划

> 本文件是**计划**，本轮未修改任何代码。
> 所有结论都来自实际读取的当前代码，行号可核对。

---

## 0. 勘察结论：三个必须先认知的事实

### 0.1 LangGraph 目前**没有安装**，也不在依赖清单里

```
langgraph                   MISSING (ModuleNotFoundError)
langchain / langchain_core  MISSING
langgraph.checkpoint.sqlite MISSING
requirements.txt 中无任何 lang* 条目
```

环境：Python 3.11.16、pydantic 2.13.5、fastapi 0.141.1、httpx 0.28.1、
openai 3.23.0、anyio 4.15.1、pytest 9.1.1。

**含义**：新版 Safety 之所以能"不用 LangGraph 就完成"，是因为它是**单点判定**，
本来不需要图。而"Dialogue 主控 + 按需 Decision + 视觉复核"是**真正的多轮状态机**，
LangGraph 在这里有实质价值。但安装必须作为独立第一步验证，
因为 LangGraph 会拉入 `langchain-core`，存在与 pydantic/fastapi 的版本约束风险。

### 0.2 当前"每轮必调 Decision"的确切位置

`backend/core/dialogue_manager.py:81`：

```python
decision = limit_topic(session, self._decide(session))
```

`_decide()` 无条件调用策略模型（`backend/policy/client.py:83` 的
`predict()`，同步 `httpx`，且**限制 loopback**）。`DialogueManager` 里没有任何
"这轮是否需要新策略"的判断——这正是你说的机械感来源。

### 0.3 一个必须处理的隐藏耦合：话题计数是**两阶段协议**

`backend/core/screening_flow.py:55` 设置 `pending_topic`，
而消费它的是**下一轮**的 `record_answer()`（`:21-26`）：

```python
def record_answer(session):
    if progress.pending_topic is not None:
        progress.topic_turns[progress.pending_topic] += 1
        progress.pending_topic = None
```

**这意味着**：如果让 Dialogue 自主追问而不调用 Decision，`limit_topic` 就不会执行，
`pending_topic` 保持为 `None`，于是**这一轮追问不会被计入任何话题**。
后果是话题次数约束（`MAX_TOPIC_TURNS = 2`）与覆盖率收尾
（`completion_reason` 要求 8 个话题各≥1 次）会**静默失效**，筛查可能永远收不了尾。

这是整个改造中最容易踩空的地方，方案第 2.3 节专门解决它。

---

## 1. 目标架构与图拓扑

### 1.1 分层职责

```
HTTP 层  backend/api/chat.py           会话锁、幂等、落库、计数（保持现有职责）
图 层    backend/graph/                LangGraph：共享状态 + 条件路由 + 节点调度
能力层   backend/safety/  (新，已完成)  安全判定
         backend/policy/               决策模型（原样保留，不重训）
         backend/agents/dialogue_agent.py  对话生成（改造为可自判）
         backend/core/visual_acknowledgment.py  视觉线索选择（原样保留）
约束层   backend/core/screening_flow.py 话题次数 / 覆盖率 / 收尾（保留并扩展）
权威层   backend/models/states.py::SessionState  仍是唯一权威状态
```

**不引入 LangGraph Checkpointer**：`SessionState` 依旧是权威状态，
图是"每轮一次"的无状态编排。这样避免把 `SessionState` 序列化进 SQLite 检查点，
也不需要处理历史会话反序列化。图内部状态用 `TypedDict` 在单轮内传递。

### 1.2 图拓扑（Dialogue 主控 + 按需 Decision + 生成后视觉复核）

```
                    ┌─────────────┐
   START ──────────▶│ safety_gate │  复用 backend/safety（Phase 3 迁入，之前留在 chat.py）
                    └──────┬──────┘
              safety_stop  │  safety_review            continue
        ┌──────────────────┴───────────┐                │
        ▼                              ▼                ▼
  ┌──────────────┐            ┌──────────────┐   ┌────────────────┐
  │safety_reply  │            │safety_reply  │   │prepare_vision  │ 复用三条互斥视觉通道
  └──────┬───────┘            └──────┬───────┘   └───────┬────────┘
         │                           │                   ▼
         │                           │           ┌────────────────┐
         │                           │           │ closing_check  │ 复用 completion_reason
         │                           │           └───────┬────────┘
         │                           │        closing    │   continue
         │                           │     ┌─────────────┘        │
         │                           │     ▼                      ▼
         │                           │  ┌─────────────────────────────────┐
         │                           │  │ dialogue_route (route_and_reply)│ Dialogue 自判
         │                           │  └───────────────┬─────────────────┘
         │                           │      needs_decision│        no
         │                           │     ┌─────────────┘        │
         │                           │     ▼                      │
         │                           │  ┌──────────────┐          │
         │                           │  │   decision   │ 预算=1   │
         │                           │  └──────┬───────┘          │
         │                           │         └────────┬─────────┘
         │                           │                  ▼
         │                           │      ┌───────────────────────┐
         │                           │      │ dialogue_execute      │ 1~3 条消息
         │                           │      └───────────┬───────────┘
         │                           │                  ▼
         │                           │      ┌───────────────────────┐
         │                           │      │   visual_review       │ 生成后复核
         │                           │      └───────────┬───────────┘
         │                           │    有复核要求 ∧ 预算=1
         │                           │         └──▶ 回 dialogue_execute（仅带样式要求）
         │                           │                  │ 通过
         ▼                           ▼                  ▼
                    ┌──────────────────────┐
                    │        commit        │ 唯一写 SessionState 的节点
                    └──────────┬───────────┘
                               ▼
                              END
```

**关键约束**（写进代码与测试）：
- `decision` 节点只能从 `dialogue_route` 到达，**每轮最多 1 次**。
- `visual_review` 的回边**只能回到 `dialogue_execute`**，永远不能回到 `decision`
  （满足"Visual Review 不得擅自更改 Decision 确定的主题"）。
- 安全分支**直达 commit**，不经过 `prepare_vision` / `decision` / `dialogue_*` /
  `visual_review`（满足"不得绕过 Safety 决策"）。
- `commit` 是**唯一**修改 `SessionState` 的节点。

---

## 2. 五个必须先解决的真实问题

### 2.1 同步/异步边界（这是最容易翻车的地方）

现状：`/api/chat` 是同步 `def`，跑在 anyio 线程池；`DialogueManager` 内部用
`asyncio.run()`（`dialogue_manager.py:176,192`）。策略客户端是**同步** httpx。

**决策**：图用 `async` 节点，但对外暴露**同步门面**：

```python
# backend/graph/engine.py
class DialogueEngine:
    def run_turn(self, ...) -> DialogueResponsePayload:
        return asyncio.run(self._graph.ainvoke(state, config=...))
```

- 保持 `/api/chat` 仍是同步 `def`，现有测试（`client.post` 同步调用）**零改动**。
- 节点内调用同步客户端一律 `await asyncio.to_thread(...)`（策略模型、必要的同步工具）。
- **硬规则**：图内**不得**出现 `asyncio.run()`。
- **已知陷阱**：我在 Safety 阶段实测到一个真实 Bug——
  单例 `AsyncOpenAI`/httpx 连接池绑定在**第一个**事件循环上，而项目每请求
  `asyncio.run()`，导致第 2 次调用起静默失败（当时 5 次里坏 2 次）。
  所以图内每次 LLM 调用必须**新建并关闭客户端**（Safety 已按此修好并测试守着，
  对话侧必须照做）。这条会写成测试。

**为什么不直接把整个 API 改 `async def`**：`DialogueManager.process_turn` 是同步的
且在内部 `asyncio.run`，改成 async 会牵动 `healing`、`assessment` 等全部调用链，
风险与收益不成比例；竞赛定位也不需要。

### 2.2 Dialogue 如何"自主判断是否需要 Decision"

**不能只让模型说了算**，否则话题覆盖率和收尾会失控。采用
**模型建议 + 后端强制 + 预算上限**三层：

```python
needs_decision = (
    model_says_yes                      # 模型判断：这个话题聊透了 / 用户不想继续
    or force_by_topic_budget            # 后端：当前话题已用满 MAX_TOPIC_TURNS=2
    or force_by_coverage_gap            # 后端：turn_count>=2 且仍有未访问话题
) and decision_calls < MAX_DECISION_CALLS
```

- 后端强制规则放在 `screening_flow.py` 新增函数
  `should_force_decision(session, active_topic) -> str | None`（返回强制原因，便于 trace）。
- 模型返回的 `suggested_topic` **必须**通过 `TOPICS` 白名单校验，否则丢弃。
- `Dialogue` 只决定"这一轮要不要新策略"和"怎么把话说明白"，
  **不能**决定评估目标——它影响不了 `TOPICS` 集合与收尾阈值。

**两种模式**（你提的命名直接采用）：

| 模式 | 何时用 | Dialogue 收到什么 |
| --- | --- | --- |
| `route_and_reply` | `dialogue_route` 节点 | 无 decision；可自行追问，或返回 `needs_decision=true` |
| `execute_decision` | `dialogue_execute` 节点 | 有 decision 时必须服从；也必须能处理 decision 时的本地表达 |

### 2.3 保住话题计数：新增 `active_topic`

如 §0.3 所述，本地追问会漏记话题。修法：

1. `ScreeningProgress` 新增 `active_topic: str | None = None`（持久化）。
2. `limit_topic()`（`screening_flow.py:42`）在设置 `pending_topic` 的同时设置
   `active_topic = topic.value`。
3. 图新增 `resolve_topic` 逻辑：
   - 走了 `decision` → 正常走 `limit_topic`；
   - **没走** `decision`（本地追问）→ `session.screening_progress.pending_topic = session.screening_progress.active_topic`。
4. 这样本地追问同样计入当前话题预算，**2 轮后后端必然强制下一次 Decision**，
   于是"自然追问"与"话题推进"两个目标同时成立。

旧记录没有 `active_topic`（默认 `None`）→ 向后兼容，无需迁移脚本。

### 2.4 防止重复调用与无限循环

| 机制 | 落点 |
| --- | --- |
| `decision_calls` 预算（默认 1/轮） | `TurnState.decision_calls`，`decision` 节点自增 |
| `visual_review_calls` 预算（默认 1/轮） | 同上，回边先查预算 |
| 条件边守卫 | `dialogue_route` 的条件函数在预算耗尽时直接返回 `execute_without_decision` |
| 硬backstop | `graph.ainvoke(..., config={"recursion_limit": 15})`，`GraphRecursionError` → 转 `DialogueUnavailable` |
| 决策不可重复 | `decision` 只在 `decision is None` 时才执行，否则直接跳过 |

对应测试：构造一个"模型反复要求 decision"的假客户端，
断言最终 `decision_calls == 1` 且**没有**抛栈溢出/挂死。

### 2.5 视觉：生成前**保留** + 生成后**新增**，且不重复说

**生成前（原样保留，只换位置）**：`dialogue_manager.py:82-98` 那三条**互斥**通道
`select_visual_observation` / `select_visual_checkin` / `select_visual_tone`
整体搬进 `prepare_vision` 节点。这三个函数在
`backend/core/visual_acknowledgment.py` 里**一行不改**。
并保留 `use_latest_states` 的 5 秒新鲜度判定（`dialogue_manager.py:55-62`）——
它决定了哪些视觉帧有资格进入本轮。

**生成后 Visual Review（新增）**：先做**确定性规则**（便宜、可测、可解释），
规则命中才触发**一次**定向重写：

| 规则 | 触发条件 | 处理 |
| --- | --- | --- |
| R1 用户已自述 | 文字极性明显消极 且 回复仍在提外观 | 要求删掉外观提及（你举的例子） |
| R2 生硬拼接 | 某条气泡**只**是外观句（如"你看起来很难过。"） | 要求并入完整句 |
| R3 气泡机械 | 3 条气泡且末条与近期高度重复 | 要求合并重写 |
| R4 视觉未用 | 给了 `visual_observation` 但回复完全没提 | **复用现有**已存在的 `missed_visual` 重写通道 |
| R5 过度解读 | 回复出现临床/诊断式断言（"你抑郁了"） | 要求改为描述性表达 |

**重要复用**：`backend/agents/dialogue_agent.py:122-151` **已经**实现了
"发现问题 → 追加【重写要求】→ 重发 → 复检 → 仍不合格才报错"的机制。
Visual Review 不新建 LLM 调用类型，只把规则结果追加进**同一个**
`requirements` 列表即可。这是本方案里性价比最高的一处复用。

---

## 3. 分阶段实施计划

> 每阶段独立可运行、可测试、可回滚。**未通过测试不得进入下一阶段。**

### Phase 0 — LangGraph 落地与可行性验证（不改产品代码）✅ **已完成**

| 项目 | 内容 |
| --- | --- |
| 改文件 | `requirements.txt`（+8 行：`langgraph==1.2.2`、`websockets>=17` 及说明）；新建 `scripts/check_langgraph_env.py` |
| **实测结果** | 见下方"Phase 0 实测记录" |
| 完成判据 | 原有 840 项测试仍全绿 ✅ |

#### Phase 0 实测记录（2026-10-15）

**依赖冲突：发现 1 处，并已规避。**

- 默认求解 `langgraph` → `1.2.15` + `langgraph-sdk 0.4.7`，后者要求
  `websockets<17,>=14`，会把已装的 **websockets 17.2 降级到 16.1.1**。
- 反向依赖核查：`funasr>=10.4`、`uvicorn>=13`（standard extra）都不要求 17；
  `openai` 的 `<16,>=13` 只属于未安装的 `realtime` extra。**降级本身是安全的**，
  但会改动既有环境。
- **采取零变更方案**：`langgraph==1.2.2` + `websockets>=17`，
  使 `langgraph-sdk` 解析到 `0.3.15`，`websockets` 保持 17.2 不动。

**安装结果（0 移除 / 0 版本变更 / 17 新增）：**

```
langgraph 1.2.2        langchain-core 1.6.10      langgraph-checkpoint 4.3.0
langgraph-prebuilt 1.1.1   langgraph-sdk 0.3.15   langsmith 0.14.9
langchain-protocol 0.0.19  distro 1.9.0           jsonpatch 1.35
jsonpointer 3.2.1      orjson 3.13.0              ormsgpack 1.12.2
requests-toolbelt 1.0.0    tenacity 9.2.1         uuid-utils 0.17.1
xxhash 4.0.1           zstandard 0.25.0
```

未被改动的关键包：`pydantic 2.13.5`、`fastapi 0.141.1`、`starlette 1.7.0`、
`httpx 0.28.1`、`openai 3.23.0`、`uvicorn 0.54.0`、`anyio 4.15.1`、`websockets 17.2`。
`pip check` → `No broken requirements found.`

**运行模型验证（`scripts/check_langgraph_env.py`，`python 3.11.16`）：**

| 检查 | 结果 |
| --- | --- |
| 3 节点 + 1 条件边路由 | 高分走 `high`、低分走 `low` ✅ |
| 每次新建并关闭 `AsyncClient`，连续 5 次 `asyncio.run(graph.ainvoke(...))` | **5/5 成功** ✅ |
| 反例：模块级单例 `AsyncClient` 跨 5 次 `asyncio.run` | **2/5 失败**，`RuntimeError: Event loop is closed` |
| `recursion_limit=15` 拦住无限回边 | 被拦下并抛错，未挂死 ✅ |

> 反例的失败形态（**同为 5 次坏 2 次**）与 §2.1 记录的 Safety 阶段真实 Bug 完全一致，
> 证实"每个节点必须新建并关闭异步客户端"这条纪律在 LangGraph 下同样**必需**，不是预防性猜测。

**回归测试：** `pytest -q tests evaluation_agent` → **840 passed in 53.21s**（安装前同为 840 passed）。


### Phase 1 — 图骨架，行为与现状**完全等价** ✅ **已完成**

| 项目 | 内容 |
| --- | --- |
| 新建 | `backend/graph/`：`__init__.py`、`state.py`（`TurnState` + `GRAPH_RECURSION_LIMIT`）、`nodes.py`、`build.py`、`engine.py` |
| 改文件 | `backend/api/chat.py`（引擎分派 + 两个新错误码）；`backend/core/dialogue_manager.py`（抽出共享函数，`process_turn` 改为组合它们）；`backend/models/states.py`（`dialogue_engine` 内部字段） |
| 保留 | `DialogueManager.process_turn` / `_decide` / `_generate_reply` 全部保留；`screening_flow.py`、`visual_acknowledgment.py`、`backend/safety/`、`backend/policy/` **一行未改** |
| 新增测试 | `tests/test_dialogue_engine.py`（30 条） |
| 开关 | `DIALOGUE_ENGINE=legacy`（默认）\| `graph`。非法取值**报错而非静默回退** |
| 完成判据 | **870 passed / 0 failed**（840 基线 + 30 新增）✅ |

#### Phase 1 实测记录

**执行模型（实现期最重要的发现）**：`DialogueManager._generate_reply` 内部沿用
`asyncio.run(...)`（`dialogue_manager.py:176` 附近）。因此**不能**用
`asyncio.run(graph.ainvoke(...))` + async 节点——节点里再调 `asyncio.run`
必然抛 `asyncio.run() cannot be called from a running event loop`。
实测三种组合（`scripts/check_langgraph_env.py` 同口径探针）：

| 组合 | 结果 |
| --- | --- |
| `graph.invoke()`（同步）+ 同步节点内 `asyncio.run` | ✅ 连续 3 次全部成功 |
| `graph.ainvoke()` + **异步**节点内 `asyncio.run` | ❌ 与预期一致地冲突 |
| `graph.ainvoke()` + **同步**节点（LangGraph 转执行器线程） | ✅ 成功，但依赖执行器语义 |

**结论：Phase 1 采用同步 `graph.invoke()`**——图内不存在事件循环，
既有业务代码的执行模型与迁移前完全相同，也没有新增任何 `asyncio.run`。
测试用 AST 断言图内不存在 `asyncio.run` 且不使用 `ainvoke`。

**langgraph 惰性导入**：`backend/graph/__init__.py` 起初在模块级导入 `build`，
导致 `DIALOGUE_ENGINE=legacy` 也会加载 langgraph（实测
`"langgraph" in sys.modules` 为 `True`）。已改为 PEP 562 `__getattr__` 惰性暴露，
实测 legacy 路径导入 `backend.api.chat` 后 langgraph **未加载**，
"依赖缺失仍能按 legacy 跑"这条退路成立。有 AST 测试守着。

**拓扑**（`decision` 仍无条件执行，与迁移前"每轮必调决策"一致）::

    START ─▶ prepare_turn ─┬─(ending)─▶ dialogue_close ──────────────────────▶ commit ─▶ END
                           └─(open)──▶ decision ─▶ prepare_vision ─▶ dialogue_execute ─▶ commit

`prepare_turn → (closing | open)` 是**真实条件路由**；`decision` 的入边在
Phase 2 改为条件边即可实现按需调用，无需再动其他节点。
（Phase 2 实际做的比这句更多：`prepare_vision` 更名为 `visual_prepare`，
并新增了 `closing_check` / `dialogue_route` / `resolve_topic` 三个节点。）

**防漂移手段**：两组实现共用同一批模块级函数
（`resolve_current_vision` / `ensure_screening_open` / `select_visual_channels` /
`finalize_visual_feedback` / `open_payload` / `closing_payload`）与
`DialogueManager` 的三个公开入口（`decide` / `reply_for_decision` / `closing_reply`），
图节点不重写任何业务逻辑，只做编排。

**引擎绑定**：会话第一轮把引擎记在 `SessionState.dialogue_engine`
（`exclude=True`，不进 API 响应），之后不匹配即返回
409 `DIALOGUE_ENGINE_MISMATCH`，且该轮被整体丢弃、不留半轮。

**明确未做**（留给 Phase 2+）：Dialogue 自主判断是否调用 Decision、
1~3 条气泡、生成后 Visual Review、把会话写入集中到单一 commit 节点。

### Phase 2 — Dialogue 主控 + Decision 按需 ⭐**你的首要任务** ✅ **已完成**

| 项目 | 内容 |
| --- | --- |
| 新建 | `tests/test_dialogue_autonomy.py`（43 条）、`scripts/compare_decision_budget.py`（可复现对照实验） |
| 改文件 | `backend/core/screening_flow.py`（`should_force_decision` / `adopt_decision` / `carry_over_topic` / `coverage_complete`）；`backend/models/states.py`（`ScreeningProgress.active_topic` / `.active_actions`，均 `exclude=True`）；`backend/models/dialogue.py`（`DialogueRouteDecision` / `DialogueRouteRequest`）；`backend/prompts/dialogue_prompt.py`（路由 System Prompt + Builder）；`backend/agents/dialogue_agent.py`（`parse_route_decision` / `route()` / `route_fallback`）；`backend/core/dialogue_manager.py`（`route_turn` / `reuse_decision` / `history_before_turn`）；`backend/graph/{state,nodes,build}.py` |
| 一行未改 | `limit_topic` / `record_answer` / `completion_reason` 的**任何阈值**；`backend/safety/**`；`backend/policy/**`；`backend/core/visual_acknowledgment.py`；全部前端文件 |
| 完成判据 | **914 passed / 0 failed**（870 基线 + 43 自主性 + 1 前端契约）✅ |

#### Phase 2 实测记录

**与计划的两处偏离（都是有意的）**

1. **没有改 `DialogueAgentRequest` 的 Schema。** 计划里写"`decision` 改为可选 + 增加 `mode`"，
   实际做法是：`decision` **保持必填**，跳过决策时用 `reuse_decision()` 把
   ``active_actions`` 原样还原成 `PolicyDecision`。理由是原方案会让 Dialogue Agent
   出现"没有决策也能工作"的第二种工作模式，而本阶段的约束是
   *Dialogue 不能自己选话题*——保持 `decision` 必填正好编码了这条约束。
   `suggested_topic` 也没有加：路由结构里**刻意没有**话题字段，模型在类型层面
   就无法指定新话题（比"加了再在代码里丢弃"更可靠）。

2. **新增了一个计划里没有的节点 `resolve_topic`，并新增了一条强制条件 `coverage_lag`。**
   - `resolve_topic`：两条分支（需要决策 / 复用决策）在这里收口，成为本轮**唯一**的
     话题记账点。计划把 `limit_topic` 留在 `decision` 里，那会让"复用策略"分支
     没有写 `pending_topic` 的地方——正是"自主追问不计入话题"那个 bug 的来源。
   - `coverage_lag`：实测发现自主追问会让每个话题都用满 2 轮，覆盖面推进明显变慢
     （最坏情况第 16 轮才补齐，只剩 4 轮余量）。规则是"已过 `MIN_TURNS`、
     当前话题已有 1 轮、覆盖仍不全 → 强制轮换"，把最坏情况压到第 13 轮。

**拓扑（最终）**::

    START ─▶ prepare_turn ─▶ closing_check ─┬─(收尾)─▶ dialogue_close ──────────────────▶ commit ─▶ END
                                            │
                                            └─(普通)─▶ dialogue_route ─┬─(需要新策略)─▶ decision ─┐
                                                                       │                       │
                                                                       └─(复用已有效策略)──────┤
                                                                                               ▼
                                                                         resolve_topic ─▶ visual_prepare
                                                                               ─▶ dialogue_execute ─▶ commit

`dialogue_route` 在**后端强制**时短路掉路由模型调用（结论已定，不必再问一次）。
图**没有回边**，有 AST 级拓扑排序测试守着，因此节点不会被重复执行。

**两个关键机制**

- **`active_topic` 与 `pending_topic` 的分工**：`active_topic` 是"正在推进的全局话题"，
  只在决策生效时更新；`pending_topic` 是"下一条回答该计入哪个话题"，**每轮结束时
  必定被指向一个明确话题**（`adopt_decision` 或 `carry_over_topic`）。因此计数与
  "本轮是否调用过决策模型"完全解耦。幂等性来自**消费即清空**：
  `record_answer` 计数后立刻把 `pending_topic` 置 `None`，重复调用不再累加。
- **路由失败的方向**：一律回退为 `need_decision=True`（回到既有的每轮决策流程）。
  只有"布尔值明确 + 原因码在约定集合内"才接受 `need_decision=False`。
  多调一次决策是安全的，让话题推进停摆不是。

**对照实验（离线桩，`scripts/compare_decision_budget.py`）**

决策模型固定返回 `["共情安慰","睡眠"]`（话题能否切换完全取决于后端次数约束）：

| 模式 | 轮数 | 决策调用 | 路由调用 | 回复生成 |
| --- | --- | --- | --- | --- |
| legacy（6 轮） | 6 | **6** | 0 | 6 |
| graph / 每轮要新策略（6 轮） | 6 | **6** | 4 | 6 |
| graph / 按需（6 轮） | 6 | **3** | 3 | 6 |
| legacy（跑到收尾） | 10 | **9** | 0 | 10 |
| graph / 每轮要新策略 | 10 | **9** | 7 | 10 |
| graph / 按需 | 13 | **8** | 4 | 13 |

- "每轮要新策略"时 graph 与 legacy 的决策次数**完全一致**，且话题计数逐项相同——
  说明减少的调用完全来自路由判断，不是顺手改了别的东西。
- 按需模式下 6 轮省一半；轮数拉长后省得变少，因为**话题轮换本身就需要决策**
  （`coverage_lag` / `topic_budget` 强制），这是结构性代价，不是缺陷。
- 按需模式覆盖全部 8 个话题用时 13 轮 vs legacy 10 轮：更慢，但在 20 轮预算内。

**这些数字只证明调度逻辑，不证明对话质量。** 真实模型下的质量与延迟需要真模型实验。

**明确未做**（留给 Phase 3+）：Safety 迁入图、1~3 条气泡、生成后 Visual Review、
Agent Trace、高并发改造。

### Phase 3 — Safety 迁入图作为节点 0

| 项目 | 内容 |
| --- | --- |
| 改文件 | `backend/graph/nodes.py`（新增 `safety_gate` / `safety_reply`）；`backend/graph/build.py`（追加条件边）；`backend/api/chat.py`（安全分支的编排交给图，`chat.py` 只保留会话锁/幂等/落库） |
| 复用 | `chat.py` 现有的 `safety_runner` 与 `safety_stage_value` / `safety_reply_messages` / `safety_next_strategy` / `safety_session_stage` **原样搬进节点**；`backend/safety/**` 一行不改 |
| 风险控制 | 这是**纯回归风险**（Safety 已正确且测试完备），所以放在图被证明等价**之后**。回归门 = `tests/test_chat.py` / `tests/test_policy_integration.py` 里全部安全用例必须继续绿，且新增一条"安全分支的 trace 里不出现 prepare_vision/decision/dialogue_* 节点"的断言 |
| 完成判据 | 840+ 全绿；安全分支节点集合断言通过 |

### Phase 4 — 1~3 条消息输出

| 项目 | 内容 |
| --- | --- |
| 改文件 | `backend/models/dialogue.py`：`DialogueAgentResponse.messages`；`reply` 保留为 `messages[0]` 的兼容别名并标注弃用 |
| 改文件 | `backend/prompts/dialogue_prompt.py`：明确"1~3 条气泡，数量由对话需要决定，**不要凑满 3 条**，**不要用标点强行拆分**" |
| 改文件 | `backend/agents/dialogue_agent.py`：气泡数校验。违反时先走**已有**重写通道；仍违反则把多余气泡**并入最后一条**（绝不静默丢内容） |
| 改文件 | `backend/models/states.py`：`Message` 新增 `assistant_turn_id: str | None`（同一轮的助手消息共享） |
| 改文件 | `backend/api/chat.py`：同一轮助手消息逐个落库、共享 `assistant_turn_id`；`turn_count` **只**统计用户轮（现有 `record_answer` 语义已经是这样，不改） |
| 改文件 | `backend/models/responses.py`：`ChatResponse.messages` **已存在**（Safety 阶段已加），无需新增 |
| 改文件 | 前端 `frontend-vue/student/src/api/types.ts`（`ChatResponse.messages` 已加）+ 聊天视图：按 `messages` 渲染多个气泡；TTS 逐条播报 |
| 新增测试 | `tests/test_message_bubbles.py`：① 1 条 / 2 条 / 3 条三种输出都能通过；② 4 条 → 触发重写或合并、**不丢内容**；③ 同一轮所有助手消息共享 `assistant_turn_id`；④ `turn_count` 只加 1 |
| 完成判据 | 上述全绿 + 前端既有 `vue-tsc` 通过（前端目前**没有**自动化测试，这是已知缺口） |

### Phase 5 — 生成后 Visual Review

| 项目 | 内容 |
| --- | --- |
| 新建 | `backend/graph/visual_review.py`：R1~R5 规则（纯函数、可单测，不调模型） |
| 改文件 | `backend/graph/nodes.py`（`visual_review` 节点 + 有界回边）；`backend/agents/dialogue_agent.py`（接收 `review_requirements`，走**已有**的 requirements 重写路径） |
| 保留 | `backend/core/visual_acknowledgment.py`、`backend/core/multimodal_consistency.py` **一行不改** |
| 新增测试 | `tests/test_visual_review.py`：R1~R5 各一条；"用户已自述情绪时不重复提外观"（你的原例）；"复核**不改变** decision 的 topic"；"复核预算 1，不产生第二次 Decision 调用"；"安全分支不进入复核" |
| 完成判据 | 全绿；且 `test_policy_integration.py` 里"视觉不被借用到错误轮次"的既有断言继续绿 |

### Phase 6 — 演示与证据

| 项目 | 内容 |
| --- | --- |
| 新建 | `scripts/demo_graph_trace.py`：逐轮打印**节点轨迹**（走了哪些节点、为什么走条件边、Decision 调用次数、视觉线索是否被采用、复核是否触发） |
| 改文件 | `backend/models/responses.py`：`ChatResponse.trace: list[dict] | None`，由 `GRAPH_TRACE_ENABLED` 环境变量控制（默认关，演示时开），**不进学生可见文案** |
| 对应演示场景 | A 自然对话（Phase 2）、B 动态调度（trace）、C 多模态（Phase 5）、D 安全识别（Phase 3）、E 完整闭环（现有评估+治愈，不改） |
| 新增测试 | `tests/test_graph_trace.py`：trace 结构稳定、默认关闭时字段为 `None` |

---

## 4. 逐条回答你的问题

| # | 你的问题 | 答案 |
| --- | --- | --- |
| 1 | 如何接入已完成的 `backend/safety/` | Phase 3 把它变成图的首节点 `safety_gate`：复用 `chat.py` 现有的 `safety_runner.evaluate()`，安全分支走 `safety_reply → commit`，**不进入**任何普通节点。`backend/safety/**` 一行不改。因为 Safety 已正确且测试完备，这一步放在图被证明等价之后，纯回归风险可控 |
| 2 | 如何复用现有 `dialogue_manager.py` | **不删不改逻辑**。把 `process_turn` 里的三段（5 秒新鲜度 + 三条互斥视觉通道、`_generate_reply` 的请求组装、`visual_feedback` 收尾）抽成模块级函数，legacy 与 graph 共用。`DialogueManager.process_turn` 原样保留作为 `DIALOGUE_ENGINE=legacy` 的实现与回退 |
| 3 | 如何实现 Dialogue 自主判断是否需要 Decision | `dialogue_route` 节点以 `route_and_reply` 模式调用 Dialogue，要求返回严格 JSON：`{needs_decision, reason, messages}`。最终值 = **模型建议 OR 后端强制**，且受 `decision_calls < 1` 预算约束；`suggested_topic` 必须过 `TOPICS` 白名单。后端强制规则在 `screening_flow.should_force_decision()` |
| 4 | 如何保留后端话题次数限制与收尾机制 | 阈值（`MIN_TURNS=10` / `MAX_TURNS=20` / `MAX_TOPIC_TURNS=2`）与 `completion_reason` 三种收尾**一行不改**。关键是补上 `active_topic`（§2.3），让本地追问也计入话题预算；`closing_check` 节点在 Dialogue 之前拦截收尾，收尾轮不允许再提问（沿用现有 `finish_screening` 校验） |
| 5 | 如何避免重复调用 Decision 和无限循环 | 四道防线：`decision` 只在 `decision is None` 时执行；`decision_calls` 预算；`visual_review` 回边只回 `dialogue_execute` 且带自己的预算；`recursion_limit=15` 硬backstop 并转成明确错误。均有专门测试 |
| 6 | 如何接入生成前视觉信息和生成后 Visual Review | 生成前：三条互斥通道整体搬进 `prepare_vision` 节点，**函数不改**，5 秒新鲜度规则保留。生成后：新增 `visual_review` 节点，先跑 R1~R5 确定性规则，命中才把要求追加进 `dialogue_agent` **已有的** requirements 重写通道（不新建 LLM 调用类型），预算 1 |
| 7 | 如何逐步改造 1～3 条消息输出 | 分两步：Phase 2 先让 LLM 以 JSON 输出 `messages` 数组（同时容忍纯文本回退），`reply` 保持为 `messages[0]` 兼容；Phase 4 再补气泡数量校验、`assistant_turn_id` 落库与前端多气泡渲染、TTS 逐条播报 |
| 8 | 每步改哪些真实文件 / 保留什么 / 加哪些测试 | 见 §3 每阶段的表格（Phase 0~6 逐项列出） |

---

## 5. 风险与取舍

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| LangGraph 依赖与 pydantic 2.13.5 / fastapi 0.141.1 冲突 | 装不上或污染现有 840 条测试 | Phase 0 独立验证，冲突就停下报告，不留半成品 |
| 图内 `asyncio.run` 嵌套 | 运行时崩溃 | 硬规则：节点内只用 `await`，同步调用走 `asyncio.to_thread` |
| 单例 LLM 客户端绑死事件循环 | **静默失败**（Safety 阶段已实测踩到） | 每轮新建并关闭客户端；写成测试 |
| 本地追问漏记话题 → 收不了尾 | 筛查流程失控 | `active_topic` + `test_screening_constraints_preserved.py` |
| Dialogue 自主后话题覆盖率下降 | 演示闭环不完整 | 后端强制规则；`test_decision_budget_evidence.py` 同时对比**调用次数**与**话题覆盖** |
| 模型不返回合法 JSON | 丢轮次 | 解析容忍纯文本回退（按单条消息 + 不需要决策处理） |
| 前端无自动化测试 | 多气泡改动无回归网 | 只能靠 `vue-tsc` + 演示前人工走查；建议后续补 Vitest，但本期不作为重点 |
| 每轮多一次 LLM 调用（Visual Review） | 延迟增加 | Review 以确定性规则为主，只有命中才触发重写，且预算 1 |

### 明确**不做**的事（遵循你的开发原则）

- 不重构评估 Agent、报告生成、治愈模块（本期只动实时筛查对话链路）。
- 不重训 Qwen3-8B 策略模型，不改 `backend/policy/**`。
- 不引入 LangGraph Checkpointer（`SessionState` 仍是唯一权威状态）。
- 不做高并发/分布式/多实例。
- 不加新 Agent；节点是对**现有**能力的编排，不是新 Agent。

---

## 6. 需要你确认的决策点

1. **Phase 0 是否允许安装 `langgraph`**（会拉入 `langchain-core`，需走代理）。
   当前环境完全干净，安装是本次改造的前置条件。
2. **`DIALOGUE_ENGINE` 默认值**：建议 Phase 1~2 期间默认 `legacy`，
   Phase 3 全绿后翻成 `graph`，并保留 `legacy` 作为演示当天的回退开关。
3. **Visual Review 是否允许消耗一次额外的 LLM 调用**（仅在规则命中时）。
   若你希望演示延迟最低，可以只做确定性规则改写、不调模型。
4. **`reply` 字段何时移除**：建议 Phase 4 保留兼容、演示结束后再清理，
   避免前端与外部文档同时改动。
5. **是否要我把 trace 暴露到 HTTP 响应**（演示场景 B 需要）。
   默认关闭、演示时开，避免污染学生可见契约。

---

## 7. 本轮未做的事

- **未修改任何代码**，未安装任何依赖（你要求"先输出实施计划，不要一次性修改所有模块"）。
- 本文档中所有行号引用均来自当前工作区实际文件，可逐一核对。
- 上一阶段（Safety 替换）的成果保持原样：全量 **840 passed / 0 failed**。
