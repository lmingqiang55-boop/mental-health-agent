# 架构说明 v0.2

本文档把目标效果图（`docs/assets/target_architecture.png`）与仓库中的真实
代码一一对应。当前版本只搭建**框架骨架与数据协议**，具体识别/生成算法用
Mock 或规则占位。

## 1. 总体分层

```text
┌──────────────────────────────────────────────────────────────┐
│        知识库与规则库（公共底座） backend/rag + llm/prompts   │
│  标准量表 · 评估维度 · 对话规则 · 风险规则 · 心理健康知识     │
└───────┬──────────────────────────────────────┬───────────────┘
        │ 提供知识与规则                         │ 提供知识与规则
        ↓                                       ↓
┌──────────────────────────┐      ┌────────────────────────────┐
│ ① 实时对话闭环           │      │ ② 多模态综合评估           │
│   DialogueManager (A)    │ 完整 │   AssessmentEngine (A+B)   │
│   Vision/Audio (B)       │ ───→ │   生成维度得分/风险/建议   │
│   边聊边感知·动态引导    │ 对话 │                            │
└───────────┬──────────────┘      └──────────────┬─────────────┘
            │                                    ↓
            │                         ┌────────────────────┐
            │   历史筛查结果（回流）   │  评估记忆库 (C)     │
            └─────────────────────────│  MemoryStore       │
                                      └──────────┬─────────┘
                                                 ↓
┌────────────────────────────┐   ┌────────────────────────────┐
│ 学生端展示（个人视角）(C)  │←→│ 心理老师端展示（专业视角）(C)│
│ 结果 · 建议 · 求助         │沟通│ 个体管理·预警·群体统计     │
└────────────────────────────┘   └────────────────────────────┘

        隐私与安全保障（贯穿全流程）：知情同意 · 身份权限 ·
        数据安全 · 匿名化 · 人工复核
```

## 2. 目标图模块 → 代码映射

| 目标图模块 | 代码位置 | 当前状态 |
| --- | --- | --- |
| 知识库与规则库 | `backend/rag/knowledge/`、`backend/rag/retriever.py`、`backend/llm/prompts.py` | 演示片段 + 关键词检索（带缓存） |
| 标准心理量表 | — | 未接入，接入前需确认授权与计分规则 |
| 对话 Agent | `backend/core/dialogue_manager.py` | 决策模型选动作 + 危机干预；无规则回退 |
| 微表情/眼动检测 | `backend/vision/detector.py` | Mock + 可选 EmotiEffLib 情绪/VA |
| 语音输入/ASR | `backend/audio/analyzer.py` | 抽象接口 + Mock |
| 句级视觉状态（实时） | `VisionState` | 已定义，merge 写入 |
| 多模态融合 | `backend/core/multimodal_fusion.py` | 句级融合 + 会话级汇总 |
| 风险识别规则 | `backend/core/risk_engine.py` | 规则式，含否定词处理 + 多模态调整 |
| 多模态心理评估 Agent | `backend/core/assessment_engine.py` | 规则式打分 + 建议生成 |
| 评估结果输出 | `backend/models/assessment.py` | 已定义 |
| 评估记忆库 | `backend/core/memory_store.py` | 进程内存储 |
| 历史结果回流 | `MemoryStore.latest_for_student` | 接口已预留 |
| 学生端 | `frontend/src/pages/StudentPage.jsx` | 对话 + 进度 + 设备 + 结果 |
| 心理老师端 | `frontend/src/pages/TeacherPage.jsx` | 三标签骨架 |
| 双向互动沟通 | `backend/core/communication.py` | 进程内消息存储 |
| 隐私与安全 | `ConsentRecord`、`backend/api/session.py` | 知情同意接口；认证待开发 |

## 3. 两条核心数据流

### 实时对话闭环（模块 ①）

```text
学生文字 ──→ POST /api/chat
                 │ (SessionManager.modify_session 原子操作)
                 ↓
        句级 VisionState/AudioState（POST /api/vision/frame、/api/vision、/api/audio）
                 ↓
        fuse_turn 多模态融合
                 ↓
        assess_risk 风险评估
                 ↓
        决策模型（backend/policy/）选择下一步动作
                 ↓
        本地基础话术生成 reply（危机时走 crisis_support）
                 ↓
        返回 { reply, next_strategy, current_stage, risk, turn_count }

模型不可用 → 503 POLICY_UNAVAILABLE，本轮不落库，不退回规则提问
```

### 多模态综合评估（模块 ②）

```text
POST /api/assessment（显式触发；对话没有自动结束信号）
        ↓
build_vision_summary / build_audio_summary（聚合句级日志）
        ↓
AssessmentEngine.assess(session)
        ↓
DimensionScore[] + RiskResult + Recommendation[]
        ↓
MemoryStore.save_result → AssessmentRecord
        ↓
学生端结果页 / 老师端记录列表
```

## 4. 模块隔离规则

```text
backend/models/        公共插头标准，三人共享，变更走评审流程
backend/core/
    dialogue_manager   A：问什么（大脑）
    risk_engine        A：风险规则
    assessment_engine  A+B：最终评估
    multimodal_fusion  B：多模态融合
    session_manager    C：会话生命周期
    memory_store       C：评估记忆库
    communication      C：双向沟通
backend/llm/           A：怎么表达（可替换 Provider）
backend/rag/           A：知识检索
backend/vision/        B：眼睛（可替换模型）
backend/audio/         B：耳朵（可替换模型）
backend/api/           C：HTTP 编排，不含业务推理
frontend/              C：双端界面
```

模块之间只通过 `backend/models/` 的数据结构连接：

- B → A：`VisionState` / `AudioState` / 会话级 Summary
- A → C：`DialogueResponsePayload` / `AssessmentResult`
- C 负责编排和存储，不在前端写提问规则
- 各模块通过抽象基类 + 工厂函数（`get_detector` / `get_llm_client` 等）
  注入实现，替换算法不影响其他模块

## 5. 并发与一致性

- 所有「读-改-写」会话的操作走 `SessionManager.modify_session`，
  在同一把锁内完成，消除 chat 与 vision/audio 之间的 lost-update。
- vision/audio 提交为 merge 语义，不会全量重置。
- 记忆库与沟通模块各有独立锁；评估与存储在会话锁外执行，避免嵌套锁。

## 6. 当前限制

- 对话依赖本机决策模型服务（`backend/policy/`，OpenAI 兼容
  `POST /v1/chat/completions`）：服务未启动或输出无效时 `/api/chat` 返回
  `503 POLICY_UNAVAILABLE`，没有规则兜底路径。
- Session / 记忆库 / 沟通消息均为单进程内存，TTL 2 小时，重启清空，
  不支持多 worker。
- 默认视觉仍为 Mock；EmotiEffLib 真实模型需单独安装并设置 provider，结果可能误报或漏报。
- 无身份认证与权限控制，老师端接口在接入认证前不得连接真实学生数据。
- 所有输出统一标注「初步筛查提示」，不构成临床诊断。

## 7. 后续替换点

按依赖顺序：真实 LLM Provider → 真实视觉模型 → 真实音频/ASR →
持久化数据库 → 身份与权限 → 标准量表 → 人工复核闭环。
每项替换前先更新 `api_spec.md` 与本文档。
