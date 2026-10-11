<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">预警管理</h2>
        <p class="page-subtitle">来自后端 /api/teacher/high-risk 的中/高风险名单；点击行查看详情并跟进处置</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Download" :disabled="!filtered.length" @click="exportList">导出名单</el-button>
        <el-button :icon="Refresh" circle @click="load" />
      </div>
    </div>

    <div class="xq-card">
      <div class="filter-bar">
        <el-select v-model="filterLevel" placeholder="风险等级" clearable style="width: 140px">
          <el-option label="高风险" value="high" />
          <el-option label="中风险" value="medium" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="跟进状态" clearable style="width: 140px">
          <el-option v-for="(v, k) in FOLLOW_UP_MAP" :key="k" :label="v.text" :value="k" />
        </el-select>
        <el-input v-model="keyword" placeholder="搜索学生标识" clearable style="width: 220px" :prefix-icon="Search" />
        <span class="cell-sub">共 {{ filtered.length }} 条</span>
      </div>

      <el-table v-loading="loading" :data="filtered" size="large" @row-click="openDetail">
        <el-table-column prop="student_ref" label="学生标识" width="200" show-overflow-tooltip />
        <el-table-column label="风险等级" width="100">
          <template #default="{ row }"><RiskTag :level="row.risk_level" /></template>
        </el-table-column>
        <el-table-column label="风险类型" min-width="150">
          <template #default="{ row }">
            <el-tag v-for="t in row.risk_types.slice(0, 3)" :key="t" size="small" effect="plain" style="margin-right: 6px">{{ t }}</el-tag>
            <span v-if="!row.risk_types.length" class="cell-sub">—</span>
          </template>
        </el-table-column>
        <el-table-column label="风险原因" min-width="220">
          <template #default="{ row }">
            <span class="cell-sub">{{ row.risk_reasons[0] ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="跟进状态" width="110">
          <template #default="{ row }"><FollowUpTag :status="row.follow_up_status" /></template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !filtered.length" description="暂无匹配预警" :image-size="90" />
    </div>

    <!-- 预警详情 + 处置抽屉 -->
    <el-drawer v-model="drawer" size="620px" :title="`预警详情 · ${current?.student_ref ?? ''}`">
      <div v-loading="detailLoading">
        <template v-if="record">
          <div class="detail-head">
            <RiskTag :level="record.result.risk.risk_level" />
            <FollowUpTag :status="record.follow_up_status" />
            <span class="cell-sub">测评时间 {{ fmtTime(record.created_at) }}</span>
          </div>

          <el-descriptions :column="2" border size="small" style="margin-top: 14px">
            <el-descriptions-item label="学生标识">{{ record.student_ref }}</el-descriptions-item>
            <el-descriptions-item label="关注指数">{{ record.result.concern_index }}</el-descriptions-item>
            <el-descriptions-item label="年级">{{ record.result.grade ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="年龄">{{ record.result.age ?? '—' }}</el-descriptions-item>
          </el-descriptions>

          <h4 class="sec-title">风险原因</h4>
          <ul class="evidence-list"><li v-for="(r, i) in record.result.risk.risk_reasons" :key="i">{{ r }}</li></ul>
          <template v-if="record.result.risk.key_evidence.length">
            <h4 class="sec-title">关键证据</h4>
            <ul class="evidence-list"><li v-for="(e, i) in record.result.risk.key_evidence" :key="i">{{ e }}</li></ul>
          </template>

          <h4 class="sec-title">跟进备注（{{ record.counselor_notes.length }}）</h4>
          <el-timeline v-if="record.counselor_notes.length" style="padding-left: 4px">
            <el-timeline-item
              v-for="n in record.counselor_notes"
              :key="n.note_id"
              :timestamp="`${fmtTime(n.created_at)} · ${n.counselor_ref}`"
            >
              {{ n.content }}
            </el-timeline-item>
          </el-timeline>
          <p v-else class="cell-sub">暂无跟进记录</p>

          <div class="note-box">
            <el-input v-model="note" type="textarea" :rows="3" maxlength="500" show-word-limit
              placeholder="填写跟进 / 访谈 / 处置记录（提交后状态自动变为「跟进中」）" />
            <el-button type="primary" :loading="submitting" :disabled="!note.trim()" style="margin-top: 10px" @click="submitNote">
              提交跟进备注
            </el-button>
          </div>

          <el-button text type="primary" @click="$router.push(`/assessment/results/${record.record_id}`)">
            查看完整评估报告 →
          </el-button>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { teacherApi } from '@/api'
import RiskTag from '@/components/business/RiskTag.vue'
import FollowUpTag from '@/components/business/FollowUpTag.vue'
import { useUserStore } from '@/stores/user'
import { FOLLOW_UP_MAP, RISK_MAP, fmtTime } from '@/utils/format'
import { exportCsv, stamp, type CsvColumn } from '@/utils/export'
import type { EvaluationRecord, FollowUpStatus, HighRiskItem, RiskLevel } from '@/types'

const user = useUserStore()
const loading = ref(false)
const list = ref<HighRiskItem[]>([])
const filterLevel = ref<RiskLevel | ''>('')
const filterStatus = ref<FollowUpStatus | ''>('')
const keyword = ref('')

const drawer = ref(false)
const detailLoading = ref(false)
const current = ref<HighRiskItem | null>(null)
const record = ref<EvaluationRecord | null>(null)
const note = ref('')
const submitting = ref(false)

const filtered = computed(() =>
  list.value.filter(
    (s) =>
      (!filterLevel.value || s.risk_level === filterLevel.value) &&
      (!filterStatus.value || s.follow_up_status === filterStatus.value) &&
      (!keyword.value || s.student_ref.includes(keyword.value)),
  ),
)

async function load() {
  loading.value = true
  try {
    list.value = (await teacherApi.listHighRisk()).students
  } finally {
    loading.value = false
  }
}

async function openDetail(row: HighRiskItem) {
  current.value = row
  drawer.value = true
  detailLoading.value = true
  record.value = null
  try {
    record.value = await teacherApi.getRecord(row.record_id)
  } finally {
    detailLoading.value = false
  }
}

async function submitNote() {
  if (!record.value || !note.value.trim()) return
  submitting.value = true
  try {
    const res = await teacherApi.addNote(record.value.record_id, user.counselorRef, note.value.trim())
    record.value = res.record
    note.value = ''
    ElMessage.success('跟进备注已保存')
    load() // 状态可能已从「待认领」变为「跟进中」
  } finally {
    submitting.value = false
  }
}

onMounted(load)

const EXPORT_COLUMNS: CsvColumn<HighRiskItem>[] = [
  { title: '学生标识', value: (r) => r.student_ref },
  { title: '风险等级', value: (r) => RISK_MAP[r.risk_level].text },
  { title: '风险类型', value: (r) => r.risk_types.join('、') },
  { title: '风险原因', value: (r) => r.risk_reasons.join('；') },
  { title: '关键证据', value: (r) => r.key_evidence.join('；') },
  { title: '跟进状态', value: (r) => FOLLOW_UP_MAP[r.follow_up_status].text },
]

function exportList() {
  exportCsv(`预警名单_${stamp()}`, EXPORT_COLUMNS, filtered.value)
  ElMessage.success(`已导出 ${filtered.value.length} 条预警记录`)
}
</script>

<style scoped>
.header-actions { display: flex; align-items: center; gap: 8px; }
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
.detail-head { display: flex; align-items: center; gap: 10px; }
.sec-title { margin: 18px 0 8px; font-size: 14px; }
.evidence-list { margin: 0; padding-left: 18px; line-height: 1.9; font-size: 13px; }
.note-box { margin-top: 16px; padding: 14px; background: var(--xq-primary-lighter); border-radius: 10px; }
</style>
