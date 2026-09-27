# 学术调研（第 3 路）：LLM/Agent 抑郁筛查 与 多模态抑郁检测

> 项目：心理健康多模态智能体（FastAPI + React；已有视觉通道：表情/效价/眼动；音频通道：语速/停顿/能量/音高）
> 调研窗口：2023–2026（经典奠基文献回溯至 2017/2020）
> 证据标记：**[已证实]** = 有多研究/meta-analysis 一致结论；**[初步]** = 单研究或小样本；**[推测/空白]** = 文献未直接回答，本调研基于已有证据外推
> 所有数字均标注作者-年份；未在检索摘要中看到的具体数字不补写。

---

## 一、核心结论（先读这一段）

1. **零样本/少样本 LLM 直接做抑郁分类，在受控数据集上 ≈ 微调小 transformer，但明显不如领域微调模型。** 在 DAIC-WOZ 文本上，零/少样本 GPT-3.5/4 与 BERT/XLNet 等微调模型之间存在稳定差距；用指令微调后的小模型（0.5B–7B）反而能在平衡准确率上反超 GPT-4 约 4.8%（Xu et al., 2023）。**[已证实]**
2. **LLM 的真正价值不在"当分类器"，而在三件事**：(a) 把非结构化访谈转成结构化症状/问卷条目（Rosenman et al., 2024）；(b) 生成可审计的推理链/症状映射（MAGI 的 PsyCoT，Bi et al., 2025）；(c) 驱动对话式访谈并按临床分支逻辑追问（EmoScan F1=0.7467，Liu et al., 2025 *Nat Commun Med*；MAGI 在 1002 名真实被试上落地）。**[已证实]**
3. **多模态相对纯文本的增益真实存在但被高估风险大**：语音单模态 DL 合并诊断准确率 0.87（95%CI 0.81–0.93，Liu et al., 2024 *JAMIA* meta）；眼动单指标区分 MDD vs HC 仅 AUC=0.76（Takahashi et al., 2021）；眼动注意偏向效应量 Hedges' g≈0.5–0.66（Suslow et al., 2020 meta）。多模态融合在 D-Vlog 等大数据集上可报 90%+，但在 DAIC-WOZ 这种小样本（≈数百人）上 SOTA 二元 F1 长期停留在 0.75–0.80 区间（DWAM-Former MF1=0.788，Yue et al.）。**[已证实]**
4. **"LLM 判断这个回答是否充分、要不要追问"在工程上已有可借鉴架构（MAGI 的 judgment agent），但其判断可靠性本身未被严格验证。** MentalBench-100k 显示 LLM 评审在"指导/信息性"上与人类专家一致性较好，但在"共情/安全/相关性"上系统性偏高估、精度下降（Badawi et al., 2026 *EACL*）。**[初步]**
5. **"句级多模态信号实时回灌给对话策略"是本项目的差异化空间，也是文献空白。** 现有自适应访谈系统（Shidara et al.；PsyAdvisor Hu et al., 2025 *ACL*；MAGI）的触发信号几乎全部来自文本/自报，没有把音频能量/音高/注视回避作为"是否需要换问法、是否需要停下来共情"的输入。**[推测/空白]**

---

## 二、A 部分：LLM/Agent 抑郁筛查（2023–2026）

### 2.1 LLM 直接做抑郁检测：代表性研究表

