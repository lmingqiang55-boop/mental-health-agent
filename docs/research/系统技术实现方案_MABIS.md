# 系统技术实现方案：多模态感知的自适应抑郁评估（MABIS）

> 项目：心理健康多模态智能体（面向大学生）
> 负责人：A（对话模块），B（多模态）、C（系统/前端）协同
> 版本：v1.0　日期：2026-09-28
> 技术总路线：**不训练大模型；以 LLM API + 提示词工程为主，LoRA/QLoRA 轻量微调开源模型做本地化兜底；确定性的状态机、IRT 选题、危机红线自己写。**

> **版本说明（后补）**：文中「重写 `dialogue_manager.py` 状态机」「扩展
> `SessionState.assessment_state` / `clarify_count`」等改造计划，基于当时尚未删除的
> 六维固定提问状态机。该状态机及其公共字段此后已删除，对话改由已训练决策模型
> 选择下一步动作；引用这些计划前需要先按当前代码重新对齐。

---

## 0. 一页纸总览

**最终能力**：系统与学生自然对话，每答一轮，①模型把回答"翻译"成 PHQ-9 症状分，②贝叶斯更新抑郁潜变量 θ，③结合多模态状态用多目标算法选下一题；结束后输出 **PHQ-9 等价总分（含置信区间）+ 多维症状剖面 + 分层建议**，并对危机信号走独立安全通道。

**核心算法 MABIS（Multimodal-Aware Bayesian Item Selection）= 四个组件**：

| 组件 | 名称 | 职责 | 技术 |
|---|---|---|---|
| LSP | LLM Structured Psychoscoring | 回答 → 症状分(0–3)/充分性/证据 | LLM API（温度0, JSON）+ 规则校验 |
| BOLFI | Bayesian Online Latent-trait Filtering | 逐题贝叶斯更新抑郁潜变量 θ 与不确定性 | GRM 多级 IRT + 贝叶斯后验 |
| **MM-MFI** | Multimodal-modulated Multi-objective Fisher Item selection | **多模态信号回控的多目标选题（核心创新）** | Fisher 信息 + 覆盖 + 多模态相关性 − 曝光 |
| CrisisGuard | 独立危机通道 | 自杀/自伤高灵敏检测与安全处置 | 硬编码规则 + 否定词窗口，独立于 LLM |

**支撑技术**：多模态时序基线跟踪（EWMA）、RAG 临床知识库、Conformal Prediction（可选）、LoRA 本地模型兜底。

---

## 1. 整体架构与数据流

```text
学生（文本 + 摄像头 + 麦克风）
        │
        ▼
 C：FastAPI 接入（chat / vision / audio）+ SessionManager
        │  当前轮：user_text + 句级 VisionState/AudioState
        ▼
┌──────────────────────────────────────────────┐
│ CrisisGuard（最高优先级，独立硬编码）           │
│   命中 → 危机模式：预写话术 + 热线 + 终止        │
└──────────────────┬───────────────────────────┘
                   │ 未命中
                   ▼
┌──────────────────────────────────────────────┐
│ LSP 回答评分（answer_scorer）                  │
│   LLM 结构化：symptom_score / sufficiency /    │
│   evidence；规则 + 多模态校验                  │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│ 写入 item_records（逐题累积，states.py）        │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│ BOLFI：贝叶斯更新 θ 后验（irt_engine, GRM）     │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│ MM-MFI 自适应决策（adaptive_selector）         │
│   不充分→rephrase / 阳性→depth /              │
│   推进→多目标选题 / 达标→finish                │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│ LLM 生成下一句（只决定"怎么表达"）              │
└──────────────────┬───────────────────────────┘
                   │（循环，直到终止）
                   ▼
 finish → AssessmentEngine 聚合：
   θ → PHQ-9 等价总分 + 置信区间
   + 症状簇/六维多维剖面 + 逐题证据 + 分层建议
```

