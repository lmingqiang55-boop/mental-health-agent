# v0.1 三人协作开发手册

本文件是三个人的工作边界和联调约定。先让三个部分分别依照稳定接口工作，再把替换后的模块接入同一个本地 Demo。当前代码是可运行的起点，不意味着真实多模态识别、临床判断、持久化用户系统或第二个前端已经完成。

## 1. 本轮目标与现状

| 能力 | 当前状态 | 本轮协作目标 |
| --- | --- | --- |
| 文字对话、六维度提问、Mock LLM | 已可运行 | 对话负责人改进提问逻辑，保留 Mock 模式 |
| VisionState、AudioState 接口 | 已可接收结构化 Mock 数据 | 多模态负责人在接口后接真实分析模块，先完成可替换的输出 |
| 学生端基础聊天页面 | 已可运行 | 前端负责人维护体验和错误处理；结果、历史和建议页面待开发 |
| 医生/心理老师端（专业端） | 尚无代码 | 前端负责人先用合成数据建立页面骨架；个体管理、预警、统计和互动须分阶段接入 |
| Session 数据 | 仅后端进程内存；重启丢失 | 前端与用户数据负责人定义数据字段、读取与删除流程；持久化作为后续任务 |

**当前 v0.1 已有基线的验收**：本地从学生聊天页创建 Session，输入多轮文字，看到下一问和风险等级；Vision/Audio 状态可通过 API 写入同一 Session；无摄像头、麦克风或 LLM Key 仍能跑完整流程；测试通过。**三人协作的下一交付**：建立学生端与专业端两个清晰入口，并用合成数据打通结果展示；真实用户管理和专业端访问控制在方案确定前不得宣称完成。产品范围见 [MVP 范围与双端规划](mvp_scope.md)。

## 2. 三个人的职责

用 **A：对话**、**B：多模态**、**C：双前端与用户数据** 指代三位成员，不指定具体姓名。

| 成员 | 主要负责的代码 | 交付与验收 | 不直接修改的边界 |
| --- | --- | --- | --- |
| A 对话 | `backend/core/dialogue_manager.py`、`risk_engine.py`、`backend/llm/`、`backend/rag/`、`backend/api/chat.py` | `process_turn()` 能稳定选下一问；无 LLM Key 仍可回复；风险只作提示；补对话测试 | 不直接改 Vision/Audio 输出字段、Session 存储结构或前端页面 |
| B 多模态 | `backend/vision/`、`backend/audio/`、`backend/core/multimodal_fusion.py`、`backend/api/vision.py`、`backend/api/audio.py`；`models/states.py` 中 VisionState/AudioState 字段 | 接收并校验状态；缺少任一模态时仍能聊天；给出字段含义和单位；补模态 API 测试 | 不把模型推理塞进对话状态机或前端；不直接改变聊天响应 |
| C 双前端与用户数据 | `frontend/`、`backend/core/session_manager.py`、`backend/api/session.py`；`models/states.py` 中 SessionState/Message 字段 | 学生端能创建会话、聊天和查看自身状态；专业端建立独立入口与合成数据页面；定义结果、历史及反馈的数据契约；Session 创建、读取、删除有测试 | 不把提问策略写进前端；不直接修改多模态算法或对话决策 |

共用文件的协调：`backend/models/states.py` 由字段所属负责人改动；`backend/main.py`、`docs/api_spec.md` 和跨模块测试由提出接口变化的人更新，另外两人审阅。接口字段的新增、重命名、删除，先在 `docs/api_spec.md` 写明请求和响应，再合并代码。不要让三个人同时编辑同一文件。

## 3. 固定接口与数据归属

### A ↔ C：文字对话

- C 调用 `POST /api/session` 获得 `session_id`，之后 `POST /api/chat` 提交 `{ "session_id": "...", "text": "..." }`。
- A 的聊天响应至少包含 `reply`、`next_strategy`、`current_stage`、`risk`；API 还返回 `session_id`、`turn_count`。C 只负责显示这些字段，不根据关键词自行决定下一问或风险。
- `DialogueManager.process_turn(user_text, session_state, vision_state=None, audio_state=None)` 是 A 的入口。A 决定“问什么”；`LLMClient.generate_reply(...)` 决定“怎么表达”。
- C 的 SessionManager 保存完整 `conversation_history`、`turn_count`、`assessment_state`、最新状态。A 修改 Session 中的评估进度后，由聊天 API 一次写回。每个成功的用户请求算一个 turn，历史增加一条 user 和一条 assistant 消息。

### B ↔ A：多模态状态

- B 输出 `VisionState` / `AudioState`，通过 `POST /api/vision` / `POST /api/audio` 写入指定 Session。字段契约见 `models/states.py` 和 `docs/api_spec.md`。
- A 可以读取 `latest_vision_state`、`latest_audio_state`，但必须接受 `None`。空值表示该模态尚未提供，不能推断用户状态正常或异常。
- `fuse(user_text, vision_state=None, audio_state=None)` 是融合入口。当前仅返回可用性标志；B 替换实现时须保留无模态输入的可运行路径。原始摄像头帧和录音不写进 Session。
- 多模态输出若新增数值，B 要写清范围、单位、缺失值、更新频率和计算方式；A 确认用法后才将它用于提问策略。

