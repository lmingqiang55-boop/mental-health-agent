<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">测评结果</h2>
        <p class="page-subtitle">数据源：/api/teacher/records；点击行查看报告六区块详情</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Download" :disabled="!filtered.length" @click="exportList">导出结果</el-button>
        <el-button :icon="Refresh" circle @click="load" />
      </div>
    </div>

    <div class="xq-card">
      <div class="filter-bar">
        <el-input v-model="keyword" placeholder="搜索学生标识" clearable style="width: 220px" :prefix-icon="Search" />
        <el-select v-model="filterLevel" placeholder="风险等级" clearable style="width: 140px">
          <el-option v-for="(v, k) in RISK_MAP" :key="k" :label="v.text" :value="k" />
        </el-select>
        <span class="cell-sub">共 {{ filtered.length }} 条</span>
      </div>

      <el-table v-loading="loading" :data="filtered" size="large" @row-click="(r: RecordSummary) => $router.push(`/assessment/results/${r.record_id}`)">
        <el-table-column prop="student_ref" label="学生标识" min-width="200" show-overflow-tooltip />
        <el-table-column prop="concern_index" label="关注指数" width="110" sortable />
        <el-table-column label="风险等级" width="110">
          <template #default="{ row }"><RiskTag :level="row.risk_level" /></template>
        </el-table-column>
        <el-table-column label="整体等级" width="130">
          <template #default="{ row }">
            <el-tag :type="overallMeta(row).type" effect="plain" round>
              {{ overallMeta(row).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="跟进状态" width="110">
          <template #default="{ row }"><FollowUpTag :status="row.follow_up_status" /></template>
        </el-table-column>
        <el-table-column label="测评时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !filtered.length" description="暂无测评结果" :image-size="90" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { teacherApi } from '@/api'
import RiskTag from '@/components/business/RiskTag.vue'
import FollowUpTag from '@/components/business/FollowUpTag.vue'
import { FOLLOW_UP_MAP, OVERALL_LEVEL_MAP, RISK_MAP, fmtTime } from '@/utils/format'
import { exportCsv, stamp, type CsvColumn } from '@/utils/export'
import type { RecordSummary, RiskLevel } from '@/types'

const loading = ref(false)
const list = ref<RecordSummary[]>([])
const keyword = ref('')
const filterLevel = ref<RiskLevel | ''>('')

const filtered = computed(() =>
  list.value.filter(
    (s) =>
      (!keyword.value || s.student_ref.includes(keyword.value)) &&
      (!filterLevel.value || s.risk_level === filterLevel.value),
  ),
)

const overallMeta = (row: RecordSummary) => OVERALL_LEVEL_MAP[row.overall_level]

async function load() {
  loading.value = true
  try {
    list.value = (await teacherApi.listRecords()).records
  } finally {
    loading.value = false
  }
}

onMounted(load)

const EXPORT_COLUMNS: CsvColumn<RecordSummary>[] = [
  { title: '学生标识', value: (r) => r.student_ref },
  { title: '关注指数', value: (r) => r.concern_index },
  { title: '风险等级', value: (r) => RISK_MAP[r.risk_level].text },
  { title: '整体等级', value: (r) => OVERALL_LEVEL_MAP[r.overall_level].text },
  { title: '跟进状态', value: (r) => FOLLOW_UP_MAP[r.follow_up_status].text },
  { title: '测评时间', value: (r) => fmtTime(r.created_at) },
]

function exportList() {
  exportCsv(`测评结果_${stamp()}`, EXPORT_COLUMNS, filtered.value)
  ElMessage.success(`已导出 ${filtered.value.length} 条测评结果`)
}
</script>

<style scoped>
.header-actions { display: flex; align-items: center; gap: 8px; }
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
</style>
