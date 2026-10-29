import { http } from './http'
import { interventionMock, resourceMock, studentMock, systemMock, taskMock } from './mock'
import type {
  CommunicationMessage,
  EvaluationRecord,
  GroupStats,
  HighRiskItem,
  RecordSummary,
} from '@/types'
import type { AppointmentStatus, ConsultAppointment, ICBTStatus, ICBTUnit } from '@/types/admin'

// ---- 老师端（现有后端骨架，无鉴权）----
export const teacherApi = {
  listRecords: () =>
    http.get<{ records: RecordSummary[]; total: number }>('/api/teacher/records').then((r) => r.data),

  getRecord: (recordId: string) =>
    http.get<{ record: EvaluationRecord }>(`/api/teacher/records/${recordId}`).then((r) => r.data.record),

  getStudentHistory: (studentRef: string) =>
    http
      .get<{ student_ref: string; records: EvaluationRecord[]; total: number }>(
        `/api/teacher/student/${studentRef}`,
      )
      .then((r) => r.data),

  listHighRisk: () =>
    http
      .get<{ high_risk_count: number; students: HighRiskItem[] }>('/api/teacher/high-risk')
      .then((r) => r.data),

  addNote: (recordId: string, counselorRef: string, content: string) =>
    http
      .post<{ status: string; record: EvaluationRecord }>(`/api/teacher/records/${recordId}/notes`, {
        counselor_ref: counselorRef,
        content,
      })
      .then((r) => r.data),

  groupStats: () => http.get<GroupStats>('/api/teacher/group-stats').then((r) => r.data),
}

// ---- 学生历史 ----
export const historyApi = {
  byStudent: (studentRef: string) =>
    http
      .get<{ student_ref: string; records: EvaluationRecord[]; total: number }>(
        `/api/history/${studentRef}`,
      )
      .then((r) => r.data),
}

// ---- 双向沟通 ----
export const communicationApi = {
  list: (studentRef: string) =>
    http
      .get<{ student_ref: string; messages: CommunicationMessage[] }>(`/api/communication/${studentRef}`)
      .then((r) => r.data),

  send: (payload: {
    student_ref: string
    counselor_ref: string | null
    direction: 'student_to_counselor' | 'counselor_to_student'
    content: string
  }) =>
    http
      .post<{ status: string; message: CommunicationMessage }>('/api/communication', payload)
      .then((r) => r.data),
}

// ---- 健康检查 ----
export const healthApi = {
  check: () => http.get<{ status: string }>('/api/health').then((r) => r.data),
}

/**
 * 以下模块后端尚未接入，当前由演示数据打底，接口就绪后替换实现即可，页面无需改动。
 * 页面只依赖这些 *Api，后端就绪后把实现换成 http 调用即可，页面零改动。
 * 注释里的「真实接口」是待对齐的契约路径。
 */

// ---- 测评任务（真实接口：GET/POST /api/assessment/tasks ...）----
export const taskApi = {
  list: () => taskMock.list(),
  get: (id: string) => taskMock.get(id),
  create: (payload: Parameters<typeof taskMock.create>[0]) => taskMock.create(payload),
  update: (id: string, patch: Parameters<typeof taskMock.update>[1]) => taskMock.update(id, patch),
  setStatus: (id: string, status: Parameters<typeof taskMock.setStatus>[1]) => taskMock.setStatus(id, status),
  remove: (id: string) => taskMock.remove(id),
  participants: (id: string) => taskMock.participants(id),
}

// ---- 干预与咨询：预约 / iCBT 走真实接口，访谈记录 / 资源推送暂用 mock ----