**关键边界**：
- "问什么"由确定性状态机 + MM-MFI 决定，LLM 不自主路由；
- LLM 只做"回答结构化评分"和"自然语言表达"；
- 多模态只影响**充分性、选题权重、置信度**，不直接改症状分（伦理安全 + 可解释）；
- 危机红线硬编码，不交给 LLM。

---

## 2. 题库设计（question_bank）

### 2.1 结构

以 PHQ-9 九题为骨架，每题包含多种问法；另加暖场题与共病/六维补充题。

```json
{
  "items": [
    {
      "id": "phq9_1",
      "symptom": "anhedonia",
      "phq9_item": 1,
      "dimension": "mood",
      "irt_a": 1.8,
      "irt_b": [0.1, 0.9, 1.8],
      "primary": "最近两周，做平时喜欢的事情时，还提得起劲吗？",
      "probes": [
        "这种情况大概持续多久了？",
        "对你的学习或生活有什么具体影响吗？",
        "是完全没兴趣，还是兴趣减少了？"
      ],
      "rephrasings": [
        "有没有什么以前觉得有意思、现在却不想做的事？",
        "最近有没有觉得做什么都提不起劲的时候？"
      ],
      "severity_anchors": {
        "0": "完全没有/和以前一样",
        "1": "几天/偶尔",
        "2": "一半以上天数/经常",
        "3": "几乎每天/总是"
      }
    }
  ],
  "warmup": [
    {"id": "warmup_1", "primary": "最近整体状态怎么样？可以随便聊聊。"},
    {"id": "warmup_2", "primary": "如果用几个词形容现在的自己，你会想到什么？"}
  ],
  "supplements": [
    {"id": "gad7_1", "symptom": "anxiety", "dimension": "pressure",
     "primary": "最近会不会经常感到紧张、担心或焦虑？"},
    {"id": "inter_1", "symptom": "interpersonal", "dimension": "interpersonal",
     "primary": "遇到烦心事时，身边有可以说说话的人吗？"}
  ],
  "crisis_item": "phq9_9"
}
```

### 2.2 规模与映射

- PHQ-9 × (1 primary + 3 probes + 2 rephrasings) ≈ 54 话术节点；
- + 2 warmup + 3–4 补充（焦虑 GAD-7、人际、自我认知）；
- 每个 PHQ-9 题映射到现有六维之一，保证多维剖面可生成。

| PHQ-9 题 | 症状 | 映射六维 | 症状簇 |
|---|---|---|---|
| 1 兴趣减退 | anhedonia | mood 情绪 | 情感 |
| 2 情绪低落 | depressed_mood | mood 情绪 | 情感 |
| 3 睡眠问题 | sleep | study_life 学习生活 | 躯体 |
| 4 精力不足 | fatigue | study_life 学习生活 | 躯体 |
| 5 食欲变化 | appetite | study_life 学习生活 | 躯体 |
| 6 自责无价值 | worthlessness | self_cognition 自我认知 | 认知 |
| 7 注意困难 | concentration | study_life 学习生活 | 认知 |
| 8 精神运动异常 | psychomotor | mood 情绪 | 躯体 |
| 9 自杀意念 | suicidal | —（独立） | 危机 |

---

## 3. 组件一：LSP 结构化症状评分

### 3.1 输出结构

```python
class AnswerScore(BaseModel):
    item_id: str
    symptom_score: float          # 0.0–3.0，对齐 PHQ-9
    sufficiency: float            # 0.0–1.0，是否具体到可计分
    confidence: float             # 0.0–1.0
    evidence: list[str]           # 原话片段
    frequency_hint: str | None = None   # none/days/most_days/nearly_everyday
    need_reprobe: bool = False    # 文本模糊 + 多模态困扰
    discrepancy: bool = False     # 文本与非语言信号矛盾
```

### 3.2 LLM Prompt 设计（API，temperature=0，JSON mode）

