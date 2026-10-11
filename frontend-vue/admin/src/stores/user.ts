import { defineStore } from 'pinia'

/**
 * 角色说明（见 docs/管理端规划.md）：
 * 后端目前无鉴权体系（P0 缺口），此处为前端身份切换，用于角色差异化工作台与菜单显隐。
 * counselor_ref 用于跟进备注 / 沟通消息的落库标识。
 */
export type RoleKey = 'admin' | 'psych' | 'headteacher' | 'manager'

export interface RoleDef {
  key: RoleKey
  name: string
  desc: string
  scopeText: string
}

export const ROLES: RoleDef[] = [
  { key: 'admin', name: '系统管理员', desc: '组织、用户、角色、日志', scopeText: '全校（系统配置）' },
  { key: 'psych', name: '心理教师', desc: '测评 / 预警处置 / 干预', scopeText: '全校学生' },
  { key: 'headteacher', name: '班主任', desc: '班级概览 / 关怀上报', scopeText: '本班（示例：初二3班）' },
  { key: 'manager', name: '管理层', desc: '统计 / 督办 / 趋势', scopeText: '全校 / 年级' },
]

interface UserState {
  role: RoleKey | null
  displayName: string
  counselorRef: string
}

const STORAGE_KEY = 'xq_admin_user'

function load(): UserState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as UserState
  } catch {
    /* ignore */
  }
  return { role: null, displayName: '', counselorRef: '' }
}

export const useUserStore = defineStore('user', {
  state: (): UserState => load(),
  getters: {
    loggedIn: (s) => s.role !== null,
    roleDef: (s) => ROLES.find((r) => r.key === s.role) ?? null,
  },
  actions: {
    login(role: RoleKey, displayName: string) {
      this.role = role
      this.displayName = displayName || ROLES.find((r) => r.key === role)?.name || ''
      this.counselorRef = `counselor-${role}`
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.$state))
    },
    logout() {
      this.role = null
      this.displayName = ''
      this.counselorRef = ''
      localStorage.removeItem(STORAGE_KEY)
    },
  },
})
