<script setup lang="ts">
import { computed } from 'vue'
import type { DimensionKey, EvaluationResult, OverallLevel, Profile5 } from '@/api/types'
import PxCard from '@/components/base/PxCard.vue'
import PxTag from '@/components/base/PxTag.vue'
import DimensionRadar from '@/components/business/DimensionRadar.vue'

const props = defineProps<{ result: EvaluationResult }>()

/** 报告只展示可解释叙述内容；不展示 student_ref / assessment_method / metadata / risk_score / key_evidence。 */
const report = computed(() => props.result.report)

const LEVEL: Record<OverallLevel, { label: string; tone: 'success' | 'secondary' | 'warning' | 'danger'; color: string }> = {
  low_concern: { label: '状态较平稳', tone: 'success', color: 'var(--xq-level-low)' },
  mild_concern: { label: '轻度关注', tone: 'secondary', color: 'var(--xq-level-mild)' },
  moderate_concern: { label: '中度关注', tone: 'warning', color: 'var(--xq-level-moderate)' },
  high_concern: { label: '高度关注', tone: 'danger', color: 'var(--xq-level-high)' },
}
const level = computed(() => LEVEL[props.result.overall_level])

const DIM_LABELS: Record<DimensionKey, string> = {
  emotion: '情绪',
  interest_motivation: '兴趣动力',
  sleep_energy: '睡眠精力',
  attention_thinking: '注意力思维',
  social_daily: '社交日常',
}
const dim = computed(() => {
  const key = report.value?.primary_concern.dimension
  return key ? DIM_LABELS[key] : '综合'
})

const TREND_LABELS: Record<string, string> = {
  improving: '较上次向好',
  stable: '基本平稳',
  fluctuating: '有起伏',
  worsening: '较上次下降',
  unclear: '暂不明确',
}
const trend = computed(() => props.result.report?.trend_and_suggestions)

const consistencyLabels: Record<string, string> = {
  low: '语言与表情：差异较大',
  moderate: '语言与表情：大体一致',
  high: '语言与表情：比较一致',
  unknown: '暂不评估',
}

const dims = computed(() => {
  const p = props.result.psychological_profile
  return (Object.keys(DIM_LABELS) as DimensionKey[]).map((k) => ({
    key: k,
    label: DIM_LABELS[k],
    value: Math.max(0, Math.min(100, Math.round((p[k as keyof Profile5] ?? 0)))),
  }))
})
</script>

<template>
  <div class="report">
    <!-- 总览 -->
    <PxCard tone="primary" class="report__overall">
      <div class="report__overall-row">
        <div
          class="report__gauge xq-gauge-in"
          :style="{ '--val': Math.round(result.concern_index), '--gauge-color': level.color }"
        >
          <span class="report__gauge-num">{{ Math.round(result.concern_index) }}</span>
          <span class="report__gauge-unit">关注指数</span>
        </div>
        <div class="report__overall-main">
          <div class="report__overall-tags">
            <PxTag tone="primary" size="sm">PHQ-9</PxTag>
            <PxTag :tone="level.tone">{{ level.label }}</PxTag>
          </div>
          <p v-if="report" class="report__summary">{{ report.overall_status.summary }}</p>
          <p class="report__overall-note">本结果仅作参考，不构成医学诊断</p>
        </div>
      </div>
    </PxCard>

    <!-- 五维画像 -->
    <PxCard title="因子得分" class="report__block">
      <DimensionRadar :profile="result.psychological_profile" :height="270" />
      <ul class="report__dims">
        <li v-for="d in dims" :key="d.key" class="report__dim">
          <span class="report__dim-name">{{ d.label }}</span>
          <span class="report__dim-bar">
            <i
              :style="{
                width: `${d.value}%`,
                background:
                  d.value >= 75
                    ? 'var(--xq-level-high)'
                    : d.value >= 50
                      ? 'var(--xq-level-moderate)'
                      : d.value >= 25
                        ? 'var(--xq-level-mild)'
                        : 'var(--xq-level-low)',
              }"
            />
          </span>
          <span class="report__dim-val">{{ d.value }}</span>
        </li>
      </ul>
      <p v-if="report" class="xq-muted report__dim-note">
        主要关注方向：{{ dim }} · {{ report.primary_concern.description }}
      </p>
    </PxCard>

    <!-- 关键发现 -->
    <PxCard v-if="report?.key_findings?.length" title="为什么得出这个结论" class="report__block">
      <ul class="report__findings">
        <li v-for="(f, i) in report.key_findings" :key="i" class="report__finding">
          <span class="report__finding-star xq-star">✦</span>
          <div>
            <div class="report__finding-title">{{ f.title }}</div>
            <p class="xq-muted">{{ f.description }}</p>
          </div>
        </li>
      </ul>
    </PxCard>

    <!-- 多模态观察 -->
    <PxCard v-if="report" title="多模态观察" class="report__block">
      <div class="report__row">
        <PxTag tone="default">{{ consistencyLabels[report.multimodal_observation.consistency_level] }}</PxTag>
      </div>
      <p class="report__summary">{{ report.multimodal_observation.summary }}</p>
    </PxCard>

    <!-- 趋势与建议 -->
    <PxCard v-if="trend" title="给你的小建议" class="report__block">
      <div class="report__row">
        <PxTag tone="star">{{ TREND_LABELS[trend.trend] ?? '—' }}</PxTag>
      </div>
      <p class="report__summary">{{ trend.trend_summary }}</p>
      <ul v-if="trend.suggestions?.length" class="report__suggestions">
        <li v-for="(s, i) in trend.suggestions" :key="i">
          <span class="report__sug-num">{{ i + 1 }}</span>
          <span>{{ s }}</span>
        </li>
      </ul>
    </PxCard>

    <!-- 关注提示（不做诊断、不展示分值/证据） -->
    <PxCard
      v-if="result.risk && (result.risk.risk_level !== 'low' || result.risk.risk_reasons?.length)"
      :tone="result.risk.risk_level === 'high' ? 'danger' : 'warn'"
      title="关注提示"
      class="report__block"
    >
      <ul v-if="result.risk.risk_reasons?.length" class="report__reasons">
        <li v-for="(r, i) in result.risk.risk_reasons" :key="i">{{ r }}</li>
      </ul>
      <p class="xq-muted">
        若你正感到难以承受，请随时联系校内心理老师，或拨打全国心理援助热线
        <b>12356</b>（24 小时，可匿名）。
      </p>
    </PxCard>

    <p class="report__disclaimer">
      本报告为初步筛查结果，仅用于自我了解与关注提示，<b>不构成医学诊断</b>，也不代表任何确定性结论。
      请勿据此自行判断病情；如有需要，请咨询专业心理或医疗人员。
    </p>
  </div>
