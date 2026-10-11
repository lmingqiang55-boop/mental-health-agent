import { defineStore } from 'pinia'
import { interventionApi, teacherApi } from '@/api'

/**
 * 全局待办中心（对标开源后台的「消息 / 待办」能力）。
 *
 * 聚合当前角色需要处理的跨模块事项，避免遗漏：
 *  - 待认领预警（真实接口 /api/teacher/high-risk）
 *  - 待确认咨询预约（interventionApi，后端就绪后自动切真实接口）
 *  - 待发送资源推送（interventionApi）
 * 后端部分不可用时静默降级，不影响其余来源。
 */
export type TodoKind = 'warning' | 'appointment' | 'push'

export interface TodoItem {
  id: string
  kind: TodoKind
  title: string
  desc: string
  count: number
  to: string
  level: 'high' | 'medium' | 'normal'
}

interface NotifyState {
  todos: TodoItem[]
  loading: boolean
  loadedAt: number
}

export const useNotifyStore = defineStore('notify', {
  state: (): NotifyState => ({ todos: [], loading: false, loadedAt: 0 }),
  getters: {
    total: (s) => s.todos.reduce((n, t) => n + t.count, 0),
  },
  actions: {
    async refresh() {
      this.loading = true
      const [risk, appts, pushes] = await Promise.all([
        teacherApi.listHighRisk().catch(() => null),
        interventionApi.appointments().catch(() => null),
        interventionApi.pushes().catch(() => null),
      ])

      const items: TodoItem[] = []

      if (risk) {
        const pending = risk.students.filter((s) => s.follow_up_status === 'pending').length
        if (pending > 0) {
          items.push({
            id: 'warning-pending',
            kind: 'warning',
            title: '待认领预警',
            desc: '中/高风险学生尚未分配跟进人',
            count: pending,
            to: '/warning',
            level: 'high',
          })
        }
      }

      if (appts) {
        const pending = appts.filter((a) => a.status === 'pending').length
        if (pending > 0) {
          items.push({
            id: 'appointment-pending',
            kind: 'appointment',
            title: '待确认咨询预约',
            desc: '学生 / 预警转介的心理咨询待确认',
            count: pending,
            to: '/intervention',
            level: 'normal',
          })
        }
      }

      if (pushes) {
        const queued = pushes.filter((p) => p.status === 'queued').length
        if (queued > 0) {
          items.push({
            id: 'push-queued',
            kind: 'push',
            title: '待发送资源推送',
            desc: '已排期但尚未触达学生的资源 / 通知',
            count: queued,
            to: '/intervention',
            level: 'normal',
          })
        }
      }

      this.todos = items
      this.loading = false
      this.loadedAt = Date.now()
    },
  },
})