```text
System：你是严格依据 PHQ-9 标准对访谈回答评分的助手。只输出 JSON，不输出多余内容。
评分依据（0–3 语言锚点）：
  0 = 完全没有/和以前一样
  1 = 几天/偶尔
  2 = 一半以上天数/经常
  3 = 几乎每天/总是

当前题目：{item.primary}
学生回答：{user_text}

输出 JSON：
{"symptom_score": 0-3 的数字,
 "sufficiency": 0-1 的数字（回答是否包含频率/持续时间/具体影响）,
 "evidence": ["可作为证据的原话片段"],
 "frequency_hint": "none/days/most_days/nearly_everyday",
 "reasoning": "一句话依据"}
```

工程要点：
- **temperature=0 + response_format=json**；可做 3 次 self-consistency 投票，取中位数分数；
- 注入 2–3 个 few-shot（含模糊、阳性、否定三类）；
- **phq9_9（自杀题）不经过 LLM**，走 CrisisGuard 硬编码。

### 3.3 规则校验（双保险，MentalBench 显示 LLM judge 在相关性维度会高估）

```python
VAGUE = {"嗯","哦","好","还行","还好","不知道","不清楚"}

def validate(score, user_text, mm_state):
    t = user_text.strip()
    if len(t) < 5 or t.lower() in VAGUE:
        score.sufficiency = min(score.sufficiency, 0.3)
    # 多模态矛盾：文本阴性但视听持续异常
    if score.symptom_score <= 1 and mm_state.persistent_concern:
        score.discrepancy = True
        score.need_reprobe = True
    # 文本模糊 + 多模态困扰 → 迂回再探
    if score.sufficiency < 0.4 and mm_state.acute_concern:
        score.need_reprobe = True
    return score
```

---

## 4. 组件二：BOLFI 贝叶斯在线潜特质更新

采用 **Samejima GRM（Graded Response Model）**，适配 0–3 多级计分。

### 4.1 GRM 概率

累计类别概率（在 θ 处得 ≥ k 分）：

```text
P*(u_j ≥ k | θ) = 1 / (1 + exp[-a_j · (θ - b_{jk})]),  k = 1,2,3
```

恰好得 k 分：

```text
P(u_j = 0 | θ) = 1 - P*(≥1)
P(u_j = k | θ) = P*(≥k) - P*(≥k+1),  k = 1,2
P(u_j = 3 | θ) = P*(≥3)
```

- a_j：区分度（斜率）；b_{jk}：题目 j 第 k 个类别边界难度。

### 4.2 贝叶斯后验更新（每答一题）

```text
先验：P(θ) = N(0, 1)
后验：P(θ | u_{1:t}) ∝ P(θ) · ∏_{j∈answered} P(u_j | θ)
```

工程实现（任选）：
- **网格法**：θ ∈ [-4,4] 取 201 点，逐点乘似然，归一化，得后验分布；
- 输出 θ̂（后验均值）、Var(θ)、SE = √Var；
- 无第三方依赖、稳定可复现，推荐 Phase 1 使用。

```python
import numpy as np

GRID = np.linspace(-4, 4, 201)

def grm_category_prob(theta, a, bs):
    cum = [1/(1+np.exp(-a*(theta-b))) for b in bs]
    p0 = 1-cum[0]
    p = [cum[k]-cum[k+1] for k in range(len(bs)-1)]
    return [p0, *p, cum[-1]]

def update_posterior(posterior, item, score_category):
    probs = grm_category_prob(GRID, item.a, item.b)
    likelihood = probs[score_category]
    posterior = posterior * likelihood
    return posterior / posterior.sum()

def theta_summary(posterior):
    mean = (GRID * posterior).sum()
    var = (((GRID-mean)**2) * posterior).sum()
    return mean, var**0.5
```

### 4.3 参数初始化

