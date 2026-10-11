<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">系统管理</h2>
        <p class="page-subtitle">组织架构 / 用户管理 / 角色权限 / 数据字典 / 审计日志 / 安全设置</p>
      </div>
      <el-button :icon="Refresh" circle @click="reload" />
    </div>

    <div class="xq-card">
      <el-tabs v-model="tab" @tab-change="onTabChange">
        <el-tab-pane label="组织架构" name="org" />
        <el-tab-pane label="用户管理" name="users" />
        <el-tab-pane label="角色权限" name="roles" />
        <el-tab-pane label="数据字典" name="dicts" />
        <el-tab-pane label="审计日志" name="logs" />
        <el-tab-pane label="安全设置" name="security" />
      </el-tabs>

      <!-- 组织架构 -->
      <template v-if="tab === 'org'">
        <div class="filter-bar">
          <span class="cell-sub">学校 → 年级 → 班级，共 {{ orgTree.length }} 个直属节点，{{ orgTotal }} 个班级</span>
          <div class="flex-spacer" />
          <el-input v-model="orgKeyword" placeholder="搜索名称" clearable style="width: 200px" :prefix-icon="Search" />
        </div>
        <el-tree
          ref="orgTreeRef"
          v-loading="loading"
          :data="orgTree"
          node-key="id"
          :props="{ label: 'name', children: 'children' }"
          :filter-node-method="filterOrg"
          default-expand-all
          class="org-tree"
        >
          <template #default="{ data }">
            <span class="org-node">
              <el-tag size="small" effect="plain" :type="orgType(data.type).type">{{ orgType(data.type).text }}</el-tag>
              <span class="org-name">{{ data.name }}</span>
              <span class="cell-sub">{{ data.studentCount }} 名学生<span v-if="data.headteacher"> · 班主任 {{ data.headteacher }}</span></span>
            </span>
          </template>
        </el-tree>
      </template>

      <!-- 用户管理 -->
      <template v-else-if="tab === 'users'">
        <div class="filter-bar">
          <el-input v-model="userKeyword" placeholder="搜索姓名 / 账号" clearable style="width: 220px" :prefix-icon="Search" />
          <el-select v-model="userRole" placeholder="角色" clearable style="width: 140px">
            <el-option v-for="r in ROLE_OPTIONS" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
          <span class="cell-sub">共 {{ filteredUsers.length }} 个账号</span>
          <div class="flex-spacer" />
          <el-button type="primary" :icon="Plus" @click="userDialog = true">新增账号</el-button>
        </div>
        <el-table v-loading="loading" :data="filteredUsers" size="large">
          <el-table-column prop="name" label="姓名" width="120" />
          <el-table-column prop="account" label="登录账号" width="140" />
          <el-table-column label="角色" width="120">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" round>{{ row.roleName }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="scope" label="数据范围" min-width="140" />
          <el-table-column prop="phone" label="联系方式" width="140" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain" round>
                {{ row.status === 'active' ? '正常' : '已停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近登录" width="170">
            <template #default="{ row }">
              <span v-if="row.lastLogin">{{ fmtTime(row.lastLogin) }}</span>
              <span v-else class="cell-sub">从未登录</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'active'" link type="danger" @click="toggleUser(row, 'disabled')">停用</el-button>
              <el-button v-else link type="success" @click="toggleUser(row, 'active')">启用</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-dialog v-model="userDialog" title="新增账号" width="480px">
          <el-form :model="userForm" label-width="90px">
            <el-form-item label="姓名"><el-input v-model="userForm.name" /></el-form-item>
            <el-form-item label="登录账号"><el-input v-model="userForm.account" /></el-form-item>
            <el-form-item label="角色">
              <el-select v-model="userForm.roleKey" placeholder="请选择" style="width: 100%">
                <el-option v-for="r in ROLE_OPTIONS" :key="r.value" :label="r.label" :value="r.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="数据范围"><el-input v-model="userForm.scope" placeholder="如：初二3班" /></el-form-item>
            <el-form-item label="联系方式"><el-input v-model="userForm.phone" /></el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="userDialog = false">取消</el-button>
            <el-button type="primary" @click="createUser">保存</el-button>
          </template>
        </el-dialog>
      </template>

      <!-- 角色权限 -->
      <template v-else-if="tab === 'roles'">
        <div class="filter-bar">
          <span class="cell-sub">勾选各角色可访问的功能模块；修改后需点击右侧「保存权限」生效</span>
          <div class="flex-spacer" />
          <el-button type="primary" :icon="Check" :loading="saving" @click="saveRoles">保存权限</el-button>
        </div>
        <el-table v-loading="loading" :data="permissions" size="large">
          <el-table-column prop="module" label="功能模块" min-width="180" />
          <el-table-column v-for="r in ROLE_COLUMNS" :key="r.key" :label="r.label" align="center" width="130">
            <template #default="{ row }">
              <el-checkbox v-model="row[r.key]" />
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- 数据字典 -->
      <template v-else-if="tab === 'dicts'">
        <div class="filter-bar">
          <el-select v-model="dictCode" placeholder="字典编码" clearable style="width: 180px">
            <el-option v-for="c in dictCodes" :key="c" :label="c" :value="c" />
          </el-select>
          <el-input v-model="dictKeyword" placeholder="搜索标签" clearable style="width: 200px" :prefix-icon="Search" />
          <span class="cell-sub">共 {{ filteredDicts.length }} 项</span>
          <div class="flex-spacer" />
          <el-button type="primary" :icon="Plus" @click="dictDialog = true">新增字典项</el-button>
        </div>
        <el-table v-loading="loading" :data="filteredDicts" size="large">
          <el-table-column prop="code" label="字典编码" width="160" />
          <el-table-column prop="label" label="显示标签" width="180" />
          <el-table-column prop="value" label="值" width="150" />
          <el-table-column prop="sort" label="排序" width="90" sortable />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" @change="onDictSwitch(row, $event)" />
            </template>
          </el-table-column>
          <el-table-column prop="remark" label="备注" min-width="140" />
        </el-table>

        <el-dialog v-model="dictDialog" title="新增字典项" width="480px">
          <el-form :model="dictForm" label-width="90px">
            <el-form-item label="字典编码">
              <el-select v-model="dictForm.code" allow-create filterable default-first-option placeholder="选择或输入" style="width: 100%">
                <el-option v-for="c in dictCodes" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
            <el-form-item label="显示标签"><el-input v-model="dictForm.label" /></el-form-item>
            <el-form-item label="值"><el-input v-model="dictForm.value" /></el-form-item>
            <el-form-item label="排序"><el-input-number v-model="dictForm.sort" :min="1" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="dictForm.remark" /></el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="dictDialog = false">取消</el-button>
            <el-button type="primary" @click="createDict">保存</el-button>
          </template>
        </el-dialog>
      </template>

      <!-- 审计日志 -->
      <template v-else-if="tab === 'logs'">
        <div class="filter-bar">
          <el-input v-model="logKeyword" placeholder="搜索操作人 / 目标" clearable style="width: 220px" :prefix-icon="Search" />
          <el-select v-model="logResult" placeholder="结果" clearable style="width: 130px">
            <el-option label="成功" value="success" />
            <el-option label="失败" value="fail" />
          </el-select>
          <span class="cell-sub">共 {{ filteredLogs.length }} 条</span>
        </div>
        <el-table v-loading="loading" :data="filteredLogs" size="large">
          <el-table-column prop="createdAt" label="时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
          </el-table-column>
          <el-table-column prop="operator" label="操作人" width="120" />
          <el-table-column prop="roleName" label="角色" width="120" />
          <el-table-column prop="action" label="操作" width="130" />
          <el-table-column prop="target" label="对象" min-width="220" show-overflow-tooltip />
          <el-table-column prop="ip" label="IP" width="140" />
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag :type="row.result === 'success' ? 'success' : 'danger'" effect="plain" round>
                {{ row.result === 'success' ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- 安全设置 -->
      <template v-else-if="tab === 'security'">
        <el-form :model="security" label-width="140px" class="security-form">
          <el-form-item label="导出添加水印">
            <el-switch v-model="security.watermark" />
            <span class="form-hint">导出报告/名单时叠加水印与操作人信息</span>
          </el-form-item>
          <el-form-item label="密码最小长度">
            <el-input-number v-model="security.passwordMinLength" :min="6" :max="20" />
          </el-form-item>
          <el-form-item label="密码复杂度校验">
            <el-switch v-model="security.passwordComplexity" />
            <span class="form-hint">需包含大小写字母、数字、符号中的至少三类</span>
          </el-form-item>
          <el-form-item label="登录失败锁定">
            <el-input-number v-model="security.loginFailLimit" :min="1" :max="10" />
            <span class="form-hint">连续失败达到该次数后锁定账号</span>
          </el-form-item>
          <el-form-item label="会话超时（分钟）">
            <el-input-number v-model="security.sessionTimeout" :min="5" :max="120" :step="5" />
          </el-form-item>
          <el-form-item label="导出二次确认">
            <el-switch v-model="security.exportConfirm" />
            <span class="form-hint">导出含隐私字段的数据前需再次确认</span>
          </el-form-item>
          <el-form-item label="IP 白名单">
            <el-input v-model="security.ipWhitelist" placeholder="如 10.12.0.0/16" style="width: 260px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="saveSecurity">保存设置</el-button>
            <el-button @click="loadSecurity">重置</el-button>
          </el-form-item>
        </el-form>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="以上为演示配置，保存后仅作用于本地 mock；后端安全模块接口就绪后本页无需改动。"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Plus, Refresh, Search } from '@element-plus/icons-vue'
import type { ElTree } from 'element-plus'
import { systemApi } from '@/api'
import { fmtTime } from '@/utils/format'
import type { AuditLog, DictItem, OrgNode, PermissionRow, SecurityPolicy, SysUser } from '@/types/admin'

type OrgTreeNode = OrgNode & { children?: OrgTreeNode[] }

const ORG_TYPE_MAP: Record<OrgNode['type'], { text: string; type: 'primary' | 'success' | 'warning' }> = {
  school: { text: '学校', type: 'primary' },
  grade: { text: '年级', type: 'warning' },
  class: { text: '班级', type: 'success' },
}
const ROLE_OPTIONS = [
  { value: 'admin', label: '系统管理员' },
  { value: 'psych', label: '心理教师' },
  { value: 'headteacher', label: '班主任' },
  { value: 'manager', label: '管理层' },
]
const ROLE_COLUMNS: { key: keyof Omit<PermissionRow, 'module'>; label: string }[] = [
  { key: 'admin', label: '系统管理员' },
  { key: 'psych', label: '心理教师' },
  { key: 'headteacher', label: '班主任' },
  { key: 'manager', label: '管理层' },
]

const tab = ref('org')
const loading = ref(false)
const saving = ref(false)

const orgType = (t: OrgNode['type']) => ORG_TYPE_MAP[t]

// 组织架构
const orgRaw = ref<OrgNode[]>([])
const orgKeyword = ref('')
const orgTreeRef = ref<InstanceType<typeof ElTree>>()
const orgTree = computed<OrgTreeNode[]>(() => buildTree(orgRaw.value))
const orgTotal = computed(() => orgRaw.value.filter((n) => n.type === 'class').length)

// 用户管理
const users = ref<SysUser[]>([])
const userKeyword = ref('')
const userRole = ref('')
const userDialog = ref(false)
const userForm = reactive({ name: '', account: '', roleKey: 'psych', scope: '', phone: '' })

// 角色权限
const permissions = ref<PermissionRow[]>([])

// 数据字典
const dicts = ref<DictItem[]>([])
const dictCode = ref('')
const dictKeyword = ref('')
const dictDialog = ref(false)
const dictForm = reactive({ code: '', label: '', value: '', sort: 1, remark: '' })

// 审计日志
const logs = ref<AuditLog[]>([])
const logKeyword = ref('')
const logResult = ref('')

// 安全设置
const security = reactive<SecurityPolicy>({
  watermark: true,
  passwordMinLength: 8,
  passwordComplexity: true,
  loginFailLimit: 5,
  sessionTimeout: 30,
  exportConfirm: true,
  ipWhitelist: '',
})

const filteredUsers = computed(() =>
  users.value.filter(
    (u) =>
      (!userKeyword.value || u.name.includes(userKeyword.value) || u.account.includes(userKeyword.value)) &&
      (!userRole.value || u.roleKey === userRole.value),
  ),
)
const dictCodes = computed(() => [...new Set(dicts.value.map((d) => d.code))])
const filteredDicts = computed(() =>
  dicts.value.filter(
    (d) => (!dictCode.value || d.code === dictCode.value) && (!dictKeyword.value || d.label.includes(dictKeyword.value)),
  ),
)
const filteredLogs = computed(() =>
  logs.value.filter(
    (l) =>
      (!logKeyword.value || l.operator.includes(logKeyword.value) || l.target.includes(logKeyword.value)) &&
      (!logResult.value || l.result === logResult.value),
  ),
)

function buildTree(nodes: OrgNode[]): OrgTreeNode[] {
  const map = new Map<string, OrgTreeNode>()
  const roots: OrgTreeNode[] = []
  nodes.forEach((n) => map.set(n.id, { ...n, children: [] }))
  nodes.forEach((n) => {
    const node = map.get(n.id)!
    const parent = n.parentId ? map.get(n.parentId) : undefined
    if (parent) parent.children!.push(node)
    else roots.push(node)
  })
  return roots
}

function filterOrg(value: string, data: OrgTreeNode) {
  if (!value) return true
  return data.name.includes(value)
}

watch(orgKeyword, (v) => orgTreeRef.value?.filter(v))

function onTabChange() {
  loadTab()
}

async function loadTab() {
  loading.value = true
  try {
    if (tab.value === 'org') orgRaw.value = await systemApi.orgTree()
    else if (tab.value === 'users') users.value = await systemApi.users()
    else if (tab.value === 'roles') permissions.value = await systemApi.permissions()
    else if (tab.value === 'dicts') dicts.value = await systemApi.dicts()
    else if (tab.value === 'logs') logs.value = await systemApi.auditLogs()
    else if (tab.value === 'security') await loadSecurity()
  } finally {
    loading.value = false
  }
}

async function toggleUser(row: SysUser, status: SysUser['status']) {
  await systemApi.setUserStatus(row.id, status)
  ElMessage.success(status === 'active' ? '已启用' : '已停用')
  users.value = await systemApi.users()
}

function createUser() {
  if (!userForm.name.trim() || !userForm.account.trim()) {
    ElMessage.warning('请填写姓名与登录账号')
    return
  }
  const role = ROLE_OPTIONS.find((r) => r.value === userForm.roleKey)
  users.value.unshift({
    id: `local-${Date.now()}`,
    name: userForm.name,
    account: userForm.account,
    roleKey: userForm.roleKey,
    roleName: role?.label ?? userForm.roleKey,
    scope: userForm.scope || '全校',
    phone: userForm.phone,
    status: 'active',
    lastLogin: null,
  })
  Object.assign(userForm, { name: '', account: '', roleKey: 'psych', scope: '', phone: '' })
  userDialog.value = false
  ElMessage.success('已新增（本地演示，未写入后端）')
}

async function saveRoles() {
  saving.value = true
  try {
    await systemApi.savePermissions(permissions.value)
    ElMessage.success('权限已保存')
  } finally {
    saving.value = false
  }
}

async function toggleDict(row: DictItem, enabled: boolean) {
  await systemApi.setDictEnabled(row.id, enabled)
  ElMessage.success(enabled ? '已启用' : '已停用')
  dicts.value = await systemApi.dicts()
}

function onDictSwitch(row: DictItem, val: string | number | boolean) {
  toggleDict(row, Boolean(val))
}

function createDict() {
  if (!dictForm.code.trim() || !dictForm.label.trim()) {
    ElMessage.warning('请填写字典编码与标签')
    return
  }
  dicts.value.push({ id: `local-${Date.now()}`, enabled: true, ...dictForm })
  Object.assign(dictForm, { code: '', label: '', value: '', sort: 1, remark: '' })
  dictDialog.value = false
  ElMessage.success('已新增（本地演示，未写入后端）')
}

async function loadSecurity() {
  Object.assign(security, await systemApi.getSecurity())
}

async function saveSecurity() {
  saving.value = true
  try {
    await systemApi.saveSecurity({ ...security })
    ElMessage.success('安全设置已保存')
  } finally {
    saving.value = false
  }
}

async function reload() {
  await loadTab()
}

onMounted(loadTab)
</script>

<style scoped>
.filter-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
.flex-spacer { flex: 1; }
.org-tree { --el-tree-node-content-height: 34px; }
.org-node { display: flex; align-items: center; gap: 8px; }
.org-name { font-weight: 600; }
.security-form { max-width: 560px; }
.form-hint { margin-left: 12px; color: var(--el-text-color-secondary); font-size: 12px; }
</style>