| 模型/方法 | 任务 | 数据集 | 关键指标 | 年份/作者 |
|---|---|---|---|---|
| ChatGPT 两阶段（先摘要后分类） | 访谈文本抑郁二分类 | DAIC-WOZ（text-only） | Accuracy ≈ 76%；在 D' 子集上比当时 SOTA 高 6.2% | Hu et al., 2024, *J USTC* |
| GPT-3.5 微调 vs zero-shot CoT | 日记文本 PHQ 风险筛查 | 428 篇日记/91 人 | 微调 acc=0.902、特异度=0.955；未微调 balanced acc=0.844、召回=0.929 | Shin et al., 2024, *JMIR* |
| Distil-RoBERTa / XLNet / Llama3-8B / GPT-3.5 Turbo 横评 | GAD-2 / PHQ / stress 三分类 | DAIC-WOZ + 压力数据集 | Distil-RoBERTa F1=0.883（GAD-2）；XLNet F1 最高=0.891（PHQ）；zero-shot+合成数据 stress F1=0.884 / AUC=0.886 | Arcan & Niland, 2025, arXiv:2511.07044 |
| Llama-2 vs ChatGPT vs 经典 ML | DAIC-WOZ 抑郁分类 | DAIC-WOZ | BERT/XLNet 等微调 transformer **优于** LLM zero-shot | Arcan et al., 2024, arXiv:2401.04592 |
| Mental-Alpaca / Mental-FLAN-T5（指令微调小模型） | 多任务在线文本心理预测 | 多源社交媒体 | 比 GPT-3.5 最佳 prompt balanced acc 高 10.9%；比 GPT-4 最佳 prompt 高 4.8%；与 task-specific SOTA 持平 | Xu et al., 2023, *IMWUT* |
| MentaLLaMA（LLaMA2 + 105K IMHI 指令数据） | 可解释抑郁/自杀/焦虑 8 任务 | 10 个社交数据源 | zero/few-shot ChatGPT 分类性能不理想，解释质量随之下降；领域微调后接近判别式 SOTA，解释达人类水平 | Yang et al., 2023, arXiv:2309.13567 |
| ChatGPT 11 数据集 5 任务横评 | 含抑郁/自杀/焦虑 | 11 个公开数据集 | ChatGPT 有强 ICL 能力，但与 task-specific 方法仍有显著差距；情绪线索+专家 few-shot 可有效提升 | Yang et al., 2023, *EMNLP* |
| SEGA（结构化元素图 + LLM 数据增强） | 临床访谈抑郁检测 | 英文 + 中文两个临床访谈集 | 显著优于 GPT-3.5 / GPT-4（直接用 LLM） | Chen et al., 2024, *NAACL* |
| DORIS（LLM 标注症状 + GBT 分类） | Reddit 抑郁检测 | 社交媒体 | LLM 按诊断标准标注 + 时序情绪课程摘要后喂 GBT，精度与可解释性兼优 | Lan et al., 2025, *EMNLP Industry* |
| LLM 把非结构化访谈转成 PHQ-8/PCL-C 问卷条目 | 心理量表回归预测 | 临床访谈 | LLM 模拟被试填问卷后接随机森林，比多基线诊断准确率高 | Rosenman et al., 2024, *EMNLP Findings* |

**读法**：(1) 所有"LLM 直接 zero-shot 分类"的报告，数字都在 0.75–0.85 F1/acc 区间，且几乎都被同数据集上微调 BERT 系模型追平或超过；(2) LLM 真正拉开差距的是"做特征工程/数据增强/症状结构化"，而不是自己当最终分类头。

### 2.2 LLM 做对话式筛查 / Agent 架构

| 系统 | Agent 架构 | 临床依据 | 规模/指标 | 年份/作者 |
|---|---|---|---|---|
| **EmoScan** | LLM 筛查系统 + 合成临床访谈管道（Psylnterview 1157 段） | 区分粗粒度（焦虑/抑郁）与细粒度（MDD） | 情绪障碍筛查 F1=0.7467（超 GPT-4）；解释 BERTScore=0.9408；外部数据 F1=0.67；人评访谈质量超基线 | Liu et al., 2025, *Nature Communications Medicine* |
| **MAGI** | 4-agent：访谈树导航 / 自适应提问（探测+解释+共情）/ **judgment（判断回答是否满足节点）** / 诊断（PsyCoT 症状→标准映射） | 把 MINI（Mini International Neuropsychiatric Interview）分支结构自动化 | 1002 名真实被试，覆盖抑郁/GAD/社交焦虑/自杀 | Bi et al., 2025, *ACL Findings* |
| **AI Psychiatrist Assistant** | 4-agent：定性评估 / judge 自我精炼 / 定量 few-shot 打分 / meta-review | 临床访谈转录 | 定量打分 few-shot MAE=0.619 vs zero-shot 0.796；二分类 acc=78%，与人类专家可比 | Greene et al., 2026, PMLR v297 |
| **TalkDep** | clinician-in-the-loop 模拟患者生成管道 | 按诊断标准+症状严重度量表+情境因子生成患者画像 | 临床专家验证模拟患者真实性 | Wang et al., 2025, *CIKM* |
| **UPSD** | 无察觉式症状探针对话策略 | 应对病耻感，避免直接问"你抑郁吗" | 在对话自然度和诊断准确率上均显著超基线 | Cao et al., 2025, *NAACL Findings* |
| **D4** | 中文抑郁诊断对话数据集（3 阶段构造） | ICD-11/DSM-5 | 4 任务：响应生成/话题预测/对话摘要/严重度+自杀风险分类 | Yao et al., 2022, *EMNLP* |

