<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">测评任务</h2>
        <p class="page-subtitle">创建 / 发布 / 追踪测评任务（对话式、PHQ-9、GAD-7 等量表）</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" circle @click="load" />
        <el-button type="primary" :icon="Plus" @click="$router.push('/assessment/tasks/create')">创建测评任务</el-button>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card" v-for="k in kpis" :key="k.label">
        <div class="kpi-label">{{ k.label }}</div>
        <div class="kpi-value" :class="k.cls">{{ k.value }}</div>
        <div class="kpi-extra">{{ k.extra }}</div>
      </div>
    </div>

    <div class="xq-card">
      <div class="filter-bar">
        <el-input v-model="keyword" placeholder="搜索任务名称" clearable style="width: 220px" :prefix-icon="Search" />
        <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 130px">
          <el-option v-for="(v, k) in TASK_STATUS_MAP" :key="k" :label="v.text" :value="k" />
        </el-select>
        <el-select v-model="filterScale" placeholder="测评类型" clearable style="width: 170px">
          <el-option v-for="(v, k) in SCALE_MAP" :key="k" :label="v" :value="k" />
        </el-select>
        <span class="cell-sub">共 {{ filtered.length }} 个任务</span>
      </div>

      <el-table v-loading="loading" :data="paged" size="large" @row-click="(r: AssessmentTask) => $router.push(`/assessment/tasks/${r.id}`)">
        <el-table-column prop="title" label="任务名称" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.title }}</div>
            <div class="cell-sub">{{ SCALE_MAP[row.scale as ScaleType] }}<span v-if="row.anonymous"> · 匿名</span></div>
          </template>
        </el-table-column>
        <el-table-column prop="targetScope" label="目标范围" width="150" show-overflow-tooltip />
        <el-table-column label="进度" width="200">
          <template #default="{ row }">
            <el-progress :percentage="pct(row)" :stroke-width="8" :format="() => `${row.submitted}/${row.total}`" />
          </template>
        </el-table-column>
        <el-table-column label="时间" width="200">
          <template #default="{ row }">
            <div>{{ row.deadline ? fmtTime(row.deadline, 'YYYY-MM-DD') : '未设置' }}</div>
            <div class="cell-sub">创建 {{ fmtTime(row.createdAt, 'MM-DD HH:mm') }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="TASK_STATUS_MAP[row.status as TaskStatus].type" effect="plain" round>
              {{ TASK_STATUS_MAP[row.status as TaskStatus].text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="$router.push(`/assessment/tasks/${row.id}`)">详情</el-button>
            <el-button v-if="row.status === 'draft' || row.status === 'published'" link type="primary" @click.stop="publish(row)">发布</el-button>
            <el-button v-if="row.status === 'running'" link type="warning" @click.stop="finish(row)">结束</el-button>
            <el-button link type="danger" @click.stop="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="filtered.length"
          layout="prev, pager, next, total"
          background
        />
      </div>
      <el-empty v-if="!loading && !filtered.length" description="暂无测评任务" :image-size="90" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { taskApi } from '@/api'
import { SCALE_MAP, TASK_STATUS_MAP, fmtTime } from '@/utils/format'
import type { AssessmentTask, ScaleType, TaskStatus } from '@/types/admin'

const loading = ref(false)
const list = ref<AssessmentTask[]>([])
const keyword = ref('')
const filterStatus = ref<TaskStatus | ''>('')
const filterScale = ref<ScaleType | ''>('')
const page = ref(1)
const pageSize = 8

const filtered = computed(() =>
  list.value.filter(
    (t) =>
      (!keyword.value || t.title.includes(keyword.value)) &&
      (!filterStatus.value || t.status === filterStatus.value) &&
      (!filterScale.value || t.scale === filterScale.value),
  ),
)

const paged = computed(() => {
  const start = (page.value - 1) * pageSize
  return filtered.value.slice(start, start + pageSize)
})

const kpis = computed(() => {
  const running = list.value.filter((t) => t.status === 'running').length
  const totalTarget = list.value.reduce((s, t) => s + t.total, 0)
  const totalSubmitted = list.value.reduce((s, t) => s + t.submitted, 0)
  const rate = totalTarget ? Math.round((totalSubmitted / totalTarget) * 100) : 0
  return [
    { label: '任务总数', value: list.value.length, extra: '含草稿与已结束', cls: 'is-primary' },
    { label: '进行中', value: running, extra: '正在收集测评数据', cls: '' },
    { label: '应参与人次', value: totalTarget, extra: '所有任务累计', cls: '' },
    { label: '提交完成率', value: `${rate}%`, extra: `${totalSubmitted} / ${totalTarget} 人次`, cls: rate >= 80 ? '' : 'is-medium' },
  ]
})

const pct = (row: AssessmentTask) => (row.total ? Math.round((row.submitted / row.total) * 100) : 0)

async function load() {
  loading.value = true
  try {
    list.value = (await taskApi.list()).items
  } finally {
    loading.value = false
  }
}

async function publish(row: AssessmentTask) {
  await taskApi.setStatus(row.id, 'running')
  ElMessage.success(`已发布「${row.title}」`)
  load()
}

async function finish(row: AssessmentTask) {
  await taskApi.setStatus(row.id, 'finished')
  ElMessage.success(`已结束「${row.title}」`)
  load()
}

async function remove(row: AssessmentTask) {
  try {
    await ElMessageBox.confirm(`确认删除任务「${row.title}」？该操作不可撤销。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await taskApi.remove(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.header-actions { display: flex; gap: 10px; }
.kpi-grid { margin-bottom: 16px; }
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
