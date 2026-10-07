# 治愈 Agent 本地交付（2026-10-07）

> 当前完成标记：用户已授权将治愈 Agent 后端、知识库、验证脚本及文档提交到 GitHub，范围为团队自行设定对话的竞赛演示版。第二轮审查的五项组合问题保留为已知边界，详见[完成里程碑](healing_completion_20261007.md)。下文未提交/未推送的表述保留前一阶段的交付事实。

> 本地后续修复：提交前审查的四类问题及用户确认的固定方法编号已修复。最新离线基准为725项通过（28.17s），本轮没有重跑远程模型；下方684项及文件摘要清单保留前一版交付范围，不代表修复后版本的远程验收。具体变化和验证见[提交前审查修复](healing_review_fix_20261007.md)。

交付对象是团队竞赛自行演示所用的后端、知识和接口。前一阶段本地交付时未创建 Git 提交、推送、PR 或 GitHub 发布，仓库原有修改及未跟踪文件保留。该阶段 Git 基准为 `dfeb795cd494d434e15ab206ec1d796403ead2bb`，当时验收版本按[文件摘要清单](examples/healing_delivery_manifest_20261007.json)识别；该清单保留前一版验收范围，本次完成版本以 Git 提交内容及完成里程碑说明为准。

最终验收结果、逐轮复核及用量见[本轮验收](healing_final_acceptance_20261007.md)，完整合成回放见[验收数据](examples/healing_final_acceptance_20261007.json)。接口字段、错误及前端接入约定见[后端交接](healing_agent.md)。总规划位于项目上一级的 `治愈Agent规划.md`。

## 环境与启动

本机使用 Miniforge 的 `mental-health-agent` 环境，Python 3.11.16。实际验收依赖：FastAPI 0.141.1、Pydantic 2.13.5、HTTPX 0.28.1、pytest 9.1.1、Uvicorn 0.54.0、jieba 0.42.1、rank-bm25 0.2.2、BeautifulSoup4 4.14.3。模型调用使用现有本地配置；本轮实测模型为 `DeepSeek-V4.1-Flash`，不将密钥或 `.env` 复制到交付文件。

在项目目录执行：

```powershell
conda activate mental-health-agent
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

运行中的服务需要重新加载代码才会采用本轮修复；本轮验收用新的隔离测试进程，没有重启现有演示服务。重启会清空进程内陪伴状态，演示应新建会话并重新评估。知识索引也在进程内缓存。

## 演示与接口

1. 创建会话，在评估的首条用户回答中明确给出合成学生年龄和年级，例如“我12岁，读初一”。调用真实 `/api/assessment` 完成评估入库。
2. 使用 `/api/healing/start`，为同一操作保留 `request_id`；`background.current_concern` 可明确指定演示方向。外部请求不接受 `background.age`，年龄来自绑定的最新评估；成人支持可选提供，也可以在陪伴中按需确认。
3. 用 `/api/healing/chat` 发送后续回答；同一回答重试保留 `message_id`。含糊指代可以澄清，已明确序号不再追问是哪条方法。
4. 演示“还没试”“试了但没帮助”“准备试试／先暂停”，查看建议和反馈。准备保留为 `prepared`；后来明确还没试时，另记 `not_attempted/unknown`，不会虚构尝试或效果。
5. 返回后用 `GET /api/healing/{session_id}` 或重复 `/start` 恢复仍存在的状态；需要新一轮时显式 `regenerate=true`。新评估不自动替换旧陪伴绑定。

9、12、16 岁的正式合成案例覆盖考试压力、情绪低落、普通同伴冲突和睡眠，以及三类多轮旅程。前端按钮、消息路由、双报告展示和页面联调由前端队员负责。

## 用户确认的范围取舍

已经展示合格 `simple` 表达后再次要求“还要更简单”，本次按用户确认略过，不再增加知识表达或缩减动作、时长、成人条件。本次团队自行演示不以真实儿童理解度作为阻塞项。复验脚本会记录被略过的输入及原因；保留已有从其他表达切换到 `simple` 的功能与验证，不将略过分支计为通过。

模型易读性评语保留在回放中供参考；这次只验收约定合成演示的接口、依据、状态、提问和收尾。真人理解度、心理改善效果、广泛复杂口语、长期稳定性和生产负载均不在本次完成声明内。

## 复验入口

在项目目录运行，所有过程数据必须在挂载根目录 `codex_proc/` 下，建议每次使用新的子目录。真实接口脚本会调用配置模型并产生用量：

```powershell
python -X utf8 -B scripts/run_healing_acceptance.py --work-dir "../codex_proc/healing_recheck/mainchain"
python -X utf8 -B scripts/validate_healing_current.py --work-dir "../codex_proc/healing_recheck/boundaries"
python -X utf8 -B scripts/validate_healing_experience.py --work-dir "../codex_proc/healing_recheck/experience"
```

三个脚本均在导入 API 前隔离默认 SQLite、临时目录与分词缓存，记录逐调用模型用量并核对后端、评估、前端源码和正常数据库的摘要。`current` 的双方法案例若只生成一个方法，记为 `not_exercised` 并返回非零，不能冒充通过。体验脚本的原始模型复核不是最终人工判定；出现非零应逐轮核对回放，保留具体错误或误判依据。

本轮全后端离线测试使用 `codex_proc/healing_final_acceptance_20261006_289acf97/run_tests.py` 隔离普通 SQLite 与 pytest 临时目录，输出 `final_full.xml` 和 `final_full_result.json`。在本机原项目目录可原样复现：

```powershell
python -X utf8 -B ../codex_proc/healing_final_acceptance_20261006_289acf97/run_tests.py recheck -q --junitxml ../codex_proc/healing_final_acceptance_20261006_289acf97/recheck.xml
```

## 当前运行边界

- 127 条知识：103 条可用方法、8 条解释/求助、16 条继续隔离；309 个合格表达。88 条学生执行、15 条成人指导，条件保留，最多两个活跃方法。
- 状态仅在单进程保存，空闲 TTL 两小时，每轮最多 80 个回答。跨进程共享和跨会话反馈持久化留作后续扩展。
- GET、恢复、重试及生成提交检查当前风险；新风险停用普通建议并求助。没有现实联系、自动通知或主动推送未来风险的能力。
- 格式或文字校验有限修复；可通过独立校验后无问题暂停。传输失败或最终文字检查失败继续返回 503 并保留旧进度。
- 资料按已确认的竞赛原型范围使用；已有来源与许可状态记录保留。当前没有把公开再分发授权作为本次待办。
