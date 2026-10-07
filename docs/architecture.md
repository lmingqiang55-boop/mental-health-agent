# 当前架构与数据流（2026-10-04）

本文件描述仓库当前实现；目标研究图见 `assets/target_architecture.png`，不代表全部能力已实现。HTTP 协议见 [API 数据协议](api_spec.md)，设备及时间对齐细节见 [摄像头与录音对接](vision_alignment.md)。

## 分层

| 层 | 代码 | 当前能力 |
| --- | --- | --- |
| 页面与设备 | `frontend/src/pages/StudentPage.jsx`、`media/capture.js` | 文字、按住/松开录音、摄像头、取消、失败重试、结果展示 |
| 视觉输入 | `backend/api/vision.py`、`vision/detector.py`、`vision/aggregation.py` | 采集代次、单帧情绪/VA、带时间帧缓存、逐句区间聚合、冻结快照 |
| 语音输入 | `backend/audio/`、`api/audio.py` | SenseVoice 整段识别、真实解码重采样、容量限制、录音元数据 |
| 会话 | `backend/core/session_manager.py` | 原子修改、消息及幂等回执、TTL；进程内存 |
| 对话 | `backend/core/dialogue_manager.py`、`backend/policy/` | 文本历史驱动策略动作、基础话术、独立规则式风险识别 |
| 综合评估 | `backend/core/evaluation_engine.py`、`evaluation_agent/` | 对话原文及双层视觉输入、11 项评分、五维画像、关注指数 |
| 报告与记录 | `backend/core/report_builder.py`、`memory_store.py` | 规则模板报告、结果索引及查询；每位匿名用户最近 3 次结果保存在本机 SQLite |
| 治愈陪伴 | `core/healing_adapter.py`、`healing/`、`api/healing.py` | 从真实记忆适配输入、检索知识、支持报告及反馈；陪伴状态独立保存在进程内存，前端待对接 |
| 教师与沟通 | `api/teacher.py`、`core/communication.py` | 记录列表、备注与沟通骨架 |

## 实时路径

```text
完整录音 → /api/audio/transcribe → text + utterance_id + speech
带采集时间的帧 → /api/vision/frame → 结构化缓存
录音区间 → /api/vision/segment → 冻结的 vision_snapshot
两路汇合 → /api/chat → 保存当前消息
                        ├─ fuse_turn → 规则式风险辅助
                        └─ 文本历史 → 本机决策模型 → 动作 → 基础话术
```

策略模型只读取文本历史，不把视觉指标送入策略提示词。视觉指标用于规则式风险辅助及最终评估。模型不可用返回 `POLICY_UNAVAILABLE`，当前轮不保存，不使用旧六维规则兜底。对话不自动结束，用户明确触发评估。

文字路径使用本次输入期间的视觉聚合；未开启摄像头时明确传 null，避免借用旧状态。未升级的文字客户端仅可在实时风险计算中借用最近 5 秒的视觉状态，不将单帧保存为逐句证据。

## 最终评估路径

```text
/api/assessment {session_id}
  → 按消息顺序读取 user 消息已绑定的快照
  → build_vision_summary（句级样本等权）
  → EvaluationInput（原文 + 每条消息快照 + 会话汇总）
  → EvaluationEngine / EvaluationService
  → 五维画像 + concern_index + overall_level + 独立 risk
  → report → MemoryStore → 学生端 / 教师端查询
```

完整 `evaluation_input` 仍用于外部上游导入。省略原快照不清空它；改写已绑定视觉或录音元数据返回 `HISTORY_CONFLICT`。评估过程中历史发生变化时返回冲突，不链接旧报告。帧日志不直接当作句级样本，评估端不重算时间对齐。

## 一致性与资源生命周期

- 会话写入使用 `modify_session`；模型失败不留下半轮消息。
- 采集 generation 单调递增，旧开启/关闭不覆盖新采集；帧在推理前和写回前检查当前采集。
- 区间结果按 utterance_id 冻结；重试与晚到帧不改变原结果。
- 摄像头关闭清空最新状态，前端停止 tracks、定时器和在途请求；权限等待也可取消。
- ASR 串行工作线程与上传前容量预留继续沿用；视觉初始化与同实例推理加锁。
- 帧缓存及实时视觉日志最多 512 条；不保存原图或录音。

## 治愈陪伴路径

```text
评估成功 → MemoryStore 按现有流程保存结果
用户明确进入 → /api/healing/start
  → healing_adapter 在填默认值前检查原始风险字段，读取最近三次结果与可选背景
  → 风险分流、多诉求优先方向确认
  → 年龄/学段、场景、执行者与前提过滤 → 中文 BM25 → 明确个人条件适配
  → 模型共情及选择知识 → 依据/单问题检查 → 确定性呈现知识步骤
用户反馈 → /api/healing/chat → 独立历史、执行状态、效果、已校验的表达简化及调整
```

治愈 Agent 不访问或写入数据库，不把陪伴消息加入筛查历史，也不调用评估 Agent。
适配层明确区分持久化评估、当前进程中最多最近 20 条用户消息和调用方明确提供的背景。
新风险沿用现有求助话术，不自动发送教师或家长通知。
接口、状态切换、知识覆盖和验证记录见 [治愈 Agent 交接](healing_agent.md)。

## 当前边界

本期采用按钮录音，不实现 VAD 或流式 ASR。EmotiEffLib 只提供情绪/VA，未实现眼动、微表情和参与度时间模型；这些字段保持缺测。默认视觉 Mock 仅用于虚构数据演示；真实视觉需安装并配置 `VISION_PROVIDER=emotiefflib`，语音需 `ASR_PROVIDER=sensevoice`。

会话仍为单进程内存，重启清空；评估结果持久保留最近 3 次，但匿名标识不是身份认证。沟通记录、身份授权、访问审计、专业危机响应与评分效度仍需单独完成。历史审查见 [2026-10-01 记录](prelaunch_audit_2026-10-01.md)。真人发音、摄像头光照/角度、不同浏览器编码器和全链路延迟仍须单独验收。
