<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">学生心理档案</h2>
        <p class="page-subtitle">按学生聚合评估记录（数据源：/api/teacher/records），并结合花名册补充班级 / 姓名维度</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Upload" @click="openImport">导入花名册</el-button>
        <el-button :icon="Download" :disabled="!rows.length" @click="exportList">导出档案</el-button>
        <el-button :icon="Refresh" circle @click="load" />
      </div>
    </div>

    <div class="xq-card">
      <div class="filter-bar">
        <el-input v-model="keyword" placeholder="搜索姓名 / 学生标识" clearable style="width: 220px" :prefix-icon="Search" />
        <el-select v-model="filterGrade" placeholder="年级" clearable style="width: 120px">
          <el-option v-for="g in gradeOptions" :key="g" :label="g" :value="g" />
        </el-select>
        <el-select v-model="filterClass" placeholder="班级" clearable style="width: 140px">
          <el-option v-for="c in classOptions" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="filterLevel" placeholder="最新风险等级" clearable style="width: 150px">
          <el-option v-for="(v, k) in RISK_MAP" :key="k" :label="v.text" :value="k" />
        </el-select>
        <span class="cell-sub">共 {{ rows.length }} 名学生</span>
      </div>

      <el-table v-loading="loading" :data="rows" size="large" @row-click="(r: StudentRow) => $router.push(`/students/${r.student_ref}`)">
        <el-table-column label="姓名" width="110">
          <template #default="{ row }">
            <span v-if="row.name">{{ row.name }}</span>
            <span v-else class="cell-sub">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="student_ref" label="学生标识" min-width="180" show-overflow-tooltip />
        <el-table-column label="班级" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.className" size="small" effect="plain">{{ row.className }}</el-tag>
            <span v-else class="cell-sub">未分班</span>
          </template>
        </el-table-column>
        <el-table-column label="年级" width="90">
          <template #default="{ row }">{{ row.grade ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="最新关注指数" width="120" sortable :sort-method="(a: StudentRow, b: StudentRow) => a.concern_index - b.concern_index">
          <template #default="{ row }"><b :style="{ color: concernColor(row.concern_index) }">{{ row.concern_index }}</b></template>
        </el-table-column>
        <el-table-column label="最新风险" width="110">
          <template #default="{ row }"><RiskTag :level="row.risk_level" /></template>
        </el-table-column>
        <el-table-column label="跟进状态" width="110">
          <template #default="{ row }"><FollowUpTag :status="row.follow_up_status" /></template>
        </el-table-column>
        <el-table-column prop="assess_count" label="评估次数" width="100" />
        <el-table-column label="最近测评时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.latest_at) }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="暂无学生档案" :image-size="90" />
    </div>

    <!-- 花名册批量导入 -->
    <el-dialog v-model="importVisible" title="导入花名册" width="560px">
      <p class="import-tip">
        每行一条学生记录，格式为 <b>姓名,学号,班级</b>（英文逗号、中文逗号、制表符或空格分隔均可）。
        可直接从 Excel 复制粘贴。学号重复的学生将被跳过。
      </p>
      <el-input
        v-model="importText"
        type="textarea"
        :rows="9"
        placeholder="张浩然,stu-0001,初二1班&#10;黄芷若,stu-0010,初二3班&#10;陈雨桐,stu-0005,初三1班"
      />
      <div class="import-preview">
        已解析 <b>{{ previewRows.length }}</b> 条有效记录
        <span v-if="importText.trim() && !previewRows.length" class="cell-sub">（请检查格式是否为「姓名,学号,班级」）</span>
      </div>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" :disabled="!previewRows.length" @click="confirmImport">
          确认导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Download, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { studentApi, teacherApi, type DemoStudent } from '@/api'
import RiskTag from '@/components/business/RiskTag.vue'
import FollowUpTag from '@/components/business/FollowUpTag.vue'
import { FOLLOW_UP_MAP, RISK_MAP, fmtTime } from '@/utils/format'
import { exportCsv, stamp, type CsvColumn } from '@/utils/export'
import type { FollowUpStatus, RecordSummary, RiskLevel } from '@/types'

interface StudentRow {
  student_ref: string
  name: string | null
  className: string | null
  grade: string | null
  concern_index: number
  risk_level: RiskLevel
  follow_up_status: FollowUpStatus
  assess_count: number
  latest_at: string
}

const loading = ref(false)
const summaries = ref<RecordSummary[]>([])
const roster = ref<DemoStudent[]>([])
const keyword = ref('')
const filterGrade = ref('')
const filterClass = ref('')
const filterLevel = ref<RiskLevel | ''>('')

