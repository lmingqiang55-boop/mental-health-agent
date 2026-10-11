import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore, type RoleKey } from '@/stores/user'

/**
 * meta.roles：可见角色；缺省 = 全部已登录角色可见。
 * 注意：前端显隐只是体验优化，后端启用鉴权后必须二次校验。
 */
const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/login/LoginPage.vue'), meta: { title: '登录' } },
  {
    path: '/',
    component: () => import('@/layouts/AdminLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/dashboard/DashboardPage.vue'), meta: { title: '工作台' } },

      { path: 'warning', name: 'warning', component: () => import('@/views/warning/WarningList.vue'), meta: { title: '预警管理', roles: ['psych', 'headteacher', 'manager'] } },

      { path: 'students', name: 'students', component: () => import('@/views/student/StudentList.vue'), meta: { title: '学生心理档案', roles: ['psych', 'headteacher'] } },
      { path: 'students/:ref', name: 'student-detail', component: () => import('@/views/student/StudentDetail.vue'), meta: { title: '个体档案', roles: ['psych', 'headteacher'] } },

      { path: 'assessment/tasks', name: 'assessment-tasks', component: () => import('@/views/assessment/TaskList.vue'), meta: { title: '测评任务', roles: ['psych'] } },
      { path: 'assessment/tasks/create', name: 'assessment-task-create', component: () => import('@/views/assessment/TaskCreate.vue'), meta: { title: '创建测评任务', roles: ['psych'] } },
      { path: 'assessment/tasks/:id', name: 'assessment-task-detail', component: () => import('@/views/assessment/TaskDetail.vue'), meta: { title: '任务详情', roles: ['psych'] } },
      { path: 'assessment/results', name: 'assessment-results', component: () => import('@/views/assessment/ResultList.vue'), meta: { title: '测评结果', roles: ['psych', 'headteacher', 'manager'] } },
      { path: 'assessment/results/:recordId', name: 'report-detail', component: () => import('@/views/assessment/ReportDetail.vue'), meta: { title: '报告详情', roles: ['psych', 'headteacher', 'manager'] } },

      { path: 'intervention', name: 'intervention', component: () => import('@/views/intervention/InterventionPage.vue'), meta: { title: '干预与咨询', roles: ['psych'] } },
      { path: 'resource', name: 'resource', component: () => import('@/views/resource/ResourcePage.vue'), meta: { title: '资源中心', roles: ['psych', 'headteacher'] } },
      { path: 'stats', name: 'stats', component: () => import('@/views/stats/StatsOverview.vue'), meta: { title: '统计报表', roles: ['psych', 'manager'] } },
      { path: 'system', name: 'system', component: () => import('@/views/system/SystemPage.vue'), meta: { title: '系统管理', roles: ['admin'] } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

// hash 模式：产物可直接用 file:// 双击打开，无需服务器托管
export const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to) => {
  const user = useUserStore()
  if (to.path !== '/login' && !user.loggedIn) return { path: '/login' }
  if (to.path === '/login' && user.loggedIn) return { path: '/dashboard' }
  const roles = to.meta.roles as RoleKey[] | undefined
  if (roles && user.role && !roles.includes(user.role)) return { path: '/dashboard' }
  document.title = to.meta.title ? `${to.meta.title as string} · 心晴管理端` : '心晴管理端'
  return true
})
