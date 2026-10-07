# 治愈模块来源和许可记录

核对日期：2026-10-05。用户已选择先完成内部竞赛原型。这个范围选择不等于取得网站授权，也不表示知识文件可随公开仓库、产品或竞赛资料任意再分发。源文缓存不纳入仓库；运行知识保留短依据和中文概述。公开发布前仍需取得相应许可或替换资料。

## 支持内容来源

| 来源 | 本版使用范围 | 许可核对结果 |
| --- | --- | --- |
| [UNICEF 压力](https://www.unicef.org/parenting/mental-health/what-is-stress)、[焦虑](https://www.unicef.org/parenting/mental-health/what-is-anxiety)、[情绪低落](https://www.unicef.org/parenting/mental-health/what-is-depression) | 成人指导的日常支持；不使用诊断或治疗章节 | [条款](https://www.unicef.org/legal)规定个人及教育用途，并对更广泛复制、翻译和传播要求书面许可。未取得本项目知识库再分发许可 |
| [北京安定医院开学支持](https://bjad.com.cn/Html/News/Articles/5055.html) | 两条解释；必要医学检查不能由当前输入确认的方法保持待处理 | 未确认覆盖本项目抽取、改写及再分发的开放许可 |
| [北京考试报中考文章](https://bjksb.bjeea.cn/html/ksb/zhongyaoxinwen/2023/0626/83972.html) | 三条方法对象证明不足，保持待处理 | 未确认开放再分发许可；文章为 2023 年资料，不当作现行规范 |
| [Child Mind 普通冲突](https://childmind.org/article/teaching-kids-how-to-deal-with-conflict/) | 成人指导下识别原因、讨论方案等；不用于欺凌威胁 | [条款](https://childmind.org/terms/)允许有版权标识的个人用途复制，对批量或商业再利用有限制。未取得本项目再分发许可 |
| [Nemours KidsHealth 儿童睡眠](https://kidshealth.org/en/kids/not-tired.html) | 固定作息、睡前屏幕、平静活动和咖啡因；保留持续困难时告诉家长的提示 | [权限指南](https://kidshealth.org/en/parents/permissions-guidelines.html)区别链接、完整免费印刷品和需许可的使用；不授权把编辑后的内容复制到其他网站。未取得本项目改写知识库的公开许可 |
| [北大六院青少年睡眠](https://www.pkuh6.cn/Html/News/Articles/4977.html) | 日常习惯；不使用睡眠限制、刺激控制或完整治疗流程 | 未确认开放再分发许可 |

Child Mind 直接 HTTP 抓取返回 403。本版使用公开网页读取结果中可见正文的正规化文本，保存其摘要与位置；没有把导航或抓取错误当正文。其字符位置属于该正规化文本，不能直接套到另一版 HTML。Nemours 文中标明医学审阅日期为 2020 年 6 月；仅作为儿童日常教育材料，不能代替医学评估。

## 交流参考

UNICEF 的 [6–10 岁交流](https://www.unicef.org/parenting/mental-health/conversation-starters-6-10-years)、[11–13 岁交流](https://www.unicef.org/parenting/mental-health/conversation-starters-11-13-years)、[14–18 岁交流](https://www.unicef.org/parenting/mental-health/conversation-starters-14-18-years)仅用于短句、倾听、自然交流、尊重自主性等表达策略，不扩展支持方法的年龄。网站许可边界与上表一致。

## 代码和模型

| 参考或依赖 | 固定版本 / 提交 | 许可及实际复用 |
| --- | --- | --- |
| [EmoLLM](https://github.com/SmartFlowAI/EmoLLM/tree/955155bb536eb1c28ff4500c6dc6a093a24e8209) | `955155bb536eb1c28ff4500c6dc6a093a24e8209` | [MIT](https://github.com/SmartFlowAI/EmoLLM/blob/955155bb536eb1c28ff4500c6dc6a093a24e8209/LICENSE)。参考窗口与抽取流程；对照时从独立下载的源码只加载 `get_txt_content`，未运行模块初始化或清理函数，未把源码加入后端 |
| [LangExtract](https://github.com/google/langextract/tree/62b933a2c757fd2bbb100498571b8d1692db4344) | 包 `1.7.0`，源码参考 `62b933a2c757fd2bbb100498571b8d1692db4344` | [Apache-2.0](https://github.com/google/langextract/blob/62b933a2c757fd2bbb100498571b8d1692db4344/LICENSE)。独立研究依赖，运行字符区间抽取；没有加入服务启动依赖 |
| [LlamaIndex](https://github.com/run-llama/llama_index/tree/962940ddc079cc21701d28d1237c84c82a7c5164) | core `0.14.25`，BM25 retriever `0.8.0`；源码参考 `962940ddc079cc21701d28d1237c84c82a7c5164` | [MIT](https://github.com/run-llama/llama_index/blob/962940ddc079cc21701d28d1237c84c82a7c5164/LICENSE)。实际比较中文分词后检索与元数据过滤，服务继续用轻量实现 |
| [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding/tree/fd1a2bdf69488ffebe0327999d4400d8c8058a0b) | `fd1a2bdf69488ffebe0327999d4400d8c8058a0b` | [MIT](https://github.com/FlagOpen/FlagEmbedding/blob/fd1a2bdf69488ffebe0327999d4400d8c8058a0b/LICENSE)。参考 CLS 归一化、交叉编码重排序和模型使用方法；基准通过现有 Transformers 加载 |
| [BGE small 中文](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[BGE reranker base](https://huggingface.co/BAAI/bge-reranker-base) | 各模型卡与实际下载快照 | 两份模型卡声明 MIT；权重只作离线检索实验，不随项目知识文件分发 |
| jieba / rank-bm25 / beautifulsoup4 | `0.42.1` / `0.2.2` / `4.14.3` | 安装包许可元数据为 MIT / Apache-2.0 / MIT；版本以 `requirements.txt` 为准 |
| 既有 Transformers / PyTorch | 当前环境安装版本 | 分别为 Apache-2.0 / BSD-3-Clause；可选实验复用环境，不增加后端加载模型的要求 |

开源框架和模型的许可不覆盖 UNICEF 等内容资料，也不覆盖远程模型服务的条款。当前远程服务沿用项目配置；记录实际 token 用量，不据未经核实的价格推算金额。MinerU、QAnything、RAGFlow、Ragas 等未运行候选不记为已接入能力。

本记录是工程范围及待确认项清单，不是法律授权证明。没有代用户联系任何资料机构。

## 同日知识扩充

新增 22 篇 Nemours KidsHealth 儿童/青少年官方文章，逐篇网址、对象、抽取范围及数量见 [知识库扩充记录](healing_knowledge_expansion.md)，允许正文与许可字段同步记录在 `backend/rag/knowledge/healing_sources.json`。范围包括日常情绪、压力、普通同伴关系和睡前习惯，排除治疗、驾驶、大学/恋爱情境与具体学习技巧。

新文章继续标记 `restricted_reuse; edited_online_content_not_authorized`，依据同一 [权限指南](https://kidshealth.org/en/parents/permissions-guidelines.html)；没有宣称开放许可或取得本项目公开再分发许可。源文缓存留在挂载项目根目录的 `codex_proc/`；知识文件中的新来源全部字面锚点累计每篇不超过 25 个英文词，保留摘要、位置和中文概述。来源的医学审阅日期与本轮访问日期是不同概念。
