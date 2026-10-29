/**
 * 管理端扩展类型（后端尚未提供对应实体）。
 * 这些类型描述「目标契约」：mock 层按此返回，后端接口就绪后切换实现即可，页面无需改动。
 */
import type { RiskLevel } from '@/types'

export type { RiskLevel }

// ---- 测评任务 ----
export type TaskStatus = 'draft' | 'published' | 'running' | 'finished'
export type ScaleType = 'dialogue' | 'phq9' | 'gad7' | 'phq2' | 'gad2'

export interface AssessmentTask {
  id: string
  title: string
  scale: ScaleType
  /** 目标范围文案，如「初二年级」「初二3班」 */
  targetScope: string
  startAt: string | null
  deadline: string | null
  status: TaskStatus
  anonymous: boolean
  consentRequired: boolean
  /** 应参与人数 */
  total: number
  /** 已提交人数 */
  submitted: number
  creator: string
  createdAt: string
  remark: string
}

export interface TaskParticipant {
  studentRef: string
  name: string
  className: string
  status: 'pending' | 'submitted' | 'expired'
  submittedAt: string | null
  riskLevel: RiskLevel | null
}

// ---- 干预与咨询 ----
export type AppointmentStatus = 'pending' | 'confirmed' | 'done' | 'cancelled'

export interface ConsultAppointment {
  id: string
  studentRef: string
  studentName: string
  className: string
  counselor: string
  slot: string
  duration: number
  room: string
  topic: string
  status: AppointmentStatus
  source: 'student' | 'teacher' | 'warning'
  createdAt: string
}

export type InterviewType = '首次访谈' | '常规访谈' | '危机干预' | '家校沟通'

export interface InterviewRecord {
  id: string
  studentRef: string
  studentName: string
  className: string
  counselor: string
  interviewedAt: string
  type: InterviewType
  summary: string
  nextPlan: string
  confidential: boolean
}

export type ICBTStatus = 'draft' | 'published' | 'offline'

export interface ICBTUnit {
  id: string
  title: string
  module: string
  order: number
  steps: number
  estMinutes: number
  status: ICBTStatus
  audience: string
  assigned: number
  completed: number
  updatedAt: string
}

export type PushStatus = 'queued' | 'sent' | 'read'

export interface PushRecord {
  id: string
  contentTitle: string
  contentType: 'article' | 'course' | 'notice'
  target: string
  targets: number
  channel: '站内' | '短信' | '家校'
  status: PushStatus
  pushedAt: string
  operator: string
}

// ---- 资源中心 ----
export type ResourceKind = 'article' | 'course' | 'notice'
export type ResourceStatus = 'draft' | 'published' | 'offline'

export interface ResourceItem {
  id: string
  kind: ResourceKind
  title: string
  category: string
  summary: string
  tags: string[]
  status: ResourceStatus
  author: string
  views: number
  updatedAt: string
}

// ---- 系统管理 ----
export interface OrgNode {
  id: string
  name: string
  type: 'school' | 'grade' | 'class'
  parentId: string | null
  studentCount: number
  headteacher?: string
}

export interface SysUser {
  id: string
  name: string
  account: string
  roleKey: string
  roleName: string
  scope: string
  phone: string
  status: 'active' | 'disabled'
  lastLogin: string | null
}

export interface PermissionRow {
  module: string
  admin: boolean
  psych: boolean
  headteacher: boolean
  manager: boolean
}

export interface DictItem {
  id: string
  code: string
  label: string
  value: string
  sort: number
  enabled: boolean
  remark: string
}

export interface AuditLog {
  id: string
  operator: string
  roleName: string
  action: string
  target: string
  ip: string
  result: 'success' | 'fail'
  createdAt: string
}

export interface SecurityPolicy {
  watermark: boolean
  passwordMinLength: number
  passwordComplexity: boolean
  loginFailLimit: number
  sessionTimeout: number
  exportConfirm: boolean
  ipWhitelist: string
}