- 用已发表 PHQ-9 IRT 参数做先验（Bianchi et al. 2022, n=58,272；Ma et al. 2021）；
- 收集 ≥200–300 份大学生回答后用 EM 重新标定；
- 比赛阶段标注"参数待标定"，先验即可演示。

---

## 5. 组件三：MM-MFI 多模态调制多目标选题（核心创新）

### 5.1 多目标打分

对每个未答项 j 计算：

```text
S(j) = λ1 · Î_j(θ̂)        // Fisher 信息（量表效率，归一化）
     + λ2 · Cov(j)         // 症状域覆盖奖励
     + λ3 · MM(j)          // 多模态相关性（创新项）
     − λ4 · Exp(j)         // 曝光/重复惩罚

j* = argmax_j S(j)
```

建议初值 λ = (0.45, 0.20, 0.25, 0.10)，后续离线调参。

### 5.2 各项定义

**Fisher 信息（GRM）**：

```text
Î_j(θ) = Σ_k ( [∂P(u=k|θ)/∂θ]² / P(u=k|θ) )
```

归一化到 [0,1]（除以题库最大值）。

**覆盖 Cov(j)**：该症状域未覆盖 = 1，否则 0。

**曝光 Exp(j)**：该题/该问法本会话已用次数（归一化）。

**多模态相关性 MM(j)（核心）**：

建立"多模态特征 → 症状项"关联（基于文献 meta），用当前多模态异常强度加权：

```text
MM(j) = σ( Σ_m W[m→j] · z_m )
```

- z_m：当前多模态特征的标准化异常分（相对个人基线）；
- W[m→j]：特征 m 对症状项 j 的关联权重，例如：

| 多模态特征 | 异常表现 | 关联症状项 |
|---|---|---|
| energy / speech_rate | ↓ 能量低、语速慢 | phq9_4 精力、phq9_3 睡眠 |
| pause_ratio | ↑ 停顿多 | phq9_4、整体严重度 |
| valence | ↓ 效价低 | phq9_2 情绪、phq9_1 |
| emotion=sad | 持续悲伤 | phq9_2、phq9_6 |
| engagement / gaze | ↓ 参与低、注视回避 | interpersonal、self_cognition |
| pitch variability | ↓ 语调平 | 整体抑郁、phq9_2 |

效果：当系统检测到学生能量持续偏低，会**优先把"精力/睡眠"相关题提前**；效价持续低则优先情绪题。这就是"**多模态信号实时回控提问**"的可计算实现——现有自适应系统（ALIRT/MAGI/PROMIS）的触发信号全部来自文本，未见此闭环，属文献空白。

### 5.3 硬约束（先于打分）

- 必须覆盖 ≥5 个 PHQ-9 症状域；
- θ̂ > 1.5（中重度倾向）→ 强制优先 phq9_9（自杀题）与高严重度题；
- θ̂ < −0.5（低风险）→ 优先高区分度核心症状题确认阴性；
- 同一 rephrasing 不重复使用。

### 5.4 每轮决策树

```text
1. 危机命中？ → CrisisGuard（最高优先级）
2. 充分性 sufficiency：
     <0.4 且 多模态困扰 → rephrase（温和换角度，不重复原话）
     <0.4 且 clarify_count[item] < 2 → 通用 probe（"能再具体说说吗"）
     <0.4 且 澄清用尽 → 标记 insufficient，部分分+低置信，继续下一项
3. 阳性深度追问：symptom_score ≥ 2 且 not depth_probed
     → depth（SCID 式：持续时间 / 功能损害 / 频率）
4. 正常推进：MM-MFI 选题
5. 终止（任一）：
     SE(θ̂) ≤ 0.4 且 覆盖 ≥5 域
     达最大轮数（12 轮，约 8–10 分钟）
     用户明确停止
```

---

## 6. 多模态时序基线跟踪（MM-MFI 的支撑）

