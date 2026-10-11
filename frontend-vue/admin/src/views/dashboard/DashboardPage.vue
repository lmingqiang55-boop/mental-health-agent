<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ greeting }}，{{ user.displayName || user.roleDef?.name }}</h2>
        <p class="page-subtitle">{{ user.roleDef?.desc }} · 数据范围：{{ user.roleDef?.scopeText }}</p>
      </div>
      <el-button :icon="Refresh" circle @click="loadAll" />
    </div>

    <div v-loading="loading">
      <!-- KPI 卡片（可点击直达） -->
      <div class="kpi-grid">
        <div class="kpi-card" @click="$router.push('/assessment/results')">
          <div class="kpi-label">已测评学生</div>
          <div class="kpi-value is-primary">{{ stats?.total_students ?? '—' }}</div>
          <div class="kpi-extra">评估记录 {{ records.length }} 条</div>
        </div>
        <div class="kpi-card" @click="$router.push('/warning')">
          <div class="kpi-label">高风险预警</div>
          <div class="kpi-value is-high">{{ highCount }}</div>
          <div class="kpi-extra">需立即跟进</div>
        </div>
        <div class="kpi-card" @click="$router.push('/warning')">
          <div class="kpi-label">中风险关注</div>
          <div class="kpi-value is-medium">{{ mediumCount }}</div>
          <div class="kpi-extra">建议一周内访谈</div>
        </div>
        <div class="kpi-card" @click="$router.push('/warning')">
          <div class="kpi-label">待认领预警</div>
          <div class="kpi-value">{{ pendingCount }}</div>
          <div class="kpi-extra">跟进状态为「待认领」</div>
        </div>
      </div>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="10">
          <div class="xq-card">
            <h3 class="card-title">风险等级分布</h3>
            <div ref="riskPieEl" class="chart-sm" />
          </div>
        </el-col>
        <el-col :span="14">
          <div class="xq-card">
            <h3 class="card-title">五维群体均值 <span class="card-hint">越高 = 越值得关注</span></h3>
            <div ref="dimBarEl" class="chart-sm" />
          </div>
        </el-col>
      </el-row>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="16">
          <div class="xq-card">
            <div class="card-head">
              <h3 class="card-title">最新预警</h3>
              <el-button text type="primary" @click="$router.push('/warning')">全部预警 →</el-button>
            </div>
            <el-table :data="highRisk.slice(0, 6)" size="large" @row-click="() => $router.push('/warning')">
              <el-table-column prop="student_ref" label="学生标识" width="180" show-overflow-tooltip />
              <el-table-column label="风险等级" width="110">
                <template #default="{ row }"><RiskTag :level="row.risk_level" /></template>
              </el-table-column>
              <el-table-column label="风险类型" min-width="140">
                <template #default="{ row }">
                  <el-tag v-for="t in row.risk_types.slice(0, 3)" :key="t" size="small" effect="plain" style="margin-right: 6px">{{ t }}</el-tag>
                  <span v-if="!row.risk_types.length" class="cell-sub">—</span>
                </template>
              </el-table-column>
              <el-table-column label="跟进状态" width="110">
                <template #default="{ row }"><FollowUpTag :status="row.follow_up_status" /></template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!loading && !highRisk.length" description="暂无中/高风险预警" :image-size="80" />
          </div>
        </el-col>
        <el-col :span="8">
          <div class="xq-card todo-card">
            <div class="card-head">
              <h3 class="card-title">今日待办 <span v-if="notify.total" class="todo-total">{{ notify.total }}</span></h3>
              <el-button text type="primary" :loading="notify.loading" :icon="Refresh" @click="notify.refresh()" />
            </div>
            <div v-if="notify.todos.length" class="todo-list">
              <div
                v-for="t in notify.todos"
                :key="t.id"
                class="todo-item"
                :class="`is-${t.level}`"
                @click="$router.push(t.to)"
              >
                <div class="todo-main">
                  <span class="todo-title">{{ t.title }}</span>
                  <span class="todo-desc">{{ t.desc }}</span>
                </div>
                <span class="todo-count">{{ t.count }}</span>
              </div>
            </div>
            <el-empty v-else-if="!notify.loading" description="今日暂无待办，一切顺利" :image-size="80" />
          </div>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import { teacherApi } from '@/api'