### C ↔ 后端：双前端与用户数据

- 两个前端分别是**学生端**和**医生/心理老师端（专业端）**，都只通过 `/api` 访问后端，不直接读取 Python 内存，也不各自维护另一份权威 Session。
- 学生端的目标是语音/文字交流、查看本次结果与历史趋势、获取个性化建议；现有代码只有文字聊天和当前状态显示。语音、摄像头、完整结果、历史趋势仍待开发。
- 专业端的目标是个体筛查管理、高风险预警与人工跟进、群体趋势统计，以及与学生双向沟通。**当前没有专业端页面、用户账户、Session 列表、跨用户查询或反馈 API**。页面骨架只可使用合成数据；在明确身份、授权和可见范围前，不连接真实学生数据。
- v0.1 的“用户数据”仅指 Session ID、对话历史、回合数、阶段、评估状态、最新 Vision/Audio 状态和风险提示。没有实名身份、账号、登录或数据库。`session_id` 是会话定位符，不是用户身份。
- C 若要引入 `user_id`、持久化或多会话管理，应先写数据字典和迁移方案，与 A/B 确认字段，再改 Session 模型与 API。心理状态数据只用合成样例联调，不提交真实个人对话。

## 4. 目录与文件修改约定

```text
backend/api/       HTTP 输入输出和校验；不要放模型推理或页面状态
backend/core/      对话决策、Session 存储、风险规则、融合入口
backend/models/    三方共享的 Pydantic 契约
backend/llm/       Mock 或真实文本生成，不能接管提问策略
backend/rag/       本地知识片段与 retrieve(query, top_k)
backend/vision/    视觉分析模块
backend/audio/     音频分析模块
frontend/          当前学生聊天页；专业端尚未建立，新增入口时保持双端代码边界
tests/             按 API 行为验证，不依赖真实模型和密钥
docs/              接口、架构、分工与联调说明
```

`backend/rag/knowledge/demo_knowledge.md` 只存演示知识。增加心理知识时记录来源和适用范围，不把未经核查的资料表述为临床结论。

## 5. 并行开发与合并顺序

1. **冻结 v0.1 契约**：三人先阅读 `docs/api_spec.md`、`backend/models/states.py` 和本文件。讨论需要新增的字段，写入文档后再动共享模型。
2. **各自开发**：A 使用现有 Mock Vision/Audio 与 Session；B 使用测试 Session 向接口提交状态；C 使用现有 Mock LLM 和 API 做两个前端及数据流程。任一部分不应等待其他人的真实模型完成。
3. **模块内检查**：各负责人补自己边界上的必要测试或手工用例；不要以真实模型、真实用户数据或外部密钥作为基础测试前提。
4. **按依赖合并**：先合并共享模型和 API 契约，再合并 A/B 的后端替换，最后合并 C 的前端与数据流程；每次合并后运行完整测试和前端构建。
5. **端到端联调**：创建 Session → 连续发两条文字 → 查询历史 → 提交 Vision/Audio Mock 状态 → 再聊天 → 创建新 Session。核对回合数、状态归属和错误响应。专业端用合成数据检查页面结构，不将现有 `GET /api/session/{id}` 当作跨学生查询权限。

建议每人从自己的功能分支提交小改动；PR/合并说明至少写：修改的接口字段、受影响的成员、验证命令和结果、尚未完成的 TODO。共享字段变更需要相关两位负责人确认后合并。

## 6. 本地验收命令与用例

在项目根目录运行：

```powershell
python -m pytest -q
cd frontend
npm run build
```

手工用例：

| 场景 | 预期 |
| --- | --- |
| 未配置 LLM Key，打开学生端 | 自动创建 Session，可发送消息 |
| 连续发送两条文字 | 两次有非空回复；`turn_count=2`；历史有 4 条消息 |
| 没有视觉/音频状态时聊天 | 正常返回，不报错 |
| 向同一 Session 提交 Vision/Audio 状态 | `GET /api/session/{id}` 可看到最新状态 |
| 错误 Session ID | HTTP 404；`error.code=SESSION_NOT_FOUND` |
| 空白文本 | HTTP 422；`error.code=VALIDATION_ERROR` |
| 创建新会话 | 新 ID、回合数归零，前端清空对话 |

## 7. 数据与安全边界

- 当前 Session 只在单进程内存，服务重启即清空，不适合保存正式用户资料，也不支持多 worker 共享。
- 风险分级是关键词 Demo，可能误报或漏报。UI 和文档统一写“初步筛查 / 风险提示”，不能声称诊断或治疗。
- 不提交 `.env`、API Key、`.venv`、`node_modules`、原始音视频或真实用户对话。
- 专业端展示个体结果或群体数据前，先明确学生知情同意、医生/心理老师身份、可见范围、脱敏规则和人工复核流程。群体统计只展示聚合结果。

## 8. 留给后续版本的 TODO

真实 LLM Provider、知识来源审核、视觉/音频模型、数据持久化、身份与权限、更可靠的风险评估、学生端结果/趋势/建议、专业端个体管理/预警/统计/互动。每项都先更新契约与验收标准，再实现。
