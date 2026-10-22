# 项目文档索引

运行项目从 [根目录 README](../README.md) 开始。日常使用 Vue 学生端和管理端；旧 React 原型保留用于对照及媒体测试。

## 安装与协作

- [队友本地运行指南](队友本地运行指南.md)
- [环境配置与验证](environment.md)
- [队友更新须知](队友更新须知.md)
- [三人协作与接口分工](三人协作与接口分工_v3.md)

## 接口与前端

- [API 数据协议](api_spec.md)
- [Vue 前端运行说明](../frontend-vue/README.md)
- [新版前端接入说明](../frontend-vue/docs/新前端接入说明.md)
- [管理端对接文档](../frontend-vue/docs/管理端-对接文档.md)
- [评估结果页面交接](assessment_output_page_handoff.md)
- [旧 React 原型](../frontend/README.md)与[旧交接记录](前端交接文档.md)

## 后端模块与架构

- [架构记录（2026-10-04）](architecture.md)
- [对话流程交接](dialogue_flow_handoff.md)
- [测评问诊职责与表达调整（2026-10-20）](archive/dialogue/dialogue_interview_scope_20261020.md)
- [对话提示词优化依据与范围（2026-10-20）](archive/dialogue/dialogue_prompt_naturalness_20261020.md)
- [LangGraph 工作流规划](langgraph_workflow_plan.md)
- [Safety Agent 替换记录](safety_agent_replacement_report.md)
- [语音识别说明](speech_recognition.md)
- [摄像头与录音对接](vision_alignment.md)
- [视觉采集缺陷报告（2026-10-16）](vision_capture_defect_report_20261016.md)
- [治愈 Agent 接口与交接](healing_agent.md)
- [治愈知识扩展记录](healing_knowledge_expansion.md)
- [治愈知识审核记录](healing_knowledge_review.md)
- [治愈验证记录](healing_validation.md)
- [治愈资料与软件许可](healing_sources_and_licenses.md)

## 演示、示例与历史

- [演示场景](demo_scenarios.md)与[场景记录](demo_scenario_records.md)
- [Trace 演示指南](phase6_demo_guide.md)
- [对话提示词 35 次真实调用实录（2026-10-20）](archive/dialogue/dialogue_prompt_ab_20261020.md)
- [接口示例与完整回放](examples/README.md)
- [历史阶段记录与原路径对照](archive/README.md)
- [上线前审查记录（2026-10-01）](prelaunch_audit_2026-10-01.md)

## 研究资料

- [个性化问答检测抑郁_调研与技术方案](research/个性化问答检测抑郁_调研与技术方案.md)
- [心理诊断对话数据集清单](research/心理诊断对话数据集清单.md)
- [抑郁筛查金标准量表_学术调研报告](research/抑郁筛查金标准量表_学术调研报告.md)
- [系统技术实现方案_MABIS](research/系统技术实现方案_MABIS.md)
- [调研报告_对话式抑郁检测与自适应提问](research/调研报告_对话式抑郁检测与自适应提问.md)
- [调研第3路_LLM筛查与多模态抑郁检测](research/调研第3路_LLM筛查与多模态抑郁检测.md)
- [调研路线4_现有不足与伦理有效性](research/调研路线4_现有不足与伦理有效性.md)

## 前端设计与规划

- [design-spec](../frontend-vue/docs/design-spec.md)
- [学生端规划](../frontend-vue/docs/学生端规划.md)
- [教师端排布与功能总结](../frontend-vue/docs/教师端排布与功能总结.md)
- [治愈功能实现](../frontend-vue/docs/治愈功能实现.md)
- [管理端规划](../frontend-vue/docs/管理端规划.md)

## 文件维护约定

当前运行说明及接口文档放在 `docs/`；有日期的阶段验收与修复记录放在 `docs/archive/<模块>/`，并在归档索引登记。历史记录不用于声明当前代码已重新验收。完整 JSON 回放保留在 `docs/examples/`，新的临时日志和试跑输出放在 Git 忽略的本地目录中。移动文档时同步更新相对链接。