**对本项目的直接借鉴**：MAGI 的 4-agent 拆分（导航/提问/判断/诊断）就是你要的"FastAPI 后端多 agent"骨架；其中 **judgment agent 正是"这个回答是否充分、要不要追问"**——它显式建模为一个独立 agent，而不是混在生成回复里。

### 2.3 LLM vs 传统方法：性能与可解释性

- **性能**：在 DAIC-WOZ 文本上，微调 BERT/XLNet 系稳定优于 zero-shot GPT（Arcan et al., 2024, 2025）；指令微调后的 7B 级模型可反超 GPT-4（Xu et al., 2023）。**[已证实]**
- **可解释性**：ChatGPT 生成的决策解释经严格人评"接近人类水平"（Yang et al., 2023 *EMNLP*；MentaLLaMA Yang et al., 2023）；但 zero/few-shot 下分类错→解释也错，解释质量依赖分类正确性（Yang et al., 2023）。**[已证实]**
- **捷径风险警示**：Burdisso et al.（2024, *ClinicalNLP Workshop*）在 DAIC-WOZ 上发现，把访谈者 prompt 喂给模型可刷到 **F1=0.90**（纯文本当时最高），但模型实际学会的是"听到既往精神病史段落就判阳性"的 shortcut，而不是患者语言特征。**做消融时必须把 interviewer prompt 单独剥离。[已证实]**

### 2.4 可靠性与局限（比赛答辩必被问）

| 问题 | 证据 | 强度 |
|---|---|---|
| LLM 评审/判断的系统性高估 | MentalBench-100k + MentalAlign-70k：4 个强 LLM judge 在 70k 评分上对人类专家；认知属性（指导、信息性）可靠性强，**共情精度下降，安全与相关性维度不可靠**；存在系统性 inflation | Badawi et al., 2026, *EACL* [已证实] |
| 对提示词的敏感性 / 否定一致性低 | 17 个 LLM × 39 种心理测量工具 × 693 题；仅调换选项顺序、把肯定句改否定句这类微小扰动即显著降低 QA 能力，多数 LLM 否定一致性低 | Shu et al., 2024, *NAACL* [已证实] |
| 人口学/文化偏差 | GPT-4 对黑人发帖者的共情评分比其他群体低 2%–13%；模型能从隐含/显式线索推断种族 | Gabriel et al., 2024, *EMNLP Findings* [已证实] |
| 已知种族与性别偏差 | Mental-LLM 明确点名部署前必须处理种族/性别偏差 | Xu et al., 2023 [已证实] |
| 同一对话多次评估的一致性 | 直接证据少；Shu et al.（2024）在心理测量题上证明简单扰动即破坏一致性，可外推到筛查场景 | [初步/外推] |
| 幻觉 | 心理健康 LLM 综述普遍点名；MentaLLaMA 报告 zero-shot 错误分类时会生成看似合理但错误的解释 | Yang et al., 2023 [初步] |

### 2.5 安全对齐

- Heston（2023, *Cureus*）用患者模拟（抑郁恶化+自杀意念）测试公开 ChatGPT-3.5 心理 agent，发现其识别与危机响应不可靠——**这意味着安全拒答/危机转介逻辑不能依赖通用 LLM 的默认对齐，必须硬编码**。[已证实]
- 与本项目相关的设计含义：筛查 agent 应把"自杀风险红线检测"做成独立规则/小模型分支，触发即转人工/危机热线，而不是让主对话 LLM 自由判断。

---

## 三、B 部分：多模态抑郁检测

### 3.1 各模态特征—抑郁关联表

> 下表对应你项目已有通道。"方向"是抑郁组相对健康组的变化。

