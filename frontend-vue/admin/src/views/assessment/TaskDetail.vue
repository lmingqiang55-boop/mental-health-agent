<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ task?.title ?? '任务详情' }}</h2>
        <p class="page-subtitle">任务进度追踪与参与明细</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Back" @click="$router.push('/assessment/tasks')">返回列表</el-button>
        <el-button v-if="task && (task.status === 'draft' || task.status === 'published')" type="primary" @click="setStatus('running')">发布任务</el-button>
        <el-button v-if="task && task.status === 'running'" type="warning" @click="setStatus('finished')">结束任务</el-button>
      </div>
    </div>

    <div v-loading="loading">
      <template v-if="task">
        <div class="xq-card">
          <el-descriptions :column="3" border>
            <el-descriptions-item label="测评类型">{{ SCALE_MAP[task.scale] }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="TASK_STATUS_MAP[task.status].type" effect="plain" round>{{ TASK_STATUS_MAP[task.status].text }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="创建人">{{ task.creator }}</el-descriptions-item>
            <el-descriptions-item label="目标范围">{{ task.targetScope }}</el-descriptions-item>
            <el-descriptions-item label="开始时间">{{ fmtTime(task.startAt) }}</el-descriptions-item>
            <el-descriptions-item label="截止时间">{{ fmtTime(task.deadline) }}</el-descriptions-item>
            <el-descriptions-item label="参与策略">
              <el-tag v-if="task.anonymous" size="small" type="info" effect="plain">匿名</el-tag>
              <el-tag v-if="task.consentRequired" size="small" type="warning" effect="plain" style="margin-left: 6px">需知情同意</el-tag>
              <span v-if="!task.anonymous && !task.consentRequired" class="cell-sub">实名 · 无需同意书</span>
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ fmtTime(task.createdAt) }}</el-descriptions-item>
            <el-descriptions-item label="备注" :span="3">{{ task.remark || '—' }}</el-descriptions-item>
          </el-descriptions>
        </div>

        <div class="xq-card">
          <div class="progress-head">
            <span class="progress-title">提交进度</span>
            <span class="cell-sub">{{ task.submitted }} / {{ task.total }} 人（{{ pct }}%）</span>
          </div>
          <el-progress :percentage="pct" :stroke-width="14" :text-inside="true" />
          <div class="stat-row">
            <div class="stat-item"><div class="stat-label">已提交</div><div class="stat-value is-ok">{{ task.submitted }}</div></div>
            <div class="stat-item"><div class="stat-label">未提交</div><div class="stat-value">{{ task.total - task.submitted }}</div></div>
            <div class="stat-item"><div class="stat-label">中高风险</div><div class="stat-value is-high">{{ riskCount }}</div></div>
          </div>
        </div>

        <div class="xq-card">
          <div class="table-head">
            <span class="progress-title">参与明细</span>
            <div class="table-head-actions">
              <el-select v-model="filterStatus" placeholder="提交状态" clearable size="small" style="width: 130px">
                <el-option v-for="(v, k) in PARTICIPANT_MAP" :key="k" :label="v.text" :value="k" />
              </el-select>
              <el-button size="small" :icon="Download" :disabled="!filteredParticipants.length" @click="exportParticipants">导出明细</el-button>
            </div>
          </div>
          <el-table :data="filteredParticipants" size="large">
            <el-table-column prop="name" label="姓名" width="120" />
            <el-table-column prop="studentRef" label="学生标识" min-width="150" />
            <el-table-column prop="className" label="班级" width="120" />
            <el-table-column label="提交状态" width="110">
              <template #default="{ row }">
                <el-tag :type="participantTag(row.status).type" effect="plain" round>{{ participantTag(row.status).text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="170">
              <template #default="{ row }">{{ fmtTime(row.submittedAt) }}</template>
            </el-table-column>
            <el-table-column label="风险等级" width="110">
              <template #default="{ row }">
                <RiskTag v-if="row.riskLevel" :level="row.riskLevel" />
                <span v-else class="cell-sub">—</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="任务不存在或已被删除" :image-size="90" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back, Download } from '@element-plus/icons-vue'
import { taskApi } from '@/api'
import RiskTag from '@/components/business/RiskTag.vue'
import { PARTICIPANT_MAP, RISK_MAP, SCALE_MAP, TASK_STATUS_MAP, fmtTime } from '@/utils/format'
import { exportCsv, stamp, type CsvColumn } from '@/utils/export'
import type { AssessmentTask, TaskParticipant, TaskStatus } from '@/types/admin'

const route = useRoute()
const id = route.params.id as string

const loading = ref(false)
const task = ref<AssessmentTask | null>(null)
const participants = ref<TaskParticipant[]>([])
const filterStatus = ref<TaskParticipant['status'] | ''>('')

const filteredParticipants = computed(() =>
  participants.value.filter((p) => !filterStatus.value || p.status === filterStatus.value),
)

const pct = computed(() => (task.value?.total ? Math.round((task.value.submitted / task.value.total) * 100) : 0))

const riskCount = computed(
  () => participants.value.filter((p) => p.riskLevel === 'high' || p.riskLevel === 'medium').length,
)

function participantTag(status: TaskParticipant['status']) {
  return PARTICIPANT_MAP[status]
}

async function load() {
  loading.value = true
  try {
    task.value = await taskApi.get(id)
    participants.value = await taskApi.participants(id)
  } catch {
    task.value = null
  } finally {
    loading.value = false
  }
}

async function setStatus(status: TaskStatus) {
  const updated = await taskApi.setStatus(id, status)
  task.value = updated
  ElMessage.success(status === 'running' ? '任务已发布' : '任务已结束')
}

onMounted(load)

const EXPORT_COLUMNS: CsvColumn<TaskParticipant>[] = [
  { title: '姓名', value: (r) => r.name },
  { title: '学生标识', value: (r) => r.studentRef },
  { title: '班级', value: (r) => r.className },
  { title: '提交状态', value: (r) => PARTICIPANT_MAP[r.status].text },
  { title: '提交时间', value: (r) => (r.submittedAt ? fmtTime(r.submittedAt) : '') },
  { title: '风险等级', value: (r) => (r.riskLevel ? RISK_MAP[r.riskLevel].text : '') },
]

function exportParticipants() {
  const name = task.value?.title ?? '任务'
  exportCsv(`${name}_参与明细_${stamp()}`, EXPORT_COLUMNS, filteredParticipants.value)
  ElMessage.success(`已导出 ${filteredParticipants.value.length} 条参与明细`)
}
</script>

<style scoped>
.header-actions { display: flex; gap: 10px; }
.progress-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.table-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.table-head-actions { display: flex; align-items: center; gap: 10px; }
.progress-title { font-weight: 600; }
.stat-row { display: flex; gap: 40px; margin-top: 16px; }
.stat-label { color: var(--xq-text-secondary); font-size: 13px; }
.stat-value { font-size: 22px; font-weight: 700; margin-top: 4px; }
.stat-value.is-ok { color: var(--xq-risk-low); }
.stat-value.is-high { color: var(--xq-risk-high); }
</style>
