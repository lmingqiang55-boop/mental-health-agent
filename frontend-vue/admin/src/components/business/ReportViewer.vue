<template>
  <div v-if="result" class="report-viewer">
    <!-- 1. 整体状态 -->
    <section class="report-block">
      <h3 class="block-title">整体状态</h3>
      <div class="overall-row">
        <div class="concern-dial">
          <el-progress
            type="dashboard"
            :percentage="result.concern_index"
            :color="dialColor"
            :width="140"
          >
            <template #default>
              <div class="dial-num">{{ result.concern_index }}</div>
              <div class="dial-label">关注指数</div>
            </template>
          </el-progress>
        </div>
        <div class="overall-text">
          <el-tag :type="OVERALL_LEVEL_MAP[result.overall_level].type" effect="dark" round>
            {{ OVERALL_LEVEL_MAP[result.overall_level].text }}
          </el-tag>
          <p class="summary">{{ report.overall_status.summary }}</p>
        </div>
      </div>
    </section>

    <!-- 2. 五维画像 -->
    <section class="report-block">
      <h3 class="block-title">五维心理画像 <span class="block-hint">数值越高 = 该维度信号越值得关注</span></h3>
      <DimensionRadar :profile="result.psychological_profile" :height="280" />
    </section>

    <!-- 3. 主要关注点 -->
    <section class="report-block">
      <h3 class="block-title">主要关注点</h3>
      <el-alert
        :title="DIMENSION_MAP[report.primary_concern.dimension] ?? report.primary_concern.dimension"
        :description="report.primary_concern.description"
        type="warning"
        :closable="false"
        show-icon
      />
    </section>

    <!-- 4. 关键发现（可解释依据） -->
    <section class="report-block">
      <h3 class="block-title">关键发现 <span class="block-hint">为什么得出这个结论</span></h3>
      <div class="finding-list">
        <div v-for="(f, i) in report.key_findings" :key="i" class="finding-card">
          <div class="finding-title">{{ i + 1 }}. {{ f.title }}</div>
          <div class="finding-desc">{{ f.description }}</div>
        </div>
      </div>
    </section>

    <!-- 5. 多模态一致性观察 -->
    <section class="report-block">
      <h3 class="block-title">多模态一致性观察</h3>
      <div class="mm-row">
        <el-tag effect="plain" round>
          一致性：{{ CONSISTENCY_MAP[report.multimodal_observation.consistency_level] }}
        </el-tag>
        <span v-if="report.multimodal_observation.consistency_score !== null" class="cell-sub">
          得分 {{ report.multimodal_observation.consistency_score }} / 100
        </span>
      </div>
      <p class="summary">{{ report.multimodal_observation.summary }}</p>
    </section>

    <!-- 6. 趋势与建议 -->
    <section class="report-block">
      <h3 class="block-title">趋势与建议</h3>
      <div class="mm-row">
        <el-tag type="primary" effect="plain" round>{{ TREND_MAP[report.trend_and_suggestions.trend] ?? report.trend_and_suggestions.trend }}</el-tag>
        <span class="cell-sub">{{ report.trend_and_suggestions.trend_summary }}</span>
      </div>
      <ul class="suggestion-list">
        <li v-for="(s, i) in report.trend_and_suggestions.suggestions" :key="i">{{ s }}</li>
      </ul>
    </section>

    <div class="xq-disclaimer">
      本报告由 AI 多模态评估模型生成，仅作为心理关怀参考，不构成医学诊断。如需专业帮助请联系心理教师或专业机构。
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import DimensionRadar from '@/components/business/DimensionRadar.vue'
import { CONSISTENCY_MAP, DIMENSION_MAP, OVERALL_LEVEL_MAP, TREND_MAP } from '@/utils/format'
import type { EvaluationResult } from '@/types'

const props = defineProps<{ result: EvaluationResult | null }>()
const report = computed(() => props.result!.report)

const dialColor = computed(() => {
  const v = props.result?.concern_index ?? 0
  if (v >= 70) return '#e5655b'
  if (v >= 45) return '#f2b84b'
  return '#52b788'
})
</script>

<style scoped>
.report-block { padding: 4px 0 18px; border-bottom: 1px dashed var(--xq-border); }
.report-block:last-of-type { border-bottom: none; }
.block-title { font-size: 15px; margin: 14px 0 12px; }
.block-hint { font-size: 12px; font-weight: 400; color: var(--xq-text-secondary); margin-left: 8px; }

.overall-row { display: flex; gap: 24px; align-items: center; }
.dial-num { font-size: 28px; font-weight: 700; }
.dial-label { font-size: 12px; color: var(--xq-text-secondary); }
.overall-text { flex: 1; }
.summary { line-height: 1.8; margin: 10px 0 0; }

.finding-list { display: flex; flex-direction: column; gap: 10px; }
.finding-card {
  background: var(--xq-primary-lighter);
  border-radius: 8px;
  padding: 12px 14px;
}
.finding-title { font-weight: 600; margin-bottom: 4px; }
.finding-desc { font-size: 13px; color: #6b5a48; line-height: 1.7; }

.mm-row { display: flex; align-items: center; gap: 10px; }
.suggestion-list { margin: 10px 0 0; padding-left: 20px; line-height: 2; }
</style>
