<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">干预与咨询</h2>
        <p class="page-subtitle">咨询预约 / 访谈记录 / iCBT 单元管理 / 资源推送</p>
      </div>
      <el-button :icon="Refresh" circle @click="reload" />
    </div>

    <div class="xq-card">
      <el-tabs v-model="tab">
        <!-- ---------------- 咨询预约 ---------------- -->
        <el-tab-pane label="咨询预约" name="consult">
          <div class="filter-bar">
            <el-select v-model="apFilter" placeholder="状态" clearable style="width: 130px">
              <el-option v-for="(v, k) in APPOINTMENT_MAP" :key="k" :label="v.text" :value="k" />
            </el-select>
            <span class="cell-sub">共 {{ filteredAppointments.length }} 条</span>
            <div class="flex-spacer" />
            <el-button type="primary" :icon="Plus" @click="apDialog = true">新建预约</el-button>
          </div>
          <el-table v-loading="loading" :data="filteredAppointments" size="large">
            <el-table-column label="学生" width="130">
              <template #default="{ row }">
                <div>{{ row.studentName }}</div>
                <div class="cell-sub">{{ row.className }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="slot" label="预约时间" width="160" />
            <el-table-column prop="counselor" label="咨询师" width="100" />
            <el-table-column label="时长/地点" width="150">
              <template #default="{ row }">{{ row.duration }} 分钟 · {{ row.room }}</template>
            </el-table-column>
            <el-table-column prop="topic" label="主题" min-width="140" show-overflow-tooltip />
            <el-table-column label="来源" width="110">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ sourceText(row.source) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="apptTag(row.status).type" effect="light" round>{{ apptTag(row.status).text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="190" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.status === 'pending'" link type="primary" @click="setApStatus(row.id, 'confirmed')">确认</el-button>
                <el-button v-if="row.status === 'confirmed'" link type="success" @click="setApStatus(row.id, 'done')">完成</el-button>
                <el-button v-if="row.status === 'pending' || row.status === 'confirmed'" link type="info" @click="setApStatus(row.id, 'cancelled')">取消</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ---------------- 访谈记录 ---------------- -->
        <el-tab-pane label="访谈记录" name="records">
          <div class="filter-bar">
            <el-input v-model="ivKeyword" placeholder="搜索学生姓名" clearable style="width: 200px" :prefix-icon="Search" />
            <span class="cell-sub">共 {{ filteredInterviews.length }} 条</span>
            <div class="flex-spacer" />
            <el-button type="primary" :icon="Plus" @click="ivDialog = true">新建访谈记录</el-button>
          </div>
          <el-table v-loading="loading" :data="filteredInterviews" size="large">
            <el-table-column label="学生" width="130">
              <template #default="{ row }">
                <div>{{ row.studentName }}</div>
                <div class="cell-sub">{{ row.className }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="interviewedAt" label="访谈时间" width="170" />
            <el-table-column label="类型" width="120">
              <template #default="{ row }"><el-tag size="small" effect="plain">{{ row.type }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="counselor" label="咨询师" width="100" />
            <el-table-column prop="summary" label="访谈摘要" min-width="240" show-overflow-tooltip />
            <el-table-column prop="nextPlan" label="下一步计划" min-width="200" show-overflow-tooltip />
            <el-table-column label="密级" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.confidential ? 'danger' : 'info'" effect="plain">
                  {{ row.confidential ? '保密' : '一般' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ---------------- iCBT 单元 ---------------- -->
        <el-tab-pane label="iCBT 单元" name="icbt">
          <div class="filter-bar">
            <span class="cell-sub">共 {{ units.length }} 个单元</span>
            <div class="flex-spacer" />
          </div>
          <el-table v-loading="loading" :data="units" size="large">
            <el-table-column prop="order" label="序号" width="70" />
            <el-table-column prop="title" label="单元名称" min-width="220" show-overflow-tooltip />
            <el-table-column prop="module" label="所属模块" width="130" />
            <el-table-column label="内容" width="120">
              <template #default="{ row }">{{ row.steps }} 步 · 约 {{ row.estMinutes }} 分钟</template>
            </el-table-column>
            <el-table-column prop="audience" label="适用人群" width="130" />
            <el-table-column label="完成度" width="170">
              <template #default="{ row }">
                <el-progress :percentage="row.assigned ? Math.round((row.completed / row.assigned) * 100) : 0" :stroke-width="8" :format="() => `${row.completed}/${row.assigned}`" />
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="icbtTag(row.status).type" effect="plain" round>{{ icbtTag(row.status).text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openUnit(row)">编辑</el-button>
                <el-button v-if="row.status !== 'published'" link type="success" @click="toggleUnit(row, 'published')">发布</el-button>
                <el-button v-else link type="warning" @click="toggleUnit(row, 'offline')">下线</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ---------------- 资源推送 ---------------- -->
        <el-tab-pane label="资源推送" name="push">
          <div class="filter-bar">
            <span class="cell-sub">共 {{ pushes.length }} 条推送记录</span>
            <div class="flex-spacer" />
            <el-button type="primary" :icon="Plus" @click="pushDialog = true">新建推送</el-button>
          </div>
          <el-table v-loading="loading" :data="pushes" size="large">
            <el-table-column prop="contentTitle" label="推送内容" min-width="240" show-overflow-tooltip />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">{{ kindText(row.contentType) }}</template>
            </el-table-column>
            <el-table-column prop="target" label="推送范围" width="130" />
            <el-table-column prop="targets" label="人数" width="90" />
            <el-table-column prop="channel" label="渠道" width="100" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="pushTag(row.status).type" effect="plain" round>{{ pushTag(row.status).text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="推送时间" width="170">
              <template #default="{ row }">{{ fmtTime(row.pushedAt) }}</template>
            </el-table-column>
            <el-table-column prop="operator" label="操作人" width="100" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 新建预约 -->
    <el-dialog v-model="apDialog" title="新建咨询预约" width="540px">
      <el-form :model="apForm" label-width="90px">
        <el-form-item label="学生">
          <el-select v-model="apForm.studentRef" filterable placeholder="选择学生" style="width: 100%" @change="onApStudent">
            <el-option v-for="s in students" :key="s.ref" :label="`${s.name}（${s.className}）`" :value="s.ref" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间">
          <el-date-picker v-model="apForm.slot" type="datetime" value-format="YYYY-MM-DD HH:mm" placeholder="选择时间" style="width: 100%" />
        </el-form-item>
        <el-form-item label="咨询师">
          <el-select v-model="apForm.counselor" style="width: 100%">
            <el-option v-for="c in COUNSELORS" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="时长/地点">
          <el-input-number v-model="apForm.duration" :min="20" :max="120" :step="10" />
          <span style="margin: 0 8px">分钟 ·</span>
          <el-select v-model="apForm.room" style="width: 150px">
            <el-option v-for="r in ROOMS" :key="r" :label="r" :value="r" />
          </el-select>
        </el-form-item>
        <el-form-item label="主题"><el-input v-model="apForm.topic" placeholder="如：考前端焦虑" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="apDialog = false">取消</el-button>
        <el-button type="primary" @click="createAppointment">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新建访谈记录 -->
    <el-dialog v-model="ivDialog" title="新建访谈记录" width="600px">
      <el-form :model="ivForm" label-width="90px">
        <el-form-item label="学生">
          <el-select v-model="ivForm.studentRef" filterable placeholder="选择学生" style="width: 100%" @change="onIvStudent">
            <el-option v-for="s in students" :key="s.ref" :label="`${s.name}（${s.className}）`" :value="s.ref" />
          </el-select>
        </el-form-item>
        <el-form-item label="访谈类型">
          <el-radio-group v-model="ivForm.type">
            <el-radio v-for="t in INTERVIEW_TYPES" :key="t" :value="t">{{ t }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="时间">
          <el-date-picker v-model="ivForm.interviewedAt" type="datetime" value-format="YYYY-MM-DD HH:mm" style="width: 100%" />
        </el-form-item>
        <el-form-item label="访谈摘要">
          <el-input v-model="ivForm.summary" type="textarea" :rows="3" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="下一步计划">
          <el-input v-model="ivForm.nextPlan" type="textarea" :rows="2" maxlength="120" show-word-limit />
        </el-form-item>
        <el-form-item label="标记保密"><el-switch v-model="ivForm.confidential" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ivDialog = false">取消</el-button>
        <el-button type="primary" @click="createInterview">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑 iCBT 单元 -->
    <el-dialog v-model="unitDialog" title="编辑 iCBT 单元" width="540px">
      <el-form :model="unitForm" label-width="90px">
        <el-form-item label="单元名称"><el-input v-model="unitForm.title" /></el-form-item>
        <el-form-item label="所属模块"><el-input v-model="unitForm.module" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="unitForm.order" :min="1" :max="99" /></el-form-item>
        <el-form-item label="步骤/时长">
          <el-input-number v-model="unitForm.steps" :min="1" :max="20" /> 步
          <span style="margin: 0 8px" />
          <el-input-number v-model="unitForm.estMinutes" :min="5" :max="120" :step="5" /> 分钟
        </el-form-item>
        <el-form-item label="适用人群"><el-input v-model="unitForm.audience" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="unitForm.status" style="width: 160px">
            <el-option v-for="(v, k) in ICBT_STATUS_MAP" :key="k" :label="v.text" :value="k" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="unitDialog = false">取消</el-button>
        <el-button type="primary" @click="saveUnit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建推送 -->
    <el-dialog v-model="pushDialog" title="新建资源推送" width="540px">
      <el-form :model="pushForm" label-width="90px">
        <el-form-item label="内容标题"><el-input v-model="pushForm.contentTitle" placeholder="选择或输入推送内容标题" /></el-form-item>
        <el-form-item label="内容类型">
          <el-select v-model="pushForm.contentType" style="width: 160px">
            <el-option label="科普文章" value="article" />
            <el-option label="课程资源" value="course" />
            <el-option label="通知公告" value="notice" />
          </el-select>
        </el-form-item>
        <el-form-item label="推送范围">
          <el-select v-model="pushForm.target" style="width: 200px">
            <el-option v-for="t in PUSH_TARGETS" :key="t.label" :label="t.label" :value="t.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道">
          <el-radio-group v-model="pushForm.channel">
            <el-radio value="站内">站内</el-radio>
            <el-radio value="短信">短信</el-radio>
            <el-radio value="家校">家校</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pushDialog = false">取消</el-button>
        <el-button type="primary" @click="createPush">推送</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { interventionApi, studentApi, type DemoStudent } from '@/api'
import {
  APPOINTMENT_MAP,
  APPOINTMENT_SOURCE_MAP,
  ICBT_STATUS_MAP,
  PUSH_STATUS_MAP,
  RESOURCE_KIND_MAP,
  fmtTime,
} from '@/utils/format'
import type {
  AppointmentStatus,
  ConsultAppointment,
  ICBTUnit,
  InterviewRecord,
  InterviewType,
  PushRecord,
} from '@/types/admin'

const COUNSELORS = ['李老师', '王老师']
const ROOMS = ['心理咨询室 A', '心理咨询室 B']
const INTERVIEW_TYPES: InterviewType[] = ['首次访谈', '常规访谈', '危机干预', '家校沟通']
const PUSH_TARGETS = [
  { label: '全校学生', count: 24 },
  { label: '初二年级', count: 6 },
  { label: '高风险学生', count: 5 },
  { label: '全体班主任', count: 7 },
]

// 表格内联样式取标签映射（el-table 插槽 row 为 any，需经强类型函数中转）
const sourceText = (s: ConsultAppointment['source']) => APPOINTMENT_SOURCE_MAP[s]
const apptTag = (s: AppointmentStatus) => APPOINTMENT_MAP[s]
const icbtTag = (s: ICBTUnit['status']) => ICBT_STATUS_MAP[s]
const pushTag = (s: PushRecord['status']) => PUSH_STATUS_MAP[s]
const kindText = (k: PushRecord['contentType']) => RESOURCE_KIND_MAP[k]

const tab = ref('consult')
const loading = ref(false)
const students = ref<DemoStudent[]>([])

// ---- 预约 ----
const appointments = ref<ConsultAppointment[]>([])
const apFilter = ref<AppointmentStatus | ''>('')
const apDialog = ref(false)
const apForm = reactive({ studentRef: '', studentName: '', className: '', slot: '', counselor: '李老师', duration: 50, room: ROOMS[0], topic: '', status: 'pending' as AppointmentStatus, source: 'teacher' as ConsultAppointment['source'] })

const filteredAppointments = computed(() =>
  appointments.value.filter((a) => !apFilter.value || a.status === apFilter.value),
)

function onApStudent(ref: string) {
  const s = students.value.find((x) => x.ref === ref)
  apForm.studentName = s?.name ?? ''
  apForm.className = s?.className ?? ''
}

async function setApStatus(id: string, status: AppointmentStatus) {
  await interventionApi.setAppointmentStatus(id, status)
  ElMessage.success('已更新')
  loadAppointments()
}

async function createAppointment() {
  if (!apForm.studentRef || !apForm.slot) {
    ElMessage.warning('请选择学生与预约时间')
    return
  }
  await interventionApi.createAppointment({ ...apForm })
  apDialog.value = false
  ElMessage.success('预约已创建')
  Object.assign(apForm, { studentRef: '', studentName: '', className: '', slot: '', topic: '' })
  loadAppointments()
}

// ---- 访谈 ----
const interviews = ref<InterviewRecord[]>([])
const ivKeyword = ref('')
const ivDialog = ref(false)
const ivForm = reactive({ studentRef: '', studentName: '', className: '', counselor: '李老师', interviewedAt: '', type: '首次访谈' as InterviewType, summary: '', nextPlan: '', confidential: false })

const filteredInterviews = computed(() =>
  interviews.value.filter((i) => !ivKeyword.value || i.studentName.includes(ivKeyword.value)),
)

function onIvStudent(ref: string) {
  const s = students.value.find((x) => x.ref === ref)
  ivForm.studentName = s?.name ?? ''
  ivForm.className = s?.className ?? ''
}

async function createInterview() {
  if (!ivForm.studentRef || !ivForm.summary.trim()) {
    ElMessage.warning('请选择学生并填写访谈摘要')
    return
  }
  await interventionApi.createInterview({ ...ivForm })
  ivDialog.value = false
  ElMessage.success('访谈记录已保存')
  Object.assign(ivForm, { studentRef: '', studentName: '', className: '', interviewedAt: '', summary: '', nextPlan: '' })
  loadInterviews()
}

// ---- iCBT ----
const units = ref<ICBTUnit[]>([])
const unitDialog = ref(false)
const unitForm = reactive<ICBTUnit>({ id: '', title: '', module: '', order: 1, steps: 3, estMinutes: 20, status: 'draft', audience: '', assigned: 0, completed: 0, updatedAt: '' })

function openUnit(row: ICBTUnit) {
  Object.assign(unitForm, { ...row })
  unitDialog.value = true
}

async function saveUnit() {
  await interventionApi.updateICBTUnit(unitForm.id, { ...unitForm })
  unitDialog.value = false
  ElMessage.success('单元已保存')
  loadUnits()
}

async function toggleUnit(row: ICBTUnit, status: ICBTUnit['status']) {
  await interventionApi.updateICBTUnit(row.id, { status })
  ElMessage.success(status === 'published' ? '已发布' : '已下线')
  loadUnits()
}

// ---- 推送 ----
const pushes = ref<PushRecord[]>([])
const pushDialog = ref(false)
const pushForm = reactive({ contentTitle: '', contentType: 'article' as PushRecord['contentType'], target: PUSH_TARGETS[0].label, channel: '站内' as PushRecord['channel'] })

async function createPush() {
  if (!pushForm.contentTitle.trim()) {
    ElMessage.warning('请填写推送内容标题')
    return
  }
  const targets = PUSH_TARGETS.find((t) => t.label === pushForm.target)?.count ?? 0
  await interventionApi.createPush({ contentTitle: pushForm.contentTitle, contentType: pushForm.contentType, target: pushForm.target, targets, channel: pushForm.channel, status: 'queued', operator: '心理中心' })
  pushDialog.value = false
  ElMessage.success('推送任务已创建')
  pushForm.contentTitle = ''
  loadPushes()
}

// ---- 加载 ----
async function loadAppointments() {
  appointments.value = await interventionApi.appointments()
}
async function loadInterviews() {
  interviews.value = await interventionApi.interviews()
}
async function loadUnits() {
  units.value = await interventionApi.icbtUnits()
}
async function loadPushes() {
  pushes.value = await interventionApi.pushes()
}

async function reload() {
  loading.value = true
  try {
    await Promise.all([loadAppointments(), loadInterviews(), loadUnits(), loadPushes()])
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  students.value = await studentApi.list()
  reload()
})
</script>

<style scoped>
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
.flex-spacer { flex: 1; }
</style>