```python
class MultimodalTracker:
    """逐用户跟踪多模态基线（EWMA），检测矛盾与急变。"""
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.baseline = {}      # 特征 -> EWMA 均值
        self.residual = {}      # 特征 -> EWMA 方差
        self.history = []

    def update(self, features: dict):
        for k, v in features.items():
            if v is None: continue
            if k not in self.baseline:
                self.baseline[k], self.residual[k] = v, 0.05
            else:
                d = v - self.baseline[k]
                self.baseline[k] += self.alpha * d
                self.residual[k] = (1-self.alpha)*(self.residual[k]+self.alpha*d*d)
        self.history.append(features)

    def z_score(self, key, value):
        if key not in self.baseline: return 0.0
        sd = max(self.residual[key]**0.5, 1e-3)
        return (value - self.baseline[key]) / sd

    def acute_change(self, features):
        # 当前轮比个人基线低 >1.5 SD → 先共情暂停
        return any((v is not None) and self.z_score(k, v) < -1.5
                   for k, v in features.items())

    def persistent_concern(self, key, thresh=-0.8, rounds=3):
        recent = [h.get(key) for h in self.history[-rounds:]]
        vals = [self.z_score(key, x) for x in recent if x is not None]
        return len(vals) >= rounds and all(z < thresh for z in vals)
```

- **acute change**：valence/energy 骤降 → 插入共情轮（"听起来这件事让你挺难受的"），再决定是否继续；
- **persistent concern**：文本阴性但多模态跨 ≥3 轮持续异常 → discrepancy，触发 UPSD 式间接探针（如说"睡得挺好"却能量低 → 改问"白天精力怎么样"）。

---

## 7. 组件四：CrisisGuard 独立危机通道

- **独立于对话 LLM**，在所有流程最前面调用；
- 硬编码危机关键词 + **否定词窗口**（"我不想自杀""我没有想过自残"不判高危）；
- 触发条件：phq9_9 得分 ≥ 1，或危机词命中且无否定修饰；
- 处置：
  1. **预写、非生成、人工审核过的共情话术**；
  2. 显示本地热线（北京 010-82951332；全国希望24 400-161-9995；校心理中心）；
  3. 可选询问紧急联系人；
  4. **终止自动对话**，不继续"陪伴"。
- 偏保守（高灵敏度），疑似即转人工，由人筛假阳性。

---

## 8. 评估引擎与打分输出（AssessmentEngine 改造）

### 8.1 主打分：θ → PHQ-9 等价分

```text
1. θ̂、SE 来自 BOLFI 后验；
2. θ → PHQ-9 等价总分：
   - 等百分位映射（θ 百分位 → PHQ-9 总分对应百分位）；
   - 标定数据上可用线性/单调回归；
3. 严重度（中国大学生 cutoff=11）：
   0–4 无 / 5–10 轻度 / 11–14 中度 / 15–19 中重度 / 20–27 重度
```

### 8.2 多维剖面

- **症状簇**：情感（phq9_1,2）、认知（phq9_6,7）、躯体（phq9_3,4,5,8）、危机（phq9_9）；
- **六维**：情绪/压力/人际/自我认知/学习生活/持续时间；
- 每维：得分 + 置信度 + 证据 + 趋势。

### 8.3 多模态角色

- 不直接加减分；一致→提置信，矛盾→降置信并标记 discrepancy；
- 老师端展示效价/能量趋势作辅助。

### 8.4 输出（扩展 AssessmentResult）

```json
{
  "phq9_equivalent": 13,
  "severity": "moderate",
  "confidence": 0.78,
  "confidence_interval": [10, 15],
  "standard_error": 0.35,
  "dimension_scores": [ {"dimension":"mood","score":0.7,"evidence":["..."]} ],
  "symptom_cluster_profile": {"affective":2.0,"cognitive":1.5,"somatic":2.2,"crisis":0},
  "per_item_scores": [ {"item":1,"score":2,"evidence":"..."} ],
  "multimodal_notes": ["后半段语音能量持续偏低"],
  "discrepancy_flags": ["第3题文本称还好但多模态显示困扰"],
  "recommendations": [ {"category":"help_resource","content":"建议咨询校心理中心","priority":1} ],
  "disclaimer": "本结果为初步筛查，不构成临床诊断，建议专业机构面诊"
}
```

