# v0.1 架构

> 下图描述原有 `/api/chat` Demo。新增的 `/api/assessment` 是独立的九项测评状态机：`规则 Mock 或 OpenAI 兼容模型抽取 → 原话和频率校验 → 证据状态与冲突检查 → 下一问策略 → 完整时程序计分`。该路径当前仍使用进程内 Session；模型适配器已有模拟响应测试，尚未用真实服务端到端验收，也未接学生前端。参见 [测评契约](assessment_contract.md) 与 [API](api_spec.md)。

```text
学生端（当前：基础文字聊天页） ─┐
                            ├── HTTP /api ──> FastAPI routes
医生/心理老师端（规划中） ────┘                     ├── SessionManager (进程内字典)
                                                ├── DialogueManager (决定下一问)
                                                │    ├── Risk Engine (关键词提示)
                                                │    ├── Multimodal Fusion (状态占位)
                                                │    ├── Retriever (本地 Markdown 匹配)
                                                │    └── LLMClient (Mock 模板措辞)
                                                └── Vision / Audio routes (存储 Mock 状态)
```

每次聊天在同一 Session 中保存用户和助手消息，并更新回合数、评估维度、阶段和最新风险。六个维度依次为 mood、interest、sleep、energy、concentration、duration；状态为 pending、in_progress、covered。DialogueManager 选策略，LLMClient 负责文字。当前 Mock LLM 不使用检索结果生成新内容，但检索接口已经接入调用路径。

内存 Session 适合单进程本地 Demo；服务重启后数据消失，多 worker 不共享数据。视觉和音频接口仅保存结构化状态，不上传或分析原始媒体。规则风险提示可能漏报或误报，不是临床评估。

当前只存在学生聊天页和单个 Session 的 API。图中的学生结果/历史、专业端个体查看/预警/统计/互动，以及评估记录库均未实现。专业端未来要访问学生数据，必须先定义学生同意、专业身份、授权范围和人工复核；不能把 `session_id` 当访问控制。完整功能映射见 [MVP 范围与双端规划](mvp_scope.md)。

后续替换点：`backend/llm/client.py`、`backend/rag/retriever.py`、`backend/core/multimodal_fusion.py`、`backend/vision/detector.py`、`backend/audio/analyzer.py`。