import RiskTag from '@/components/business/RiskTag.vue'
import FollowUpTag from '@/components/business/FollowUpTag.vue'
import { useChart } from '@/composables/useChart'
import { useUserStore } from '@/stores/user'
import { useNotifyStore } from '@/stores/notify'
import { DIMENSION_MAP, RISK_MAP } from '@/utils/format'
import type { GroupStats, HighRiskItem, RecordSummary, RiskLevel } from '@/types'

const user = useUserStore()
const notify = useNotifyStore()
const loading = ref(false)
const stats = ref<GroupStats | null>(null)
const highRisk = ref<HighRiskItem[]>([])
const records = ref<RecordSummary[]>([])

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const highCount = computed(() => highRisk.value.filter((s) => s.risk_level === 'high').length)
const mediumCount = computed(() => highRisk.value.filter((s) => s.risk_level === 'medium').length)
const pendingCount = computed(
  () => highRisk.value.filter((s) => s.follow_up_status === 'pending').length,
)

const riskPieOption = computed<EChartsOption | null>(() => {
  if (!stats.value) return null
  const dist = stats.value.risk_distribution
  const order: RiskLevel[] = ['low', 'medium', 'high']
  const colors = { low: '#52b788', medium: '#f2b84b', high: '#e5655b' }
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['48%', '70%'],
        center: ['50%', '44%'],
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{c} 人' },
        data: order
          .filter((k) => dist[k] !== undefined)
          .map((k) => ({ name: RISK_MAP[k].text, value: dist[k], itemStyle: { color: colors[k] } })),
      },
    ],
  }
})

const dimBarOption = computed<EChartsOption | null>(() => {
  if (!stats.value) return null
  const dims = Object.keys(DIMENSION_MAP) as (keyof typeof DIMENSION_MAP)[]
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 20, top: 20, bottom: 0, containLabel: true },
    xAxis: { type: 'value', max: 100 },
    yAxis: { type: 'category', data: dims.map((d) => DIMENSION_MAP[d]) },
    series: [
      {
        type: 'bar',
        barWidth: 16,
        itemStyle: { borderRadius: [0, 8, 8, 0], color: '#f0833c' },
        data: dims.map((d) => stats.value?.dimension_averages[d] ?? 0),
      },
    ],
  }
})

const riskPieEl = useTemplateRef<HTMLElement>('riskPieEl')
const dimBarEl = useTemplateRef<HTMLElement>('dimBarEl')
useChart(riskPieEl, riskPieOption)
useChart(dimBarEl, dimBarOption)

async function loadAll() {
  loading.value = true
  notify.refresh()
  try {
    const [s, h, r] = await Promise.all([
      teacherApi.groupStats(),
      teacherApi.listHighRisk(),
      teacherApi.listRecords(),
    ])
    stats.value = s
    highRisk.value = h.students
    records.value = r.records
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.card-title { margin: 0 0 8px; font-size: 15px; }
.card-hint { font-size: 12px; font-weight: 400; color: var(--xq-text-secondary); }
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }

.todo-card { height: 100%; }
.todo-total {
  display: inline-block;
  min-width: 20px;
  padding: 0 6px;
  margin-left: 6px;
  font-size: 12px;
  font-weight: 600;
  line-height: 18px;
  text-align: center;
  color: #fff;
  background: var(--xq-risk-high);
  border-radius: 10px;
}
.todo-list { display: flex; flex-direction: column; gap: 10px; }
.todo-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--xq-border);
  border-left: 3px solid var(--xq-text-secondary);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.todo-item:hover { background: var(--xq-primary-lighter); border-color: var(--xq-primary); }
.todo-item.is-high { border-left-color: var(--xq-risk-high); }
.todo-item.is-medium { border-left-color: var(--xq-risk-medium); }
.todo-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.todo-title { font-weight: 600; font-size: 14px; }
.todo-desc { font-size: 12px; color: var(--xq-text-secondary); }
.todo-count {
  flex-shrink: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--xq-primary);
}
</style>
