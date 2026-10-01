# 上线前审查（2026-10-01）

审查基线：GitHub `main` 的 `55bea63d47c0e43a914556fcdff19ef83300f7d3`。本次修复在本地 `codex/prelaunch-fixes` 分支，尚未合入 `main`。本报告审查**真实学生使用**所需条件；这些事项不阻止只使用虚构数据的 MVB 演示。MVB 对话数据流的验收方式见 [README](../README.md#对话数据流验收mvb)。

## 已验证

- 原始 `main`：后端 28 项测试通过，前端 `npm run build` 通过。现有测试未覆盖权限、同意、危机漏报及人工响应。
- 本次修复后：后端 33 项测试通过，前端生产构建通过；其中两项使用模拟外部模型响应验证对话到评估及上游两级视觉输入的数据流。
- `POST /api/assessment` 成功后，原先使用返回的 `result_id` 调用 `GET /api/assessment/result/{result_id}` 会得到 404：存储按另一个随机 `record_id` 索引。本次增加结果 ID 索引和会话 ID 匹配检查，并加入回归测试。
- `PROMPT_VERSION=1.2` 的未成年人证据边界与评分 rubric 已从独立评估 Agent 同步，增加相关测试。同步的是提示词和评分口径，尚未对最终分数做年龄分层效度验证。
- 前端“开启麦克风”原先不采集声音，却会向后端提交固定的音频特征；现改为“语音功能待接入”。重新开始会话时也会停止旧摄像头采样。

## 阻止真实用户上线的问题

| 优先级 | 现状和证据 | 上线条件 |
| --- | --- | --- |
| P0：学生信息访问控制 | `backend/api/teacher.py` 明确写明尚无身份认证；`/api/teacher/records`、`/api/teacher/high-risk`、`/api/history/{student_ref}`、`/api/communication/{student_ref}` 等接口未检查登录身份和访问范围。未登录请求 `/api/teacher/high-risk` 返回 200。前端可直接切换到教师端。 | 建立可靠的身份认证、学生与教师角色授权、学校或班级范围隔离；对读取、写入及越权访问做端到端测试。 |
| P0：危机漏报与人工响应缺失 | `backend/core/risk_engine.py` 是有限关键词 Demo。实测“我不想活”“我有自杀计划”“我想跳楼”“我刚割了手腕”未命中高风险词。另一次接口实测“我想自杀”使 `/api/chat` 返回 `high`，但 `/api/teacher/high-risk` 仍返回 0：教师列表仅查询已完成的评估记录。学生不点击生成结果或评估服务失败时，危机消息不会进入该列表。 | 与专业人员制定年龄适配的安全识别与人工升级流程，覆盖即时告警、责任人、响应时限、失败重试和处置记录；用代表性中文语料验证漏报与误报。低关注评分不得覆盖安全风险。 |
| P0：未执行同意状态 | 新会话 `consent.status=not_provided`，但实测 `/api/chat` 仍返回 200；`backend/api/chat.py`、`backend/api/vision.py`、`backend/api/assessment.py` 均未据此阻止处理。浏览器摄像头权限也不等于项目的数据处理同意。 | 明确学生与监护人的适用同意流程及数据用途；后端按同意范围执行，撤回后停止后续采集和处理，并测试。 |
| P0：关键记录仅在进程内存 | `backend/core/memory_store.py`、`backend/core/session_manager.py`、`backend/core/communication.py` 都使用进程内对象。重启会丢失评估、会话和沟通记录；多进程实例也不会共享数据。 | 持久化、访问审计、备份恢复、数据保留和删除策略，以及可靠的危机事件队列与交接记录。 |
| P1：评估输入可信边界 | `POST /api/assessment` 接受调用方传入的 `evaluation_input.dialogue_history`，并在完成后替换会话历史。当前没有验证调用方是否为可信上游，也不核对提交内容与既有会话一致。 | 对上游服务鉴权；绑定提交内容与学生身份和会话，保留原始与修订记录及审计轨迹。 |
| P1：评分解释与验证 | 页面展示 0～100 的 `concern_index` 和关注等级。项目未提供该分数在中小学生中的年龄适配、校准、误差及转介阈值证据；风险引擎还把视觉效价等作为中风险依据。 | 明确适用年龄和用途，开展独立验证并评估各年龄段误差；在人审及后续服务到位前，不把分数用作诊断或排除风险的结论。 |
| P2：生产部署接线 | 前端 API 使用相对路径 `/api`，`frontend/vite.config.js` 的代理只用于开发服务器；仓库中没有生产反向代理或同源部署配置。 | 在目标环境配置 `/api` 到后端，并进行真实部署环境的端到端、故障恢复及权限验证。 |

## 研究与实践依据

- [USPSTF 儿童青少年抑郁及自杀风险筛查建议](https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/screening-depression-suicide-risk-children-adolescents)：12～18 岁抑郁筛查有证据支持；11 岁及以下常规筛查的获益与风险证据不足。筛查实施需要能完成后续评估和照护的人员与体系。本项目自定义 11 项评分不能直接等同于经过验证的临床工具。
- [AAP 青少年自杀风险筛查说明](https://www.aap.org/en/patient-care/blueprint-for-youth-suicide-prevention/strategies-for-clinical-settings-for-youth-suicide-prevention/screening-for-suicide-risk-in-clinical-practice/)：抑郁筛查不能替代独立的自杀风险识别；对阳性者应开展进一步安全评估。
- [NIMH ASQ 工具包](https://www.nimh.nih.gov/research/research-conducted-at-nimh/asq-toolkit-materials)：在医疗场景筛查前要有处理阳性结果的路径；阳性后由受训人员进一步评估。其适用范围是医疗场景 8 岁及以上，不能直接把该工具包当成本项目的自动化实现或小学生全龄适用依据。

## 本次验证边界

后端测试使用离线模型替身；未使用真实决策模型、DeepSeek 密钥、真实学生数据或部署环境。尚未进行临床效度、渗透、并发、故障恢复测试。以上测试通过只说明已覆盖的代码路径运行正常。