| 模态 | 具体特征 | 与抑郁的关联（方向 / 效应） | 证据等级 / 来源 |
|---|---|---|---|
| **面部表情** | 皱眉肌（corrugator, AU4）、颧大肌（zygomatic, AU12）活动 | 治疗反应好 = 面部表情整体活动性升高；corrugator/zygomatic 活动更高、唇紧抿(AU17)/下唇下降(AU15)更少 → 预测治疗有效 | 12 研究 389 人系统综述，Plevin et al., 2022/23, *Depress Anxiety* [已证实] |
| 面部表情 | 对情绪刺激的面部肌电低反应（hyporeactivity） | 抑郁组在负性/高唤醒视频下眉/颊肌激活显著低于对照（n=75） | Broulidakis et al., 2023, *Front Psychiatry* [初步] |
| 面部表情 | 表情减少、微笑时长/幅度降低 | 临床共识+自动 FACS 可逐帧编码（AU 时长 ICC=0.89，逐帧 MCC=0.61） | Girard et al., 2015 [已证实方法学] |
| **眼动** | 对正性刺激注视时长 | 抑郁组显著更短，SMD=−0.87（p=0.004） | 14 研究 1167 人 meta，Huang et al., 2022, *Front Psychol* [已证实] |
| 眼动 | 对负性/烦躁刺激维持注意 | 抑郁组更久，Hedges' g=0.66（烦躁图片）、g=0.58（悲伤面孔）；对快乐面孔 g=−0.54 | 16 研究 meta，Suslow et al., 2020, *J Affect Disord* [已证实] |
| 眼动 | 扫视峰值速度、扫视时长、scanpath 长度 | MDD 组平滑追踪扫视时长更短、峰值速度更低、自由浏览 scanpath 更短；这两个指标判别 MDD vs HC 准确率 72.1%，**AUC=0.76** | Takahashi et al., 2021, *Front Psychiatry*（37 MDD vs 400 HC）[已证实] |
| 眼动 | 早期定向（first fixation） | **无显著组间差异**——偏向性出现在晚期维持注意，不在早期定向 | Suslow et al., 2020 [已证实]；Bodenschatz et al., 2021 *BMC Psychiatry* 在 face-in-the-crowd 任务下甚至未复现注意偏向（反例） |
| 眼动 | 瞳孔变化 | 综述列为候选生物标志，但抑郁-瞳孔方向一致性证据弱，本调研未拿到定量 meta | Skaramagkas et al. 综述 [初步/证据弱] |
| **语音副语言** | 合并诊断性能（DL 语音） | 25 研究综述，8 研究 meta：合并准确率 **0.87**（95%CI 0.81–0.93）、特异度 0.85、敏感度 0.82；手工特征+CNN 组最高 0.89 | Liu et al., 2024, *JAMIA* [已证实] |
| 语音 | 语速（speech rate） | 抑郁组显著更慢（老年队列组间差异显著） | Mijnders et al., 2023, *Interspeech*；Albuquerque et al. [已证实] |
| 语音 | 停顿时长 / 停顿占比 | 抑郁组总停顿时长更长、总发声时长更短 | Albuquerque et al.；Mijnders et al., 2023 [已证实] |
| 语音 | F0（音高）均值与范围 | 高抑郁者在 clear speech 任务中 F0 均值与范围提升显著小于低抑郁者（即**音高范围缩小、语调更平**） | Yi et al., *JSLHR* [初步]；Mijnders et al. 报告 F2 范围内组间差异 |
| 语音 | 语音强度/能量变异性 | 抑郁症状越重，语音强度变异性越低 | Gumus et al., 2023, *Digital Health*（n=16 日记式 30 天）[初步] |
| 语音 | Jitter（频率微扰） | 抑郁症状越重，jitter 越高 | Gumus et al., 2023 [初步] |
| 语音 | Wav2vec2.0 深度特征（去说话人身份后） | DAIC-WOZ F1=69.2%；普通话 CONVERGE F1=91.5% | Ravi et al., 2022, arXiv:2206.09530 [已证实跨数据集] |

**对你已有通道的对照**：你已经在用的"效价/唤醒/参与度/微表情 + 语速/停顿/能量/音高"，每一个都能在上面表里找到对应的抑郁关联证据。**最稳的是：语速↓、停顿↑、能量变异性↓、正性表情/注视时长↓、负性刺激注视维持↑**。眼动"早期定向无差异、晚期维持才有差异"这一点在设计实时策略时很关键——**不要指望一眼就看出来，要靠句/段级累积**。

### 3.2 多模态融合方法对比与增益

| 方法 / 系统 | 融合策略 | 数据集 | 报告指标 | 年份/作者 |
|---|---|---|---|---|
| AudiFace | 预训练时序面部特征 + 音频 + 转录文本；BiLSTM+self-attention | 15 个数据集 | 15 个数据集中 13 个 F1 最高；**eye gaze 是单模态和多模态中最有价值的时序面部特征** | Flores et al., 2022, *PMLR v182* |
| DPD Net | GNN-enhanced Transformer 单模态编码器 + 多模态编码器 + 检测头 | E-DAIC / Twitter / MODDMA / D-Vlog | 4 个数据集中 3 个 SOTA | He et al., 2024, *BMC* |
| 深度特征融合网络 | Transformer 自编码句句级嵌入 + cross-modal transformer | DAIC-WOZ | 超当时 SOTA | Sun et al., 2023, SPIE |
| MMFormer | 时空 Transformer + 晚期+中间融合 | D-Vlog / LMVD | D-Vlog **93.92%**、LMVD 77.74% | Haque et al., 2025, arXiv:2508.06701 |
| MDD-Net | mutual transformer 跨模态声学-视觉 | D-Vlog | 比此前 SOTA 高 **17.37%**（相对） | Haque et al., 2025, arXiv:2508.08093 |
| DWAM-Former | 层级 Transformer + 动态窗 + 注意力合并 | DAIC-WOZ | **MF1=0.788**，比前作 +7.5% | Yue et al., *PeerJ CS* |
| BERT-BiLSTM 混合 | BERT 文本嵌入 + 序列模型吃音频 | DAIC-WOZ | Accuracy 93.6%（注意：此数字来自单篇 IIETA 来源，需谨慎引用） | Challapalli et al. |
| 语音 DL meta（单模态基线） | — | 25 研究 meta | 合并 acc=0.87 | Liu et al., 2024, *JAMIA* |