</template>

<style scoped>
.report {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-4);
}

/* ---- 总览 ---- */
.report__overall-row {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-4);
}
.report__gauge {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 96px;
  height: 96px;
  border-radius: 50%;
  background: radial-gradient(circle at 70% 30%, var(--xq-primary-soft) 0%, var(--xq-surface) 70%);
  box-shadow: inset 0 0 0 6px var(--xq-primary-soft), 0 8px 24px rgba(255, 138, 92, 0.18);
}
.report__gauge-num {
  font-family: var(--xq-font-pixel);
  font-weight: 800;
  font-size: var(--xq-fs-3xl);
  line-height: 1;
  color: var(--gauge-color, var(--xq-primary-deep));
}
.report__gauge-unit {
  margin-top: 2px;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.report__overall-main {
  flex: 1;
  min-width: 0;
}
.report__overall-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xq-sp-2);
}
.report__summary {
  margin-top: var(--xq-sp-3);
  line-height: 1.75;
}
.report__overall-note {
  margin-top: var(--xq-sp-2);
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-disabled);
}

/* ---- 因子得分 ---- */
.report__dims {
  margin-top: var(--xq-sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
}
.report__dim {
  display: grid;
  grid-template-columns: 72px 1fr 34px;
  align-items: center;
  gap: var(--xq-sp-2);
  font-size: var(--xq-fs-sm);
}
.report__dim-name {
  color: var(--xq-text-2);
}
.report__dim-bar {
  height: 14px;
  border-radius: 999px;
  background: var(--xq-primary-soft);
  display: block;
  overflow: hidden;
}
.report__dim-bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--xq-primary);
  transition: width var(--xq-dur-slow) var(--xq-ease-base);
}
.report__dim-val {
  text-align: right;
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-xs);
}
.report__dim-note {
  margin-top: var(--xq-sp-3);
}

/* ---- 关键发现 ---- */
.report__findings {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
}
.report__finding {
  display: flex;
  gap: var(--xq-sp-2);
  padding: var(--xq-sp-3);
  border-radius: var(--xq-radius-m);
  background: var(--xq-surface-2);
}
.report__finding-star {
  font-size: 14px;
  margin-top: 3px;
}
.report__finding-title {
  font-family: var(--xq-font-pixel);
  font-weight: 600;
  font-size: var(--xq-fs-base);
}

/* ---- 建议列表（橙色序号圆点） ---- */
.report__suggestions {
  margin-top: var(--xq-sp-3);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.report__suggestions li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  line-height: 1.75;
}
.report__sug-num {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--xq-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  margin-top: 1px;
}

/* ---- 风险提示 ---- */
.report__reasons {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: var(--xq-sp-3);
}
.report__reasons li {
  position: relative;
  padding-left: 18px;
  line-height: 1.7;
}
.report__reasons li::before {
  content: '▸';
  position: absolute;
  left: 0;
  color: var(--xq-primary-deep);
}
.report__row {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
}

/* ---- 免责声明 ---- */
.report__disclaimer {
  padding: var(--xq-sp-3) var(--xq-sp-4);
  border-radius: var(--xq-radius-m);
  background: var(--xq-surface-2);
  color: var(--xq-text-2);
  font-size: var(--xq-fs-xs);
  line-height: 1.7;
}
</style>