### 8.5 可选前沿：Conformal Prediction

- 在标定集上用 **split conformal** 学习 PHQ-9 预测的误差分位数；
- 输出带覆盖率保证（如 90%）的预测区间，增强医疗可信度；
- 实现简单（一次校准），是答辩中"不确定性量化"的亮点。

---

## 9. 轻量化微调（LoRA/QLoRA）本地兜底方案

**定位**：不从头训练；只微调开源模型做"LSP 结构化评分员"，本地部署，解决隐私（数据不出校）、API 断网/成本兜底。

### 9.1 基座选择

| 模型 | 规模 | 说明 |
|---|---|---|
| Qwen2.5-7B-Instruct | 7B | 首选，中文与结构化输出强 |
| GLM-4-9B-Chat | 9B | 中文优秀，可商用（看许可） |
| Qwen2.5-3B-Instruct | 3B | 量化后 CPU/小显存可跑 |

### 9.2 微调方法

- **LoRA**（rank=8/16，只训 adapter，占原参数 <1%）；
- **QLoRA**（4bit NF量化基座 + LoRA），单张消费级 GPU 数小时；
- 单任务：(题目 + 回答) → PHQ-9 症状分 JSON；
- 框架：PEFT + transformers + bitsandbytes；
- 评估：与 GPT-4 评分一致性、症状分 MAE、JSON 合法率、重测一致性。

### 9.3 训练数据（公开 + 合成 + 少量自标）

- **D4**（中文抑郁诊断对话，Yao et al. EMNLP 2022）；
- **DAIC-WOZ**（USC ICT 申请 DUA）；
- **PsyInterview**（EmoScan 合成 1157 段，随论文）；
- 自标注：强模型生成 (题目,回答,分数)，人工抽检校正。

### 9.4 部署与切换

- **vLLM**（GPU，OpenAI 兼容接口）/ **llama.cpp GGUF**（CPU 量化）/ **Ollama**；
- 通过 `LLM_PROVIDER` 切换：`cloud`（API）/ `local`（LoRA 模型）/ `mock`；
- 接口统一，业务代码无感知。

### 9.5 更轻替代

- 用 **Chinese-BERT-wwm / RoBERTa** 微调做症状 0–3 回归或二分类，参数百 M 级、CPU 可跑，作为评分辅助/校验。

---

## 10. 分阶段落地与验收

### Phase 0：协议 + 题库（3–5 天）

| 任务 | 文件 | 验收 |
|---|---|---|
| 数据协议 | models/states.py（AnswerScore/ItemRecord/item_records/current_item_id/theta）、models/assessment.py、enums.py（WARMUP/ADAPTIVE_SCREENING/DEPTH_PROBE/SYNTHESIS） | 字段完整、兼容旧字段、pytest 通过 |
| 题库 | data/question_bank.json + core/question_bank.py | 可加载，含 primary/probes/rephrasings/anchors/IRT 先验 |

### Phase 1：确定性闭环 + LLM 评分（1–2 周）

| 任务 | 文件 | 验收 |
|---|---|---|
| LSP 评分（API + 规则兜底） | core/answer_scorer.py、llm/cloud_client.py、prompts.py | 给定回答输出 0–3 分/充分性/证据 |
| 重写状态机 | core/dialogue_manager.py、core/adaptive_selector.py | 随回答决定追问/换题/终止，不再固定六维 |
| BOLFI（先用先验参数、网格后验） | core/irt_engine.py | 输出 θ̂/SE，逐题更新 |
| MM-MFI 简化版 | core/adaptive_selector.py | 覆盖+严重度+多模态权重共同选题 |
| CrisisGuard | core/risk_engine.py | 危机命中绕过一切 |
| 评估聚合 | core/assessment_engine.py | PHQ-9 等价分 + 多维剖面 + 证据 |