**增益怎么读（关键，别被论文数字忽悠）**：
- 在**大规模自然数据集**（D-Vlog、LMVD，数千段短视频）上，多模态可以做到 90%+；在**临床访谈小样本**（DAIC-WOZ/E-DAIC，数百人）上，二元 F1 长期在 0.7–0.8 区间——DWAM-Former 的 0.788 是近年代表。
- 多模态 vs 单模态的具体增益数字在不同论文里口径不一（有的报绝对 acc、有的报相对提升），**没有跨研究统一的"+X%"数字可引用**。可确认的定性结论是：(a) 眼注视是面部通道里最有信息量的子特征（Flores et al., 2022）；(b) 文本+音频+视觉三模态稳定优于任意单模态；(c) 晚期融合/交叉注意力是主流，早期拼接已基本被淘汰。
- **[推测]** 对你的项目，合理预期是：纯文本 LLM 筛查 F1 ≈ 0.75–0.80；加上音频+视觉句级特征后，在自有小规模测试集上能拿到 +3–8 个百分点 F1 的提升，但不要期待跨数据集泛化。

### 3.3 代表性数据集与竞赛

- **DAIC-WOZ / E-DAIC**：USC 基于虚拟访谈员 WOZ 的临床访谈，PHQ-8 标注；AVEC 2016/2017 depression challenge 用的就是它（Ringeval et al., 2017, *AVEC 2017*）。E-DAIC 是扩展版。
- **AVEC 2013/2014**：基于巴西语音-视频抑郁语料，BDI-II 评分；DepNet 在两库上 RMSE=9.17/9.01（He et al.）。
- **D-Vlog / LMVD / MODDMA**：社交媒体自然视频，规模大、噪声高；近一年多模态 SOTA 多在此刷榜。
- **D4**（Yao et al., 2022 *EMNLP*）：中文抑郁诊断对话数据集，4 任务——**这是你做中文智能体最该看的对话标注资源**。

### 3.4 多模态在实时对话中的应用（句级信号如何反馈给策略）

- **已被做的**：Shidara et al.（*JMIR Formative Research*）让 ECA 实时检测心理困扰水平并**自适应调整苏格拉底提问数量**——自适应组比随机问题数组困扰下降更显著。但触发信号是自报/ECG 类，不是视听。
- **已被做的**：PsyAdvisor（Hu et al., 2025 *ACL*）在 ProPsyC 多轮数据集上训练主动提问策略插件，提升对话深度；Deng et al.（2023 *EMNLP Findings*）用 Proactive CoT 触发 LLM 主动澄清。
- **[空白/推测]**：把"这一句用户语音能量骤降/音高变平/注视回避"作为信号喂给 LLM 决策器，让它选择"换温和问法/停下来共情/跳过这个话题"——**这条闭环在检索到的文献里没有现成系统**。MAGI 的 judgment agent 只看文本回答是否满足节点，不看多模态通道。这就是你项目可以写进 related work 的 gap。

---

## 四、特别问题：LLM 做"自适应提问决策"的可行性

### 4.1 已经被研究证实的部分

1. **"判断回答是否满足诊断节点"可以显式建模为独立 agent**：MAGI（Bi et al., 2025）的 judgment agent 专门做这件事，并在 1002 名真实被试上跑通了 MINI 分支逻辑。**架构上可行。**
2. **"根据已检测到的困扰水平调整问题数量/深度"有 RCT 级证据**：Shidara et al. 对比自适应 vs 随机问题数，自适应组困扰下降显著更多。**策略上有效。**
3. **主动提问/澄清是 LLM 可以被提示出来的能力**：Deng et al.（2023 *EMNLP Findings*）Proactive CoT；Hu et al.（2025 *ACL*）PsyAdvisor 用 SFT 插件即可增强。**prompt/SFT 路线成熟。**

