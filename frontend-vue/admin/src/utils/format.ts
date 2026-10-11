import dayjs from 'dayjs'
import type { FollowUpStatus, OverallLevel, PsychologicalProfile, RiskLevel } from '@/types'
import type {
  AppointmentStatus,
  ConsultAppointment,
  ICBTStatus,
  PushStatus,
  ResourceKind,
  ResourceStatus,
  ScaleType,
  TaskParticipant,
  TaskStatus,
} from '@/types/admin'

export const fmtTime = (v: string | null | undefined, pattern = 'YYYY-MM-DD HH:mm') =>
  v ? dayjs(v).format(pattern) : '—'

export const RISK_MAP: Record<RiskLevel, { text: string; type: 'success' | 'warning' | 'danger' }> = {
  low: { text: '低风险', type: 'success' },
  medium: { text: '中风险', type: 'warning' },
  high: { text: '高风险', type: 'danger' },
}

export const FOLLOW_UP_MAP: Record<FollowUpStatus, { text: string; type: 'info' | 'warning' | 'primary' | 'success' }> = {
  none: { text: '无需跟进', type: 'info' },
  pending: { text: '待认领', type: 'warning' },
  in_progress: { text: '跟进中', type: 'primary' },
  resolved: { text: '已结案', type: 'success' },
}

export const OVERALL_LEVEL_MAP: Record<OverallLevel, { text: string; type: 'success' | 'primary' | 'warning' | 'danger' }> = {
  low_concern: { text: '低关注', type: 'success' },
  mild_concern: { text: '轻度关注', type: 'primary' },
  moderate_concern: { text: '中度关注', type: 'warning' },
  high_concern: { text: '高度关注', type: 'danger' },
}

export const DIMENSION_MAP: Record<keyof PsychologicalProfile, string> = {
  emotion: '情绪状态',
  interest_motivation: '兴趣与动力',
  sleep_energy: '睡眠与精力',
  attention_thinking: '专注与思考',
  social_daily: '社交与日常',
}

export const TREND_MAP: Record<string, string> = {
  improving: '好转中',
  stable: '稳定',
  fluctuating: '波动',
  worsening: '加重',
  unclear: '不明朗',
}

export const CONSISTENCY_MAP: Record<string, string> = {
  low: '低一致',
  moderate: '中等一致',
  high: '高度一致',
  unknown: '暂无数据',
}

// ---- 管理端扩展模块（任务 / 预约 / iCBT / 资源）标签 ----
type TagType = 'success' | 'warning' | 'danger' | 'primary' | 'info'

export const SCALE_MAP: Record<ScaleType, string> = {
  dialogue: '对话式测评',
  phq9: 'PHQ-9 抑郁量表',
  gad7: 'GAD-7 焦虑量表',
  phq2: 'PHQ-2 快速筛查',
  gad2: 'GAD-2 快速筛查',
}

export const TASK_STATUS_MAP: Record<TaskStatus, { text: string; type: TagType }> = {
  draft: { text: '草稿', type: 'info' },
  published: { text: '已发布', type: 'primary' },
  running: { text: '进行中', type: 'warning' },
  finished: { text: '已完成', type: 'success' },
}

export const PARTICIPANT_MAP: Record<TaskParticipant['status'], { text: string; type: TagType }> = {
  pending: { text: '未提交', type: 'info' },
  submitted: { text: '已提交', type: 'success' },
  expired: { text: '已过期', type: 'warning' },
}

export const APPOINTMENT_MAP: Record<AppointmentStatus, { text: string; type: TagType }> = {
  pending: { text: '待确认', type: 'warning' },
  confirmed: { text: '已确认', type: 'primary' },
  done: { text: '已完成', type: 'success' },
  cancelled: { text: '已取消', type: 'info' },
}

export const APPOINTMENT_SOURCE_MAP: Record<ConsultAppointment['source'], string> = {
  student: '学生预约',
  teacher: '教师发起',
  warning: '预警转介',
}

export const ICBT_STATUS_MAP: Record<ICBTStatus, { text: string; type: TagType }> = {
  draft: { text: '草稿', type: 'info' },
  published: { text: '已发布', type: 'success' },
  offline: { text: '已下线', type: 'warning' },
}

export const PUSH_STATUS_MAP: Record<PushStatus, { text: string; type: TagType }> = {
  queued: { text: '待发送', type: 'info' },
  sent: { text: '已发送', type: 'primary' },
  read: { text: '已读', type: 'success' },
}

export const RESOURCE_KIND_MAP: Record<ResourceKind, string> = {
  article: '科普文章',
  course: '课程资源',
  notice: '通知公告',
}

export const RESOURCE_STATUS_MAP: Record<ResourceStatus, { text: string; type: TagType }> = {
  draft: { text: '草稿', type: 'info' },
  published: { text: '已发布', type: 'success' },
  offline: { text: '已下线', type: 'warning' },
}