const refMap = computed(() => new Map(roster.value.map((s) => [s.ref, s])))
const classOptions = computed(() => [...new Set(roster.value.map((s) => s.className))].sort())
const gradeOptions = computed(() =>
  [...new Set(roster.value.map((s) => s.grade))].sort((a, b) => a.localeCompare(b, 'zh')),
)

const rows = computed<StudentRow[]>(() => {
  const byStudent = new Map<string, RecordSummary[]>()
  for (const r of summaries.value) {
    const arr = byStudent.get(r.student_ref) ?? []
    arr.push(r)
    byStudent.set(r.student_ref, arr)
  }
  return [...byStudent.values()]
    .map((list) => {
      const sorted = [...list].sort((a, b) => a.created_at.localeCompare(b.created_at))
      const latest = sorted[sorted.length - 1]
      const info = refMap.value.get(latest.student_ref) ?? null
      return {
        student_ref: latest.student_ref,
        name: info?.name ?? null,
        className: info?.className ?? null,
        grade: info?.grade ?? null,
        concern_index: latest.concern_index,
        risk_level: latest.risk_level,
        follow_up_status: latest.follow_up_status,
        assess_count: sorted.length,
        latest_at: latest.created_at,
      }
    })
    .filter(
      (s) =>
        (!keyword.value || s.student_ref.includes(keyword.value) || (s.name ?? '').includes(keyword.value)) &&
        (!filterGrade.value || s.grade === filterGrade.value) &&
        (!filterClass.value || s.className === filterClass.value) &&
        (!filterLevel.value || s.risk_level === filterLevel.value),
    )
    .sort((a, b) => b.concern_index - a.concern_index)
})

// 年级变化时清掉不在该年级的班级选择
watch(filterGrade, (g) => {
  if (g && filterClass.value) {
    const stillValid = roster.value.some((s) => s.className === filterClass.value && s.grade === g)
    if (!stillValid) filterClass.value = ''
  }
})

function concernColor(v: number) {
  return v >= 70 ? '#e5655b' : v >= 45 ? '#f2b84b' : '#52b788'
}

async function load() {
  loading.value = true
  try {
    const [recordRes, rosterRes] = await Promise.all([
      teacherApi.listRecords(),
      studentApi.list().catch(() => [] as DemoStudent[]),
    ])
    summaries.value = recordRes.records
    roster.value = rosterRes
  } finally {
    loading.value = false
  }
}

// ---- 导出 ----
const EXPORT_COLUMNS: CsvColumn<StudentRow>[] = [
  { title: '姓名', value: (r) => r.name ?? '' },
  { title: '学生标识', value: (r) => r.student_ref },
  { title: '班级', value: (r) => r.className ?? '' },
  { title: '年级', value: (r) => r.grade ?? '' },
  { title: '最新关注指数', value: (r) => r.concern_index },
  { title: '最新风险等级', value: (r) => RISK_MAP[r.risk_level].text },
  { title: '跟进状态', value: (r) => FOLLOW_UP_MAP[r.follow_up_status].text },
  { title: '评估次数', value: (r) => r.assess_count },
  { title: '最近测评时间', value: (r) => fmtTime(r.latest_at) },
]

function exportList() {
  exportCsv(`学生心理档案_${stamp()}`, EXPORT_COLUMNS, rows.value)
  ElMessage.success(`已导出 ${rows.value.length} 名学生档案`)
}

// ---- 花名册导入 ----
const importVisible = ref(false)
const importText = ref('')
const importing = ref(false)

const previewRows = computed(() =>
  importText.value
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [name = '', ref = '', className = ''] = line.split(/[\s,，\t]+/).filter(Boolean)
      return { name, ref, className }
    })
    .filter((r) => r.name && r.ref && r.className),
)

function openImport() {
  importText.value = ''
  importVisible.value = true
}

async function confirmImport() {
  importing.value = true
  try {
    const res = await studentApi.import(previewRows.value)
    ElMessage.success(`成功导入 ${res.added} 人${res.skipped ? `，跳过 ${res.skipped} 条（重复或格式不符）` : ''}`)
    importVisible.value = false
    await load()
  } finally {
    importing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.header-actions { display: flex; align-items: center; gap: 8px; }
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }
.import-tip { margin: 0 0 10px; color: var(--xq-text-secondary); font-size: 13px; line-height: 1.7; }
.import-preview { margin-top: 10px; font-size: 13px; }
</style>
