# 历史记录索引

这里保存阶段验收、修复过程及当时的完成声明。文档中的测试数量、已知问题和模型结果保留原版本范围；当前入口见 [文档索引](../README.md)。

## 按模块查阅

- `healing/`：2026-10-06 至 2026-10-07 的治愈模块阶段记录。
- `dialogue/`：对话、消息拆分、视觉关怀及 Trace 的阶段记录。
- `audio/`：语音链路阶段验收。

## 文件位置对照

| 归档文档 | 原路径 |
| --- | --- |
| [对话流程修复验证（2026-10-11）](dialogue/dialogue_flow_validation_20261011.md) | `docs/dialogue_flow_validation_20261011.md` |
| [成人支持的对话确认与验证](healing/healing_adult_support_20261006.md) | `docs/healing_adult_support_20261006.md` |
| [治愈 Agent 竞赛演示版完成里程碑（2026-10-07）](healing/healing_completion_20261007.md) | `docs/healing_completion_20261007.md` |
| [陪伴问题、双方法失败路径与检索收尾](healing/healing_conversation_fix_20261006.md) | `docs/healing_conversation_fix_20261006.md` |
| [治愈 Agent 本地交付（2026-10-07）](healing/healing_delivery_20261007.md) | `docs/healing_delivery_20261007.md` |
| [2026-10-06：反馈修复与最新真实模型、陪伴体验验收](healing/healing_feedback_acceptance_20261006.md) | `docs/healing_feedback_acceptance_20261006.md` |
| [治愈 Agent 最终合成验收与本地收尾（2026-10-07）](healing/healing_final_acceptance_20261007.md) | `docs/healing_final_acceptance_20261007.md` |
| [2026-10-06：保留准备状态并另记尚未尝试反馈](healing/healing_prepared_feedback_20261006.md) | `docs/healing_prepared_feedback_20261006.md` |
| [提交前审查修复与验证（2026-10-07）](healing/healing_review_fix_20261007.md) | `docs/healing_review_fix_20261007.md` |
| [治愈报告风险同步修复与背景字段评估](healing/healing_risk_refresh_20261006.md) | `docs/healing_risk_refresh_20261006.md` |
| [2026-10-06 最新接口、背景边界与扩充库检索验证](healing/healing_validation_20261006.md) | `docs/healing_validation_20261006.md` |
| [Phase 2.5 真实模型对话验收记录（legacy 引擎）](dialogue/phase25_legacy_baseline_log.md) | `docs/phase25_legacy_baseline_log.md` |
| [Phase 2.5 真实模型对话效果验收报告](dialogue/phase25_real_dialogue_findings.md) | `docs/phase25_real_dialogue_findings.md` |
| [Phase 2.5 真实模型对话验收记录（graph 引擎）](dialogue/phase25_real_dialogue_log.md) | `docs/phase25_real_dialogue_log.md` |
| [Phase 4 真实模型分段验证（Dialogue 输出 1~3 条消息）](dialogue/phase4_message_split_log.md) | `docs/phase4_message_split_log.md` |
| [Phase 5 视觉关怀话术验证（真实模型 + 预设视觉标签）](dialogue/phase5_visual_care_log.md) | `docs/phase5_visual_care_log.md` |
| [Phase 6 多智能体运行轨迹验证（真实模型）](dialogue/phase6_trace_log.md) | `docs/phase6_trace_log.md` |
| [语音识别实现与验证记录](audio/speech_validation_2026-10-02.md) | `docs/speech_validation_2026-10-02.md` |

## 原始证据

完整回放继续保存在 [docs/examples/](../examples/README.md)，知识库与来源记录继续保存在原路径。归档调整 Markdown 文档位置、修正引用，并将 4 个阶段验证脚本的默认报告输出同步到 `docs/archive/dialogue/`；应用代码、测试、模型配置和 JSON 回放未移动。
