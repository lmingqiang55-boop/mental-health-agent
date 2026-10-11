<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">资源中心</h2>
        <p class="page-subtitle">科普文章 / 课程资源 / 通知公告的内容管理</p>
      </div>
      <el-button :icon="Refresh" circle @click="reload" />
    </div>

    <div class="xq-card">
      <el-tabs v-model="tab" @tab-change="onTabChange">
        <el-tab-pane v-for="k in KINDS" :key="k.kind" :label="k.label" :name="k.kind" />
      </el-tabs>

      <div class="filter-bar">
        <el-input v-model="keyword" :placeholder="`搜索${currentKindLabel}标题`" clearable style="width: 220px" :prefix-icon="Search" />
        <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 130px">
          <el-option v-for="(v, k) in RESOURCE_STATUS_MAP" :key="k" :label="v.text" :value="k" />
        </el-select>
        <span class="cell-sub">共 {{ filtered.length }} 条</span>
        <div class="flex-spacer" />
        <el-button type="primary" :icon="Plus" @click="openCreate">新建{{ currentKindLabel }}</el-button>
      </div>

      <el-table v-loading="loading" :data="filtered" size="large">
        <el-table-column prop="title" :label="`${currentKindLabel}标题`" min-width="260" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="130" />
        <el-table-column label="标签" width="180">
          <template #default="{ row }">
            <el-tag v-for="t in row.tags" :key="t" size="small" effect="plain" style="margin-right: 4px">{{ t }}</el-tag>
            <span v-if="!row.tags.length" class="cell-sub">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="author" label="作者" width="110" />
        <el-table-column prop="views" label="浏览量" width="90" sortable />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status).type" effect="plain" round>{{ statusTag(row.status).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.updatedAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'published'" link type="success" @click="setStatus(row, 'published')">发布</el-button>
            <el-button v-else link type="warning" @click="setStatus(row, 'offline')">下线</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !filtered.length" :description="`暂无${currentKindLabel}`" :image-size="90" />
    </div>

    <el-dialog v-model="dialog" :title="`新建${currentKindLabel}`" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="标题"><el-input v-model="form.title" maxlength="50" show-word-limit /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" allow-create filterable default-first-option style="width: 100%">
            <el-option v-for="c in currentCategories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="form.summary" type="textarea" :rows="3" maxlength="120" show-word-limit />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="form.tags" multiple allow-create filterable default-first-option placeholder="回车添加标签" style="width: 100%" />
        </el-form-item>
        <el-form-item label="作者"><el-input v-model="form.author" style="width: 200px" /></el-form-item>
        <el-form-item label="立即发布"><el-switch v-model="form.publishNow" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { resourceApi } from '@/api'
import { RESOURCE_STATUS_MAP, fmtTime } from '@/utils/format'
import type { ResourceItem, ResourceKind, ResourceStatus } from '@/types/admin'

const KINDS: { kind: ResourceKind; label: string }[] = [
  { kind: 'article', label: '科普文章' },
  { kind: 'course', label: '课程资源' },
  { kind: 'notice', label: '通知公告' },
]
const CATEGORIES: Record<ResourceKind, string[]> = {
  article: ['考试心理', '家庭教育', '健康生活', '情绪管理'],
  course: ['放松训练', '情绪管理', '人际交往', '时间管理'],
  notice: ['工作通知', '服务公告', '活动通知'],
}

const tab = ref<ResourceKind>('article')
const loading = ref(false)
const list = ref<ResourceItem[]>([])
const keyword = ref('')
const filterStatus = ref<ResourceStatus | ''>('')
const dialog = ref(false)

const form = reactive({ title: '', category: '', summary: '', tags: [] as string[], author: '心理中心', publishNow: true })

const currentKindLabel = computed(() => KINDS.find((k) => k.kind === tab.value)?.label ?? '')
const currentCategories = computed(() => CATEGORIES[tab.value])

const statusTag = (s: ResourceStatus) => RESOURCE_STATUS_MAP[s]

const filtered = computed(() =>
  list.value.filter(
    (r) =>
      (!keyword.value || r.title.includes(keyword.value)) &&
      (!filterStatus.value || r.status === filterStatus.value),
  ),
)

async function load() {
  loading.value = true
  try {
    list.value = await resourceApi.list(tab.value)
  } finally {
    loading.value = false
  }
}

function onTabChange() {
  keyword.value = ''
  filterStatus.value = ''
  load()
}

function openCreate() {
  Object.assign(form, { title: '', category: CATEGORIES[tab.value][0], summary: '', tags: [], author: '心理中心', publishNow: true })
  dialog.value = true
}

async function create() {
  if (!form.title.trim()) {
    ElMessage.warning('请填写标题')
    return
  }
  await resourceApi.create({
    kind: tab.value,
    title: form.title,
    category: form.category,
    summary: form.summary,
    tags: form.tags,
    status: form.publishNow ? 'published' : 'draft',
    author: form.author,
  })
  dialog.value = false
  ElMessage.success('已保存')
  load()
}

async function setStatus(row: ResourceItem, status: ResourceStatus) {
  await resourceApi.setStatus(row.id, status)
  ElMessage.success(status === 'published' ? '已发布' : '已下线')
  load()
}

async function remove(row: ResourceItem) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.title}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  await resourceApi.remove(row.id)
  ElMessage.success('已删除')
  load()
}

async function reload() {
  await load()
}

onMounted(load)
</script>

<style scoped>
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
.flex-spacer { flex: 1; }
</style>