Phase 1 结束：状态驱动、逐题打分、输出量表分与剖面的完整闭环。

### Phase 2：完整 IRT + 多模态回控 + 本地 LoRA（2–3 周）

- MM-MFI 完整多目标接入；
- 多模态时序基线/矛盾/急变共情；
- LoRA 微调 + 本地部署，provider 三档切换；
- 验收：不同人问题路径不同，多模态能改变提问，本地兜底可跑，断网可演示。

### Phase 3：评估、消融、打磨（1–2 周）

- 离线模拟（D4/DAIC）：自适应 vs 固定顺序的"题数–精度"曲线；
- 消融：无多模态回控 / 无 IRT / 无深度追问；
- Burdisso 式 shortcut 消融（仅患者回答 vs 含系统提问）；
- Conformal 区间（可选）、可靠性/重测一致性；
- 老师端报告、知情同意、措辞合规、答辩材料。

---

## 11. 文件改动清单

**新增**
```
backend/core/question_bank.py
backend/core/answer_scorer.py
backend/core/irt_engine.py
backend/core/adaptive_selector.py
backend/core/multimodal_tracker.py
backend/data/question_bank.json
backend/llm/cloud_client.py      # 真实 API（OpenAI 兼容：DeepSeek/GLM/通义）
backend/llm/local_client.py      # vLLM/Ollama 兼容
training/lora_finetune.py        # LoRA/QLoRA
eval/simulate_cat.py             # 自适应离线模拟
eval/ablation.py
```

**改造**
```
backend/models/enums.py          # 新增阶段/症状簇枚举
backend/models/states.py         # AnswerScore/ItemRecord/item_records/theta
backend/models/assessment.py     # PHQ-9 等价分/症状簇剖面/区间
backend/core/dialogue_manager.py # 评分→决策→生成
backend/core/assessment_engine.py# θ→PHQ-9 + 多维
backend/core/risk_engine.py      # CrisisGuard 强化
backend/llm/client.py            # provider 路由 cloud/local/mock
backend/llm/prompts.py           # 评分 prompt + warmup/probe/depth/rephrase
frontend AssessmentResultView    # 剖面图 + 量表分 + 证据
```

---

## 12. 不可妥协的红线

1. 只说"评估/风险提示"，不说"诊断/确诊"（《精神卫生法》第 23 条）；
2. 自杀红线硬编码，不交给 LLM；
3. 多模态只影响提问策略/充分性/置信度，不直接改症状分；
4. 原始音视频端侧处理，只上传特征向量；分层知情同意；
5. main 分支永远可运行；合并前 pytest + build 通过。

---

## 13. 核心参考文献

1. Varadarajan et al. ALBA/ALIRT. NAACL 2024. arXiv:2311.06467
2. Bi et al. MAGI. ACL Findings 2025.
3. Liu et al. EmoScan. Nat Commun Med 2025.
4. Zhang et al. PHQ-9 中国大学生验证. Asia-Pac Psychiatry 2016（cutoff=11）
5. Bianchi et al. PHQ-9 单维度性. Psychological Assessment 2022（n=58,272）
6. Gibbons et al. CAT-MH. Annu Rev Clin Psychol 2016
7. Morris et al. 多维 CAT. JAMIA 2017
8. Chalmers. mirt (JSS 2012) / mirtCAT (JSS 2016)
9. Liu et al. 语音 DL 抑郁 meta. JAMIA 2024（acc 0.87）
10. Crawford & Glatard. AI 自杀预防. CMAJ 2025

*本方案为比赛技术设计；标注"待验证/待标定"的内容需在实验中验证，不作为已证实结论。*