### 4.2 尚未解决 / 必须警惕的部分

1. **LLM 判断"回答是否充分"本身的可靠性没有被单独验证**。MentalBench（Badawi et al., 2026）显示 LLM 在"相关性/安全"维度与人类一致性弱、系统性偏高估。**把"够不够追问"交给一个未校准的 LLM judge，是本项目最大的可靠性风险。**
2. **提示敏感性高**：Shu et al.（2024 *NAACL*）证明微调选项顺序、否定句都会显著改变 LLM 在心理测量题上的回答——同一对话、同一答案，换个 prompt 模板就可能得出"需要追问/不需要追问"两种结论。**工程上必须固定 prompt、做多次投票或温度=0，并对决策做回归测试。**
3. **文化/语言偏差**：现有证据几乎全在英文/白人被试；中文场景下 LLM 对"含蓄表达是否算症状阳性"的判断未被验证。

### 4.3 多模态信号如何增强这个判断（设计建议）

> 以下为**基于已有证据的设计外推，不是已发表结论**。

- **[推测]** 当文本回答模糊（"还好""就那样"）时，音频能量/音高变异性骤降 + 视觉注视回避，是比纯文本更强的"这个回答不充分、需要换方式再问"证据。依据：语音能量变异性↓（Gumus et al., 2023）、注视回避/正性注视↓（Suslow et al., 2020 meta）都与抑郁程度相关。
- **[推测]** 当 LLM 判断"该追问"与多模态信号一致时，置信度加权；当两者矛盾（文本说"挺好"但眼动/语音呈典型抑郁模式）时，应触发"温和迂回再探"而不是直接采信文本。这正好对应 UPSD（Cao et al., 2025）的无察觉探针思路。
- **[推测/空白]** 把句级视听特征作为 judgment agent 的额外输入 token（例如在 prompt 里注入"本句用户语音能量低于其本人基线 1.5 SD、注视回避 3 秒"），让 LLM 在做充分性判断时参考——**这一具体做法在检索到的文献中未见先例，可作为本项目的创新点写进 related work 的 gap 段**。

---

## 五、对你项目的直接启示（一页纸结论）

1. **不要让 GPT-4 直接当最终抑郁分类器**——它在 DAIC 上打不过微调 BERT，且有 shortcut 风险（Burdisso et al., 2024）。正确姿势：LLM 做症状结构化 + 推理链，一个轻量分类头（BERT/小 GBT）做最终判决，参考 DORIS（Lan et al., 2025）和 MAGI（Bi et al., 2025）。
2. **Agent 架构直接抄 MAGI 四件套**：访谈树导航 / 自适应提问 / judgment（回答充分性判断）/ 诊断（症状→PHQ-9 映射）。FastAPI 后端拆成四个工具调用即可。
3. **视觉通道保留眼动（注视/扫视）权重**——Flores et al.（2022）证明眼注视是面部子特征里最有信息量的；但要注意"早期定向无差异、晚期维持才有差异"，所以特征要按句/段累积，不要按帧下结论。
4. **音频通道里最稳的是语速/停顿/能量变异性**——这三个有 meta-analysis 或队列证据；jitter/音高范围是次要补充。
5. **多模态融合用晚期融合或 cross-attention，别用早期拼接**；在你自己的小样本测试集上，对纯文本基线预期 +3–8 个 F1 点，别对标 D-Vlog 的 90%+。
6. **judgment agent 的可靠性要做离线回归测试**：固定 prompt、温度=0、多次投票；红线（自杀意念）硬编码，不交给 LLM 自由判断（Heston, 2023；Badawi et al., 2026）。
7. **差异化创新点**：把句级视听特征作为 judgment agent 的上下文输入，让它在"文本模糊"时结合非语言信号决定是否迂回追问——这是文献空白，比赛答辩可讲。

---

## 六、参考文献（按出现顺序，附可访问链接）

