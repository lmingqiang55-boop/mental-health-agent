<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">统计报表</h2>
        <p class="page-subtitle">数据源：/api/teacher/group-stats + /api/teacher/records；年级/班级对比待后端扩展</p>
      </div>
      <el-button :icon="Refresh" circle @click="load" />
    </div>

    <div v-loading="loading">
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">覆盖学生数</div>
          <div class="kpi-value is-primary">{{ stats?.total_students ?? '—' }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">评估记录总数</div>
          <div class="kpi-value">{{ records.length }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">高风险人数</div>
          <div class="kpi-value is-high">{{ riskDist.high ?? 0 }}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">待认领预警</div>
          <div class="kpi-value is-medium">{{ pendingCount }}</div>
        </div>
      </div>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="12">
          <div class="xq-card">
            <h3 class="card-title">风险等级分布</h3>
            <div ref="pieEl" class="chart" />
          </div>
        </el-col>
        <el-col :span="12">
          <div class="xq-card">
            <h3 class="card-title">五维均值对比</h3>
            <div ref="barEl" class="chart" />
          </div>
        </el-col>
      </el-row>

      <div class="xq-card" style="margin-top: 16px">
        <h3 class="card-title">测评记录按日趋势</h3>
        <div ref="lineEl" class="chart" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import type { EChartsOption } from 'echarts'
import { teacherApi } from '@/api'
import { useChart } from '@/composables/useChart'
import { DIMENSION_MAP, RISK_MAP } from '@/utils/format'
import type { GroupStats, RecordSummary, RiskLevel } from '@/types'

const loading = ref(false)
const stats = ref<GroupStats | null>(null)
const records = ref<RecordSummary[]>([])

const riskDist = computed(() => stats.value?.risk_distribution ?? {})
const pendingCount = computed(() => records.value.filter((r) => r.follow_up_status === 'pending').length)

const pieOption = computed<EChartsOption | null>(() => {
  if (!stats.value) return null
  const order: RiskLevel[] = ['low', 'medium', 'high']
  const colors = { low: '#52b788', medium: '#f2b84b', high: '#e5655b' }
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['45%', '68%'],
      center: ['50%', '44%'],
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { formatter: '{b}\n{c} 人' },
      data: order.filter((k) => riskDist.value[k] !== undefined).map((k) => ({
        name: RISK_MAP[k].text, value: riskDist.value[k], itemStyle: { color: colors[k] },
      })),
    }],
  }
})

const barOption = computed<EChartsOption | null>(() => {
  if (!stats.value) return null
  const dims = Object.keys(DIMENSION_MAP) as (keyof typeof DIMENSION_MAP)[]
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 20, top: 20, bottom: 0, containLabel: true },
    xAxis: { type: 'value', max: 100 },
    yAxis: { type: 'category', data: dims.map((d) => DIMENSION_MAP[d]) },
    series: [{
      type: 'bar', barWidth: 18,
      itemStyle: { borderRadius: [0, 8, 8, 0], color: '#f0833c' },
      data: dims.map((d) => stats.value?.dimension_averages[d] ?? 0),
    }],
  }
})

const lineOption = computed<EChartsOption | null>(() => {
  if (!records.value.length) return null
  const byDate = new Map<string, number>()
  for (const r of records.value) {
    const d = dayjs(r.created_at).format('MM-DD')
    byDate.set(d, (byDate.get(d) ?? 0) + 1)
  }
  const days = [...byDate.keys()].sort()
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 20, top: 20, bottom: 0, containLabel: true },
    xAxis: { type: 'category', data: days },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      type: 'line', smooth: true, areaStyle: { color: 'rgba(240,131,60,0.12)' },
      itemStyle: { color: '#f0833c' }, lineStyle: { color: '#f0833c' },
      data: days.map((d) => byDate.get(d)),
    }],
  }
})

const pieEl = useTemplateRef<HTMLElement>('pieEl')
const barEl = useTemplateRef<HTMLElement>('barEl')
const lineEl = useTemplateRef<HTMLElement>('lineEl')
useChart(pieEl, pieOption)
useChart(barEl, barOption)
useChart(lineEl, lineOption)

async function load() {
  loading.value = true
  try {
    const [s, r] = await Promise.all([teacherApi.groupStats(), teacherApi.listRecords()])
    stats.value = s
    records.value = r.records
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.card-title { margin: 0 0 8px; font-size: 15px; }
</style>
