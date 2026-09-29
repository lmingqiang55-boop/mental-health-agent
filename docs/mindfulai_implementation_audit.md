# MindfulAI 源码核查与本项目迁移方案

核查对象：[Hereakash/Mental-Health-Detection-Using-AI](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/tree/e70bec9a76a66cd6dfe91d64acda588bc5d58704)，提交 `e70bec9a76a66cd6dfe91d64acda588bc5d58704`。本文件基于源码静态核查；没有把上游项目运行结果或 README 功能宣称当作验证结论。

## 1. 上游实际如何工作

| 功能 | 源码路径 | 实际机制 |
| --- | --- | --- |
| 网页问卷 | [`index.html`](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/index.html)、[`script.js` 1311–1411 行](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/script.js#L1311-L1411) | 一次收集 PHQ-9 的 9 个答案和 GAD-7 的 7 个答案，在浏览器中求和、按阈值分级；第 9 个 PHQ 答案大于 0 时覆盖风险级别。没有根据答案改变后续题目。 |
| 网页聊天 | [`script.js` 2154–2174、2238–2389 行](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/script.js#L2154-L2389) | 关键词提取情绪、话题和风险，再用条件分支返回预写回复。`API_BASE_URL` 仅定义，整个 `script.js` 没有 `fetch()` 调用。用户和聊天内容放在 `localStorage`。 |
| 网页报告 | [`script.js` 2415–2660 行](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/script.js#L2415-L2660) | 从聊天关键词、消息数和风险标签生成 HTML 与文本下载。报告没有读取前面的 PHQ-9/GAD-7 答案，也没有六维分数。建议由情绪/话题关键词触发。 |
| 独立后端聊天 | [`backend/app.py` 241–329 行](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/backend/app.py#L241-L329)、[`backend/chatbot.py` 473–628 行](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/backend/chatbot.py#L473-L628) | Flask API 接收消息；配置密钥时调用 Gemini，失败则回退关键词模板。Gemini 的系统提示要求跟进提问，但没有结构化题库、题目选择或覆盖率状态。 |
| 独立后端问卷/综合分 | [`backend/mental_health_predictor.py`](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/backend/mental_health_predictor.py) | 后端另有 PHQ-9/GAD-7 求和和阈值规则；`generate_combined_assessment()` 将问卷、文本、表情风险转成 0/1/2 后取平均。后端计分没有逐项验证 0–3 值，也没有单独处理 PHQ-9 第 9 题。 |
| 独立后端报告/建议 | [`backend/app.py` 484–549 行](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/backend/app.py#L484-L549)、[`backend/mental_health_predictor.py`](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/backend/mental_health_predictor.py) | `/api/report/{user_id}` 取聊天分析与最近测评 JSON，再按情绪关键词生成通用建议；并未把问卷和聊天融合成一致的六维结果。建议接口是固定规则和模板。 |
| 文字模型 | [`backend/ml_model.py` 68–139 行](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/backend/ml_model.py#L68-L139) | 默认示例训练集为代码里写的 50 条英文句子，仅供演示，不能作为本项目的抑郁检测模型或准确率证据。 |

关键结论：上游有两个基本分离的实现路径。浏览器内的问卷、聊天、报告互不形成完整的“问答→多维分数→报告”闭环；后端有相似的 API，却未被网页调用。它可供参考的是页面结构、PHQ/GAD 输入样式和建议分类，不能直接作为自适应评估引擎。

## 2. 与本项目当前代码的对应

| 上游思路 | 本项目承接点 | 建议 |
| --- | --- | --- |
| 聊天入口 | `backend/api/chat.py`、`backend/core/dialogue_manager.py` | 保留 FastAPI 和现有会话路径；由后端决定下一问，前端只渲染。不要引入 Flask 或复制上游浏览器关键词聊天。 |
| 结构化答案 | `backend/models/states.py`、`backend/core/session_manager.py` | 先扩展数据契约：题目 ID、量表/维度、答案值、已问列表、测评版本、完成状态、风险事件。依照 `docs/development_rules.md` 先更新 API 契约，再改共享模型。 |
| 问卷计分 | 新增 `backend/core/screening_engine.py` 与受审核的题库 | PHQ-9 九题完整作答后才显示正式 PHQ-9 总分；不足九题只标“初筛/估计”，不可冒充 PHQ-9 分数。附加维度单独记录分数和来源。 |
| 风险覆盖 | `backend/core/risk_engine.py` | 直接的自伤表述及有关量表答案应优先进入人工复核/求助流程。不要用文字、问卷、表情风险取平均，以免冲淡高危信号。风险提示与抑郁症状严重度分开显示。 |
| 建议 | 新增 `backend/core/recommendation_engine.py`、`backend/rag/knowledge/` | 用经审核的建议库按严重度、功能受损、主要困扰和持续时间选条目；LLM 可解释和调整语气，不独立决定治疗或药物。 |
| 报告 | 新增后端评估快照和学生端结果页 | 报告由同一份后端评估快照生成，列出量表分、附加维度、病程/功能受损、证据来源、缺失项、风险提示、建议与专业人员复核状态。 |
| 专业端 | `docs/mvp_scope.md` 的既有规划 | 使用合成数据建页面；身份、知情同意、授权与访问日志完成前，不开放真实学生跨会话查看。上游 `/api/report/{user_id}` 只按整数 ID 查询，不能照搬。 |

本项目当前的 `mood/interest/sleep/energy/concentration/duration` 是六个**提问主题及覆盖状态**，并非六个经过校准的心理测量维度；`covered` 也不是分数。若要按目标图展示“情绪、压力、人际、自我认知、学习生活、持续时间”，需要明确各维度的题目、计分依据和展示含义。其中“持续时间”应是病程字段，不宜伪装成与其余维度同类的 θ 值。GAD-7 评估焦虑，不等于压力。

建议的报告数据形状如下；这只是接口草案，尚未进入 `docs/api_spec.md`，也未实现：

```json
{
  "primary_screen": {"instrument": "PHQ-9", "version": "待确认", "answered": 9, "required": 9, "score": 12, "score_kind": "observed_total"},
  "dimensions": [
    {"id": "relationships", "label": "人际关系", "score": 2, "score_kind": "demo_rule", "answered": 3, "source_question_ids": ["rel_1", "rel_2", "rel_3"]}
  ],
  "context": {"duration": "约三周", "functional_impact": "学习效率下降"},
  "safety": {"review_required": false, "reasons": []},
  "recommendations": [{"id": "seek_assessment", "trigger": "phq9_score", "review_status": "待审核"}]
}
```

这里的 `demo_rule` 明确表明辅助维度只是演示规则，不能展示成经过校准的 θ 分数；真实报告中的建议还必须有已审核的内容和来源。

## 3. 最小可交付闭环

1. **定义结果契约**：先在 `docs/api_spec.md` 写明 `question_id`、候选答案、量表版本、已确认答案、各维度结果、风险事件和建议 ID。A 与 C 核对后修改共享模型。
2. **先做确定性问答**：后端按答案选择下一道补充题，显示跳题原因和每维完成进度。没有经过题库校准与外部验证时，称“分支式自适应问答”，不称 CAT、MFI 或六维 θ 估计。
3. **接入抑郁锚定测评**：把 PHQ-9 的答案和计分保存在会话或评估快照中；完整九题才给 0–27 总分。对青少年使用场景先确认适龄量表、语言版本和人工流程。
4. **加附加维度**：为人际、自我认知、学习生活等定义独立题库和明确的演示评分；仅把可追溯的维度写进结果页。病程与功能受损另列。
5. **规则式建议与风险分流**：评估快照驱动建议卡片；每张卡记录触发依据、建议来源、适用年龄、审核版本。急迫风险先给人工求助通道和专业端待复核标记。
6. **学生端报告**：`frontend/src/App.jsx` 增加逐题控件和结果页，读取后端报告 API；不要像上游那样在前端重新计分或根据关键词生成另一份报告。

建议的验收场景：同一组答案在浏览器和 API 中得到同一结果；跳题不会导致已答题目丢失；不完整 PHQ-9 不显示正式总分；自伤相关答案不会被其他低风险信号抵消；无音视频和无 LLM Key 时仍能完成问答、得到报告；报告中的每条建议可追溯到规则与证据。

上游源码采用 [MIT 许可](https://github.com/Hereakash/Mental-Health-Detection-Using-AI/blob/e70bec9a76a66cd6dfe91d64acda588bc5d58704/LICENSE)。若复制少量界面代码，保留许可证与版权声明；核心评估逻辑以本项目后端重建更直接。

临床边界参考：[NICE 成人抑郁评估指南](https://www.nice.org.uk/guidance/ng222/chapter/Recommendations)要求结合症状、持续时间、病程与功能损害；[NICE 儿童青少年指南](https://www.nice.org.uk/guidance/ng134/chapter/recommendations)强调学校、人际及家庭情境与直接询问自伤；[AAP 青少年自杀风险筛查资料](https://www.aap.org/en/patient-care/blueprint-for-youth-suicide-prevention/strategies-for-clinical-settings-for-youth-suicide-prevention/screening-for-suicide-risk-in-clinical-practice/)指出不能单靠 PHQ-9 第 9 题排除风险。