1. Hu P, Li H, Li X, et al. Large language model for interview-based depression diagnosis: an empirical study. *J USTC*, 2024. https://justc.ustc.edu.cn/en/article/pdf/preview/10.52396/JUSTC-2023-0088.pdf
2. Shin D, Kim H, Lee S, et al. Using Large Language Models to Detect Depression From User-Generated Diary Text Data: Instrument Validation Study. *JMIR*, 2024. https://www.jmir.org/2024/1/e54617/PDF
3. Arcan M, Niland D-P. Evaluating Large Language Models for Anxiety, Depression, and Stress Detection. arXiv:2511.07044, 2025. https://arxiv.org/pdf/2511.07044.pdf
4. Arcan M, Niland D, Delahunty F. An Assessment on Comprehending Mental Health through Large Language Models. arXiv:2401.04592, 2024. https://arxiv.org/pdf/2401.04592
5. Xu X, Yao B, Dong Y, et al. Mental-LLM: Leveraging LLMs for Mental Health Prediction via Online Text Data. *IMWUT*, 2023. https://dspace.mit.edu/handle/1721.1/154068
6. Yang K, Zhang T, Kuang Z, et al. MentaLLaMA: Interpretable Mental Health Analysis on Social Media with LLMs. arXiv:2309.13567, 2023. https://arxiv.org/pdf/2309.13567
7. Yang K, Ji S, Zhang T, et al. Towards Interpretable Mental Health Analysis with Large Language Models. *EMNLP*, 2023. https://aclanthology.org/2023.emnlp-main.370/
8. Chen Z, Deng J, Zhou J, et al. Depression Detection in Clinical Interviews with LLM-Empowered Structural Element Graph (SEGA). *NAACL*, 2024. https://aclanthology.org/2024.naacl-long.452/
9. Lan X, Han Z, Cheng Y, et al. DORIS: Depression Detection on Social Media with LLMs. *EMNLP Industry*, 2025. https://aclanthology.org/2025.emnlp-industry.151/
10. Rosenman G, Wolf L, Hendler T. LLM Questionnaire Completion for Automatic Psychiatric Assessment. *EMNLP Findings*, 2024. https://aclanthology.org/2024.findings-emnlp.23/
11. Liu JM, Gao M, Sabour S, et al. Enhanced large language models for effective screening of depression and anxiety (EmoScan). *Nature Communications Medicine*, 2025. https://www.nature.com/articles/s43856-025-01158-1
12. Bi G, Chen Z, Liu Z, et al. MAGI: Multi-Agent Guided Interview for Psychiatric Assessment. *ACL Findings*, 2025. https://preview.aclanthology.org/bulk-verify-all/2025.findings-acl.1278.pdf
13. Greene A, Blair N, Mahdipour Aghabagher S, et al. AI Psychiatrist Assistant: An LLM-based Multi-Agent System for Depression Assessment. *PMLR v297*, 2026. https://raw.githubusercontent.com/mlresearch/v297/main/assets/greene26a/greene26a.pdf
14. Wang X, Perez A, Parapar J, Crestani F. TalkDep: Clinically Grounded LLM Personas for Conversation-Centric Depression Screening. *CIKM*, 2025. https://arxiv.org/pdf/2508.04248
15. Cao J, Huang C, Zhang Y, et al. Breaking the Stigma! Unobtrusively Probe Symptoms in Depression Disorder Diagnosis Dialogue (UPSD). *NAACL Findings*, 2025.
16. Yao B, Shi C, Zou L, et al. D4: A Chinese Dialogue Dataset for Depression-Diagnosis-Oriented Chat. *EMNLP*, 2022. https://aclanthology.org/2022.emnlp-main.156/
17. Burdisso S, Reyes-Ramírez EA, Villatoro-Tello E, et al. DAIC-WOZ: On the Validity of Using the Therapist's prompts in Automatic Depression Detection. *ClinicalNLP Workshop*, 2024. https://aclanthology.org/2024.clinicalnlp-1.8/
18. Badawi A, Rahimi E, Laskar MTR, et al. When Can We Trust LLMs in Mental Health? Large-Scale Benchmarks for Reliable LLM Evaluation (MentalBench). *EACL*, 2026. https://preview.aclanthology.org/ingest-nejlt/2026.eacl-long.180.pdf
19. Shu B, Zhang L, Choi M, et al. You don't need a personality test to know these models are unreliable: Assessing the Reliability of LLMs on Psychometric Instruments. *NAACL*, 2024. https://aclanthology.org/2024.naacl-long.295/
20. Gabriel S, Puri I, Xu X, et al. Can AI Relate: Testing LLM Response for Mental Health Support. *EMNLP Findings*, 2024. https://aclanthology.org/2024.findings-emnlp.120/
21. Heston TF. Safety of Large Language Models in Addressing Depression. *Cureus*, 2023. https://pdfs.semanticscholar.org/1554/d7e72a8b5bcad108ff1d0c9014ddfaaebd0f.pdf
22. Plevin D, Hartmann S, Schubert KO, et al. Facial Expression and Predicting and Monitoring Response to Depression Treatment: A Systematic Review. *Depression and Anxiety*, 2022/23.
23. Broulidakis MJ, Kiprijanovska I, Severs L, et al. Optomyography-based sensing of facial expression derived arousal and valence in adults with depression. *Frontiers in Psychiatry*, 2023. https://www.frontiersin.org/articles/10.3389/fpsyt.2023.1232433
24. Girard JM, Cohn JF, Jeni LA, et al. Spontaneous facial expression in unscripted social interactions can be measured automatically. *Psychological Methods*, 2015. https://pmc.ncbi.nlm.nih.gov/articles/PMC4461567/
25. Huang G, Li Y, Zhu H, et al. Emotional stimulation processing characteristics in depression: Meta-analysis of eye tracking findings. *Frontiers in Psychology*, 2022. https://www.frontiersin.org/articles/10.3389/fpsyg.2022.1089654
26. Suslow T, Hulack A, Kersting A, Bodenschatz CM. Attentional biases to emotional information in clinical depression: A systematic and meta-analytic review of eye tracking findings. *Journal of Affective Disorders*, 2020.
27. Takahashi J, Hirano Y, Miura K, et al. Eye Movement Abnormalities in Major Depressive Disorder. *Frontiers in Psychiatry*, 2021. https://www.frontiersin.org/articles/10.3389/fpsyt.2021.673443
28. Bodenschatz CM, Czepluch F, Kersting A, Suslow T. Efficient visual search for facial emotions in patients with major depression. *BMC Psychiatry*, 2021. https://link.springer.com/article/10.1186/s12888-021-03093-6
29. Liu L, Liu L, Wafa HA, et al. Diagnostic accuracy of deep learning using speech samples in depression: a systematic review and meta-analysis. *JAMIA*, 2024.
30. Mijnders C, Janse E, Naarding P, Truong KP. Acoustic characteristics of depression in older adults' speech. *Interspeech*, 2023.
31. Albuquerque L, Valente ARS, Teixeira A, et al. Association between acoustic speech features and non-severe levels of anxiety and depression symptoms across lifespan.
32. Gumus M, DeSouza DD, Xu M, et al. Evaluating the utility of daily speech assessments for monitoring depression symptoms. *Digital Health*, 2023. https://pmc.ncbi.nlm.nih.gov/articles/PMC10328009/
33. Yi H, Smiljanic R, Chandrasekaran B. The Effect of Talker and Listener Depressive Symptoms on Speech Intelligibility. *JSLHR*.
34. Ravi V, Wang J, Flint J, Alwan A. A Step Towards Preserving Speakers' Identity While Detecting Depression Via Speaker Disentanglement. arXiv:2206.09530, 2022. https://arxiv.org/pdf/2206.09530
35. Flores R, Tlachac ML, Toto E, Rundensteiner E. AudiFace: Multimodal Deep Learning for Depression Screening. *PMLR v182*, 2022. https://proceedings.mlr.press/v182/flores22a.html
36. He M, Bakker EM, Lew MS. DPD Net: a deep neural network for multimodal depression detection. *BMC*, 2024. https://pmc.ncbi.nlm.nih.gov/articles/PMC11557813/
37. Sun G, Zhao S, Zou B, An Y. Multimodal depression detection using a deep feature fusion network. SPIE, 2023.
38. Haque MR, Islam MM, Raju SMTU, et al. MMFormer: Multimodal Fusion Transformer Network for Depression Detection. arXiv:2508.06701, 2025. https://arxiv.org/pdf/2508.06701
39. Haque MR, Islam MM, Raju SMTU, et al. MDD-Net: Multimodal Depression Detection through Mutual Transformer. arXiv:2508.08093, 2025. https://arxiv.org/pdf/2508.08093
40. Yue X, Zhang C, Wang Z, et al. DWAM-Former: Hierarchical transformer speech depression detection based on dynamic window and attention merge. *PeerJ Computer Science*.
41. Ringeval F, Schuller B, Valstar M, et al. AVEC 2017: Real-life Depression, and Affect Recognition Workshop and Challenge. *ACM*, 2017.
42. Shidara K, Tanaka H, Adachi H, et al. Adapting the Number of Questions Based on Detected Psychological Distress for CBT With an ECA: Comparative Study. *JMIR Formative Research*.
43. Hu Y, Liu D, Liu B, et al. PsyAdvisor: A Plug-and-Play Strategy Advice Planner with Proactive Questioning in Psychological Conversations. *ACL*, 2025.
44. Deng Y, Liao L, Chen L, et al. Prompting and Evaluating LLMs for Proactive Dialogues. *EMNLP Findings*, 2023.
