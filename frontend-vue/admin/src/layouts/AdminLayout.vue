<template>
  <el-container class="admin-layout">
    <!-- 纯白侧边栏 + 橙色选中态（设计规范定稿） -->
    <el-aside :width="collapsed ? '64px' : '220px'" class="sidebar">
      <div class="brand" @click="$router.push('/dashboard')">
        <span class="brand-logo">晴</span>
        <span v-if="!collapsed" class="brand-name">心晴 · 管理端</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        router
        class="side-menu"
      >
        <el-menu-item v-for="m in visibleMenus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <template #title>{{ m.title }}</template>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer" @click="collapsed = !collapsed">
        <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar" height="56px">
        <div class="topbar-left">
          <span class="crumb">{{ route.meta.title ?? '工作台' }}</span>
          <span class="scope-tag">{{ user.roleDef?.scopeText }}</span>
        </div>
        <div class="topbar-right">
          <span class="backend-status" :class="{ ok: backendOk }">
            <span class="dot" />后端{{ backendOk ? '已连接' : '未连接' }}
          </span>
          <NotificationCenter />
          <el-dropdown @command="onSwitchRole">
            <span class="user-entry">
              <el-avatar :size="28" class="avatar">{{ avatarText }}</el-avatar>
              <span class="user-name">{{ user.displayName }}</span>
              <span class="role-tag">{{ user.roleDef?.name }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="r in ROLES"
                  :key="r.key"
                  :command="r.key"
                  :disabled="r.key === user.role"
                >
                  切换为{{ r.name }}
                </el-dropdown-item>
                <el-dropdown-item divided command="__logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <TagsView />
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  DataAnalysis, Document, Expand, Files, Fold, HomeFilled,
  Service, Setting, User, Warning,
} from '@element-plus/icons-vue'
import { healthApi } from '@/api'
import { ROLES, useUserStore, type RoleKey } from '@/stores/user'
import NotificationCenter from '@/components/common/NotificationCenter.vue'
import TagsView from '@/components/common/TagsView.vue'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const collapsed = ref(false)
const backendOk = ref(false)

interface MenuItem { path: string; title: string; icon: unknown; roles?: RoleKey[] }

const MENUS: MenuItem[] = [
  { path: '/dashboard', title: '工作台', icon: HomeFilled },
  { path: '/warning', title: '预警管理', icon: Warning, roles: ['psych', 'headteacher', 'manager'] },
  { path: '/students', title: '学生心理档案', icon: User, roles: ['psych', 'headteacher'] },
  { path: '/assessment/tasks', title: '测评任务', icon: Document, roles: ['psych'] },
  { path: '/assessment/results', title: '测评结果', icon: Files, roles: ['psych', 'headteacher', 'manager'] },
  { path: '/intervention', title: '干预与咨询', icon: Service, roles: ['psych'] },
  { path: '/resource', title: '资源中心', icon: Files, roles: ['psych', 'headteacher'] },
  { path: '/stats', title: '统计报表', icon: DataAnalysis, roles: ['psych', 'manager'] },
  { path: '/system', title: '系统管理', icon: Setting, roles: ['admin'] },
]

const visibleMenus = computed(() =>
  MENUS.filter((m) => !m.roles || (user.role && m.roles.includes(user.role))),
)

const activeMenu = computed(() => {
  // 详情页高亮所属列表菜单
  if (route.path.startsWith('/students/')) return '/students'
  if (route.path.startsWith('/assessment/tasks')) return '/assessment/tasks'
  if (route.path.startsWith('/assessment/results')) return '/assessment/results'
  return route.path
})

const avatarText = computed(() => (user.roleDef?.name ?? '访').slice(0, 1))

function onSwitchRole(cmd: string) {
  if (cmd === '__logout') {
    user.logout()
    router.push('/login')
    return
  }
  user.login(cmd as RoleKey, '')
  router.push('/dashboard')
}

onMounted(async () => {
  try {
    await healthApi.check()
    backendOk.value = true
  } catch {
    backendOk.value = false
  }
})
</script>

<style scoped>
.admin-layout { height: 100vh; }

.sidebar {
  background: #fff;
  border-right: 1px solid var(--xq-border);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 14px;
  cursor: pointer;
}

.brand-logo {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--xq-primary), #f6a86b);
  color: #fff;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.brand-name { font-weight: 600; font-size: 15px; white-space: nowrap; }

.side-menu { border-right: none; flex: 1; }

.side-menu :deep(.el-menu-item) {
  margin: 2px 8px;
  border-radius: 8px;
  height: 44px;
  line-height: 44px;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: var(--xq-primary-light);
  color: var(--xq-primary-deep);
  font-weight: 600;
}

.sidebar-footer {
  padding: 12px;
  text-align: center;
  color: var(--xq-text-secondary);
  cursor: pointer;
  border-top: 1px solid var(--xq-border);
}
.sidebar-footer:hover { color: var(--xq-primary); }

.topbar {
  background: #fff;
  border-bottom: 1px solid var(--xq-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}

.topbar-left { display: flex; align-items: center; gap: 10px; }
.crumb { font-weight: 600; }
.scope-tag {
  font-size: 12px;
  color: var(--xq-primary-deep);
  background: var(--xq-primary-light);
  padding: 2px 10px;
  border-radius: 20px;
}

.topbar-right { display: flex; align-items: center; gap: 16px; }

.backend-status {
  font-size: 12px;
  color: var(--xq-text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.backend-status .dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--xq-risk-high);
}
.backend-status.ok .dot { background: var(--xq-risk-low); }

.user-entry { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.avatar { background: var(--xq-primary-light); color: var(--xq-primary-deep); font-weight: 600; }
.user-name { font-weight: 500; }
.role-tag {
  font-size: 12px;
  color: var(--xq-text-secondary);
  border: 1px solid var(--xq-border);
  border-radius: 4px;
  padding: 1px 6px;
}

.main { background: var(--xq-bg); padding: 0; overflow-y: auto; }
</style>