/** 后端 UTC ISO → 本地 'YYYY-MM-DD HH:mm'（与列表展示格式一致）。 */
function fmtIso(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

interface RawAppointment {
  id: string
  student_ref: string
  student_name: string | null
  class_name: string | null
  counselor: string | null
  slot: string
  preferred_label: string | null
  duration: number
  room: string | null
  topic: string | null
  status: AppointmentStatus
  source: ConsultAppointment['source']
  created_at: string
}

function toAppointment(raw: RawAppointment): ConsultAppointment {
  return {
    id: raw.id,
    studentRef: raw.student_ref,
    studentName: raw.student_name ?? '',
    className: raw.class_name ?? '',
    counselor: raw.counselor ?? '',
    slot: raw.slot,
    duration: raw.duration,
    room: raw.room ?? '',
    topic: raw.topic ?? '',
    status: raw.status,
    source: raw.source,
    createdAt: fmtIso(raw.created_at),
  }
}

interface RawICBTUnit {
  id: string
  no: number
  title: string
  module: string
  order: number
  steps: number
  est_minutes: number
  status: ICBTStatus
  audience: string | null
  updated_at: string
  assigned: number
  completed: number
}

function toICBTUnit(raw: RawICBTUnit): ICBTUnit {
  return {
    id: raw.id,
    title: raw.title,
    module: raw.module,
    order: raw.order,
    steps: raw.steps,
    estMinutes: raw.est_minutes,
    status: raw.status,
    audience: raw.audience ?? '',
    assigned: raw.assigned,
    completed: raw.completed,
    updatedAt: fmtIso(raw.updated_at),
  }
}

export const interventionApi = {
  appointments: () =>
    http
      .get<{ appointments: RawAppointment[]; total: number }>('/api/counseling/appointments')
      .then((r) => r.data.appointments.map(toAppointment)),

  createAppointment: (payload: Omit<ConsultAppointment, 'id' | 'createdAt'>) =>
    http
      .post<{ appointment: RawAppointment }>('/api/counseling/appointments', {
        student_ref: payload.studentRef,
        student_name: payload.studentName || null,
        class_name: payload.className || null,
        counselor: payload.counselor || null,
        slot: payload.slot,
        duration: payload.duration,
        room: payload.room || null,
        topic: payload.topic || null,
        status: payload.status,
        source: payload.source,
      })
      .then((r) => toAppointment(r.data.appointment)),

  setAppointmentStatus: (id: string, status: AppointmentStatus) =>
    http
      .post<{ appointment: RawAppointment }>(`/api/counseling/appointments/${id}/status`, { status })
      .then(() => undefined),

  // 访谈记录 / 资源推送：后端暂无接口，继续 mock
  interviews: () => interventionMock.interviews(),
  createInterview: (payload: Parameters<typeof interventionMock.createInterview>[0]) =>
    interventionMock.createInterview(payload),

  icbtUnits: () =>
    http
      .get<{ units: RawICBTUnit[] }>('/api/heal/icbt/units')
      .then((r) => r.data.units.map(toICBTUnit).sort((a, b) => a.order - b.order)),

  updateICBTUnit: (id: string, patch: Partial<ICBTUnit>) => {
    const body: Record<string, unknown> = {}
    if (patch.title !== undefined) body.title = patch.title
    if (patch.module !== undefined) body.module = patch.module
    if (patch.order !== undefined) body.order = patch.order
    if (patch.steps !== undefined) body.steps = patch.steps
    if (patch.estMinutes !== undefined) body.est_minutes = patch.estMinutes
    if (patch.status !== undefined) body.status = patch.status
    if (patch.audience !== undefined) body.audience = patch.audience
    return http.put<{ unit: RawICBTUnit }>(`/api/heal/icbt/units/${id}`, body).then(() => undefined)
  },

  pushes: () => interventionMock.pushes(),
  createPush: (payload: Parameters<typeof interventionMock.createPush>[0]) =>
    interventionMock.createPush(payload),
}

// ---- 资源中心（真实接口：/api/resources?kind=article|course|notice）----
export const resourceApi = resourceMock

// ---- 系统管理（真实接口：/api/system/org、/users、/roles、/dicts、/audit、/security）----
export const systemApi = systemMock

// ---- 学生花名册（真实接口：/api/students，来自组织架构）----
export const studentApi = {
  list: () => studentMock.list(),
  import: (rows: Parameters<typeof studentMock.import>[0]) => studentMock.import(rows),
}

export type { DemoStudent, RosterImportRow } from './mock'
