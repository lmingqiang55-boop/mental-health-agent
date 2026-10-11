/**
 * 演示数据层（mock）。
 *
 * 目的：4 个占位模块（测评任务 / 干预与咨询 / 资源中心 / 系统管理）后端尚未提供接口，
 * 先用本文件打底把前端交互做完整。页面只依赖 `@/api` 导出的 *Api，不直接引用本文件，
 * 因此后端接口就绪时只需替换 `@/api/index.ts` 中的实现，页面零改动。
 *
 * 每个 mock 方法都标注了「真实接口」路径，便于后端对齐。
 */
import type {
  AppointmentStatus,
  AssessmentTask,
  AuditLog,
  ConsultAppointment,
  DictItem,
  ICBTUnit,
  InterviewRecord,
  OrgNode,
  PermissionRow,
  PushRecord,
  ResourceItem,
  ResourceKind,
  SecurityPolicy,
  SysUser,
  TaskParticipant,
  TaskStatus,
} from '@/types/admin'

export const delay = (ms = 220) => new Promise((r) => setTimeout(r, ms))

// ---------- 演示学生池 ----------
const SURNAMES = ['王', '李', '张', '刘', '陈', '杨', '赵', '黄', '周', '吴', '徐', '孙']
const GIVEN = ['子墨', '欣怡', '浩然', '思远', '雨桐', '梓涵', '宇轩', '若汐', '嘉懿', '芷若', '天佑', '诗琪']
const CLASSES = ['初一1班', '初一2班', '初二1班', '初二3班', '初三1班', '初三4班', '高一2班', '高二5班']
export const GRADE_NAMES = ['初一', '初二', '初三', '高一', '高二']

export interface DemoStudent {
  ref: string
  name: string
  className: string
  grade: string
}

export const DEMO_STUDENTS: DemoStudent[] = Array.from({ length: 24 }, (_, i) => {
  const className = CLASSES[i % CLASSES.length]
  return {
    ref: `stu-${String(i + 1).padStart(4, '0')}`,
    name: SURNAMES[i % SURNAMES.length] + GIVEN[(i * 5) % GIVEN.length],
    className,
    grade: className.slice(0, 2),
  }
})

export const CLASS_NAMES = CLASSES
export const findStudent = (ref: string) => DEMO_STUDENTS.find((s) => s.ref === ref)

/** 花名册批量导入行：姓名,学号,班级（年级由班级前两位推导） */
export interface RosterImportRow {
  ref: string
  name: string
  className: string
}

export const studentMock = {
  list: async (): Promise<DemoStudent[]> => {
    await delay()
    return DEMO_STUDENTS.map((s) => ({ ...s }))
  },
  import: async (rows: RosterImportRow[]): Promise<{ added: number; skipped: number }> => {
    await delay()
    let added = 0
    let skipped = 0
    for (const r of rows) {
      const ref = r.ref.trim()
      const name = r.name.trim()
      const className = r.className.trim()
      if (!ref || !name || !className || DEMO_STUDENTS.some((s) => s.ref === ref)) {
        skipped++
        continue
      }
      DEMO_STUDENTS.push({ ref, name, className, grade: className.slice(0, 2) })
      added++
    }
    return { added, skipped }
  },
}

const RISK_CYCLE: TaskParticipant['riskLevel'][] = ['low', 'low', 'medium', 'low', 'high']

// ================= 测评任务 =================
let TASKS: AssessmentTask[] = [
  {
    id: 'task-1001',
    title: '2026 秋季新生心理健康普测',
    scale: 'phq9',
    targetScope: '初一年级（2 个班）',
    startAt: '2026-09-28 08:00',
    deadline: '2026-10-20 23:59',
    status: 'running',
    anonymous: false,
    consentRequired: true,
    total: 24,
    submitted: 18,
    creator: '心理中心',
    createdAt: '2026-09-25 10:12',
    remark: '入学适应期基线测评，含第 9 题阳性自动随访',
  },
  {
    id: 'task-1002',
    title: '初二期中考前压力筛查',
    scale: 'gad7',
    targetScope: '初二1班',
    startAt: '2026-10-08 08:00',
    deadline: '2026-10-18 23:59',
    status: 'running',
    anonymous: true,
    consentRequired: false,
    total: 8,
    submitted: 5,
    creator: '李老师',
    createdAt: '2026-10-06 15:40',
    remark: '匿名测评，仅输出班级聚合结果',
  },
  {
    id: 'task-1003',
    title: '初三毕业班抑郁复评',
    scale: 'phq9',
    targetScope: '初三1班、初三4班',
    startAt: '2026-10-01 08:00',
    deadline: '2026-10-15 23:59',
    status: 'running',
    anonymous: false,
    consentRequired: true,
    total: 16,
    submitted: 11,
    creator: '心理中心',
    createdAt: '2026-09-29 09:05',
    remark: '对上一轮中高风险学生开展复评',
  },
  {
    id: 'task-1004',
    title: '高一日常情绪状态普测',
    scale: 'dialogue',
    targetScope: '高一2班',
    startAt: '2026-09-20 08:00',
    deadline: '2026-09-30 23:59',
    status: 'finished',
    anonymous: false,
    consentRequired: true,
    total: 8,
    submitted: 8,
    creator: '李老师',
    createdAt: '2026-09-18 14:20',
    remark: '对话式测评，已全部完成并生成报告',
  },
  {
    id: 'task-1005',
    title: '高二情绪快速筛查（PHQ-2）',
    scale: 'phq2',
    targetScope: '高二5班',
    startAt: null,
    deadline: '2026-10-25 23:59',
    status: 'published',
    anonymous: false,
    consentRequired: false,
    total: 8,
    submitted: 0,
    creator: '心理中心',
    createdAt: '2026-10-09 11:30',
    remark: '两步法初筛，阳性者自动转入 PHQ-9 复评',
  },
  {
    id: 'task-1006',
    title: '全校教师心理健康自查（草稿）',
    scale: 'gad2',
    targetScope: '全体教师',
    startAt: null,
    deadline: null,
    status: 'draft',
    anonymous: true,
    consentRequired: false,
    total: 0,
    submitted: 0,
    creator: '张管理员',
    createdAt: '2026-10-10 09:00',
    remark: '面向教职工的匿名自查，待确认量表后发布',
  },
]

export function mockParticipants(task: AssessmentTask): TaskParticipant[] {
  const n = Math.min(task.total || DEMO_STUDENTS.length, DEMO_STUDENTS.length)
  const ratio = task.total ? task.submitted / task.total : 0
  const submittedCount = Math.round(n * ratio)
  return DEMO_STUDENTS.slice(0, n).map((s, i) => {
    const done = i < submittedCount
    return {
      studentRef: s.ref,
      name: s.name,
      className: s.className,
      status: done ? 'submitted' : 'pending',
      submittedAt: done ? `2026-10-0${(i % 9) + 1} 1${i % 9}:${String((i * 7) % 60).padStart(2, '0')}` : null,
      riskLevel: done ? RISK_CYCLE[i % RISK_CYCLE.length] : null,
    }
  })
}

let SEQ = 2000
const nextId = (prefix: string) => `${prefix}-${++SEQ}`

export const taskMock = {
  list: async (): Promise<{ items: AssessmentTask[]; total: number }> => {
    await delay()
    return { items: TASKS.map((t) => ({ ...t })), total: TASKS.length }
  },
  get: async (id: string): Promise<AssessmentTask> => {
    await delay()
    const t = TASKS.find((x) => x.id === id)
    if (!t) throw new Error('任务不存在')
    return { ...t }
  },
  create: async (payload: Omit<AssessmentTask, 'id' | 'createdAt' | 'submitted'>): Promise<AssessmentTask> => {
    await delay()
    const task: AssessmentTask = {
      ...payload,
      id: nextId('task'),
      submitted: 0,
      createdAt: new Date().toISOString().slice(0, 16).replace('T', ' '),
    }
    TASKS = [task, ...TASKS]
    return { ...task }
  },
  update: async (id: string, patch: Partial<AssessmentTask>): Promise<AssessmentTask> => {
    await delay()
    const idx = TASKS.findIndex((x) => x.id === id)
    if (idx < 0) throw new Error('任务不存在')
    TASKS[idx] = { ...TASKS[idx], ...patch, id }
    return { ...TASKS[idx] }
  },
  setStatus: async (id: string, status: TaskStatus): Promise<AssessmentTask> => {
    return taskMock.update(id, { status })
  },
  remove: async (id: string): Promise<void> => {
    await delay()
    TASKS = TASKS.filter((x) => x.id !== id)
  },
  participants: async (id: string): Promise<TaskParticipant[]> => {
    await delay()
    const t = TASKS.find((x) => x.id === id)
    if (!t) throw new Error('任务不存在')
    return mockParticipants(t)
  },
}

// ================= 干预与咨询 =================
let APPOINTMENTS: ConsultAppointment[] = [
  { id: 'ap-01', studentRef: 'stu-0003', studentName: '张浩然', className: '初二1班', counselor: '李老师', slot: '2026-10-11 14:00', duration: 50, room: '心理咨询室 A', topic: '考前端焦虑', status: 'confirmed', source: 'student', createdAt: '2026-10-09 16:20' },
  { id: 'ap-02', studentRef: 'stu-0010', studentName: '黄芷若', className: '初二3班', counselor: '李老师', slot: '2026-10-11 15:10', duration: 50, room: '心理咨询室 A', topic: '人际困扰', status: 'pending', source: 'warning', createdAt: '2026-10-10 08:40' },
  { id: 'ap-03', studentRef: 'stu-0005', studentName: '陈雨桐', className: '初三1班', counselor: '王老师', slot: '2026-10-12 09:00', duration: 60, room: '心理咨询室 B', topic: '情绪低落随访', status: 'confirmed', source: 'teacher', createdAt: '2026-10-08 11:05' },
  { id: 'ap-04', studentRef: 'stu-0008', studentName: '周宇轩', className: '初一2班', counselor: '李老师', slot: '2026-10-09 14:00', duration: 50, room: '心理咨询室 A', topic: '入学适应', status: 'done', source: 'student', createdAt: '2026-10-07 10:15' },
  { id: 'ap-05', studentRef: 'stu-0015', studentName: '孙诗琪', className: '高一2班', counselor: '王老师', slot: '2026-10-10 16:00', duration: 50, room: '心理咨询室 B', topic: '睡眠问题', status: 'cancelled', source: 'student', createdAt: '2026-10-09 09:30' },
]

let INTERVIEWS: InterviewRecord[] = [
  { id: 'iv-01', studentRef: 'stu-0003', studentName: '张浩然', className: '初二1班', counselor: '李老师', interviewedAt: '2026-10-09 14:00', type: '首次访谈', summary: '自诉近两周因期中考试出现入睡困难、注意力下降，情绪波动明显，无自伤意念。', nextPlan: '安排每周一次访谈，配合放松训练与考前时间管理指导。', confidential: false },
  { id: 'iv-02', studentRef: 'stu-0005', studentName: '陈雨桐', className: '初三1班', counselor: '王老师', interviewedAt: '2026-10-08 09:30', type: '危机干预', summary: 'PHQ-9 第 9 题阳性，自述偶有「活着没意思」的想法，无具体计划，社会支持尚可。', nextPlan: '启动高危随访流程，24h 内联系班主任与家长，一周内复评。', confidential: true },
  { id: 'iv-03', studentRef: 'stu-0010', studentName: '黄芷若', className: '初二3班', counselor: '李老师', interviewedAt: '2026-10-07 15:20', type: '常规访谈', summary: '与同伴关系紧张，担心被孤立，情绪以委屈、愤怒为主，睡眠可。', nextPlan: '开展人际沟通技巧练习，2 周后回访。', confidential: false },
  { id: 'iv-04', studentRef: 'stu-0018', studentName: '高嘉懿', className: '高二5班', counselor: '王老师', interviewedAt: '2026-09-30 10:00', type: '家校沟通', summary: '与家长沟通成绩下滑与亲子冲突情况，家长配合意愿良好。', nextPlan: '建立家校联系本，两周一次线上反馈。', confidential: true },
]

let ICBT_UNITS: ICBTUnit[] = [
  { id: 'icbt-01', title: '认识情绪：情绪 ABC 模型', module: '情绪管理', order: 1, steps: 4, estMinutes: 25, status: 'published', audience: '全校学生', assigned: 320, completed: 268, updatedAt: '2026-09-26 10:00' },
  { id: 'icbt-02', title: '放松训练：腹式呼吸与渐进式肌肉放松', module: '焦虑应对', order: 2, steps: 3, estMinutes: 20, status: 'published', audience: '初二年级', assigned: 160, completed: 121, updatedAt: '2026-09-28 14:30' },
  { id: 'icbt-03', title: '睡眠改善：刺激控制法', module: '睡眠管理', order: 3, steps: 5, estMinutes: 30, status: 'published', audience: '高风险学生', assigned: 42, completed: 19, updatedAt: '2026-10-02 09:20' },
  { id: 'icbt-04', title: '拖延与任务分解', module: '时间管理', order: 4, steps: 4, estMinutes: 25, status: 'draft', audience: '初三毕业班', assigned: 0, completed: 0, updatedAt: '2026-10-08 16:45' },
  { id: 'icbt-05', title: '人际冲突的非暴力沟通', module: '人际交往', order: 5, steps: 4, estMinutes: 28, status: 'offline', audience: '全校学生', assigned: 150, completed: 96, updatedAt: '2026-08-20 11:10' },
]

let PUSHES: PushRecord[] = [
  { id: 'ps-01', contentTitle: '考前心理调适指南', contentType: 'article', target: '初二年级', targets: 160, channel: '站内', status: 'read', pushedAt: '2026-10-06 09:00', operator: '李老师' },
  { id: 'ps-02', contentTitle: '放松训练音频（腹式呼吸）', contentType: 'course', target: '高风险学生', targets: 42, channel: '站内', status: 'sent', pushedAt: '2026-10-08 15:30', operator: '王老师' },
  { id: 'ps-03', contentTitle: '关于期中考后心理关怀的通知', contentType: 'notice', target: '全校学生', targets: 320, channel: '家校', status: 'queued', pushedAt: '2026-10-10 08:00', operator: '心理中心' },
]

export const interventionMock = {
  appointments: async (): Promise<ConsultAppointment[]> => {
    await delay()
    return APPOINTMENTS.map((a) => ({ ...a }))
  },
  createAppointment: async (payload: Omit<ConsultAppointment, 'id' | 'createdAt'>): Promise<ConsultAppointment> => {
    await delay()
    const item: ConsultAppointment = {
      ...payload,
      id: nextId('ap'),
      createdAt: new Date().toISOString().slice(0, 16).replace('T', ' '),
    }
    APPOINTMENTS = [item, ...APPOINTMENTS]
    return { ...item }
  },
  setAppointmentStatus: async (id: string, status: AppointmentStatus): Promise<void> => {
    await delay()
    const a = APPOINTMENTS.find((x) => x.id === id)
    if (a) a.status = status
  },
  interviews: async (): Promise<InterviewRecord[]> => {
    await delay()
    return INTERVIEWS.map((i) => ({ ...i }))
  },
  createInterview: async (payload: Omit<InterviewRecord, 'id'>): Promise<InterviewRecord> => {
    await delay()
    const item: InterviewRecord = { ...payload, id: nextId('iv') }
    INTERVIEWS = [item, ...INTERVIEWS]
    return { ...item }
  },
  icbtUnits: async (): Promise<ICBTUnit[]> => {
    await delay()
    return ICBT_UNITS.map((u) => ({ ...u })).sort((a, b) => a.order - b.order)
  },
  updateICBTUnit: async (id: string, patch: Partial<ICBTUnit>): Promise<void> => {
    await delay()
    const idx = ICBT_UNITS.findIndex((x) => x.id === id)
    if (idx >= 0) ICBT_UNITS[idx] = { ...ICBT_UNITS[idx], ...patch, id, updatedAt: new Date().toISOString().slice(0, 16).replace('T', ' ') }
  },
  pushes: async (): Promise<PushRecord[]> => {
    await delay()
    return PUSHES.map((p) => ({ ...p }))
  },
  createPush: async (payload: Omit<PushRecord, 'id' | 'pushedAt'>): Promise<PushRecord> => {
    await delay()
    const item: PushRecord = {
      ...payload,
      id: nextId('ps'),
      pushedAt: new Date().toISOString().slice(0, 16).replace('T', ' '),
    }
    PUSHES = [item, ...PUSHES]
    return { ...item }
  },
}

// ================= 资源中心 =================
let RESOURCES: ResourceItem[] = [
  { id: 're-01', kind: 'article', title: '考前心理调适指南：给初三学生的 6 条建议', category: '考试心理', summary: '从作息、复习节奏、情绪调节三方面给出可操作建议。', tags: ['考试', '焦虑'], status: 'published', author: '李老师', views: 862, updatedAt: '2026-10-06 09:00' },
  { id: 're-02', kind: 'article', title: '如何识别孩子的情绪信号——写给家长', category: '家庭教育', summary: '帮助家长看懂青少年的情绪表达方式与求助信号。', tags: ['家长', '沟通'], status: 'published', author: '心理中心', views: 1204, updatedAt: '2026-09-30 10:20' },
  { id: 're-03', kind: 'article', title: '睡眠与情绪：青少年睡眠卫生科普', category: '健康生活', summary: '睡眠不足如何影响情绪与学习，以及改善方法。', tags: ['睡眠'], status: 'draft', author: '王老师', views: 0, updatedAt: '2026-10-09 16:00' },
  { id: 're-04', kind: 'course', title: '放松训练音频合辑（腹式呼吸 / 渐进式肌肉放松）', category: '放松训练', summary: '共 4 段引导音频，适合课间与睡前使用。', tags: ['音频', '放松'], status: 'published', author: '心理中心', views: 573, updatedAt: '2026-10-08 15:30' },
  { id: 're-05', kind: 'course', title: '情绪管理微课：认识你的情绪', category: '情绪管理', summary: '20 分钟微课，配套 iCBT 单元一。', tags: ['微课'], status: 'published', author: '李老师', views: 431, updatedAt: '2026-09-26 10:00' },
  { id: 're-06', kind: 'course', title: '人际沟通技巧训练（小组课）', category: '人际交往', summary: '适用于小团辅，含教师指导手册。', tags: ['团辅'], status: 'offline', author: '王老师', views: 210, updatedAt: '2026-08-20 11:10' },
  { id: 're-07', kind: 'notice', title: '关于期中考后开展心理关怀工作的通知', category: '工作通知', summary: '面向全校班主任，明确考后一周关怀重点与上报流程。', tags: ['通知', '班主任'], status: 'published', author: '心理中心', views: 96, updatedAt: '2026-10-10 08:00' },
  { id: 're-08', kind: 'notice', title: '心理咨询室开放时间调整公告', category: '服务公告', summary: '10 月起咨询室延时开放至 18:30，支持线上预约。', tags: ['公告'], status: 'published', author: '心理中心', views: 342, updatedAt: '2026-09-29 09:00' },
  { id: 're-09', kind: 'notice', title: '心理健康月活动方案（草稿）', category: '活动通知', summary: '待定稿，含讲座、团辅、展板三部分。', tags: ['活动'], status: 'draft', author: '张管理员', views: 0, updatedAt: '2026-10-10 09:10' },
]

export const resourceMock = {
  list: async (kind?: ResourceKind): Promise<ResourceItem[]> => {
    await delay()
    const items = kind ? RESOURCES.filter((r) => r.kind === kind) : RESOURCES
    return items.map((r) => ({ ...r }))
  },
  create: async (payload: Omit<ResourceItem, 'id' | 'views' | 'updatedAt'>): Promise<ResourceItem> => {
    await delay()
    const item: ResourceItem = {
      ...payload,
      id: nextId('re'),
      views: 0,
      updatedAt: new Date().toISOString().slice(0, 16).replace('T', ' '),
    }
    RESOURCES = [item, ...RESOURCES]
    return { ...item }
  },
  setStatus: async (id: string, status: ResourceItem['status']): Promise<void> => {
    await delay()
    const r = RESOURCES.find((x) => x.id === id)
    if (r) {
      r.status = status
      r.updatedAt = new Date().toISOString().slice(0, 16).replace('T', ' ')
    }
  },
  remove: async (id: string): Promise<void> => {
    await delay()
    RESOURCES = RESOURCES.filter((x) => x.id !== id)
  },
}

// ================= 系统管理 =================
const ORG_TREE: OrgNode[] = [
  { id: 'org-school', name: '心晴实验中学', type: 'school', parentId: null, studentCount: 24 },
  { id: 'org-g1', name: '初一年级', type: 'grade', parentId: 'org-school', studentCount: 6 },
  { id: 'org-g1c1', name: '初一1班', type: 'class', parentId: 'org-g1', studentCount: 3, headteacher: '刘老师' },
  { id: 'org-g1c2', name: '初一2班', type: 'class', parentId: 'org-g1', studentCount: 3, headteacher: '陈老师' },
  { id: 'org-g2', name: '初二年级', type: 'grade', parentId: 'org-school', studentCount: 6 },
  { id: 'org-g2c1', name: '初二1班', type: 'class', parentId: 'org-g2', studentCount: 3, headteacher: '赵老师' },
  { id: 'org-g2c3', name: '初二3班', type: 'class', parentId: 'org-g2', studentCount: 3, headteacher: '孙老师' },
  { id: 'org-g3', name: '初三年级', type: 'grade', parentId: 'org-school', studentCount: 6 },
  { id: 'org-g3c1', name: '初三1班', type: 'class', parentId: 'org-g3', studentCount: 3, headteacher: '周老师' },
  { id: 'org-g3c4', name: '初三4班', type: 'class', parentId: 'org-g3', studentCount: 3, headteacher: '吴老师' },
  { id: 'org-g4', name: '高一年级', type: 'grade', parentId: 'org-school', studentCount: 3 },
  { id: 'org-g4c2', name: '高一2班', type: 'class', parentId: 'org-g4', studentCount: 3, headteacher: '郑老师' },
  { id: 'org-g5', name: '高二年级', type: 'grade', parentId: 'org-school', studentCount: 3 },
  { id: 'org-g5c5', name: '高二5班', type: 'class', parentId: 'org-g5', studentCount: 3, headteacher: '冯老师' },
]

let USERS: SysUser[] = [
  { id: 'u-01', name: '张管理员', account: 'admin', roleKey: 'admin', roleName: '系统管理员', scope: '全校', phone: '138****0001', status: 'active', lastLogin: '2026-10-10 08:32' },
  { id: 'u-02', name: '李老师', account: 'psych01', roleKey: 'psych', roleName: '心理教师', scope: '全校学生', phone: '138****0002', status: 'active', lastLogin: '2026-10-10 09:05' },
  { id: 'u-03', name: '王老师', account: 'psych02', roleKey: 'psych', roleName: '心理教师', scope: '全校学生', phone: '138****0003', status: 'active', lastLogin: '2026-10-09 17:41' },
  { id: 'u-04', name: '孙老师', account: 'head0203', roleKey: 'headteacher', roleName: '班主任', scope: '初二3班', phone: '138****0004', status: 'active', lastLogin: '2026-10-10 07:58' },
  { id: 'u-05', name: '周老师', account: 'head0301', roleKey: 'headteacher', roleName: '班主任', scope: '初三1班', phone: '138****0005', status: 'active', lastLogin: '2026-10-08 18:20' },
  { id: 'u-06', name: '校长办公室', account: 'manager01', roleKey: 'manager', roleName: '管理层', scope: '全校 / 年级', phone: '138****0006', status: 'active', lastLogin: '2026-10-09 10:12' },
  { id: 'u-07', name: '陈老师', account: 'head0102', roleKey: 'headteacher', roleName: '班主任', scope: '初一2班', phone: '138****0007', status: 'disabled', lastLogin: '2026-09-15 16:03' },
]

const PERMISSIONS: PermissionRow[] = [
  { module: '工作台', admin: true, psych: true, headteacher: true, manager: true },
  { module: '预警管理', admin: true, psych: true, headteacher: true, manager: true },
  { module: '学生心理档案', admin: false, psych: true, headteacher: true, manager: false },
  { module: '测评任务', admin: false, psych: true, headteacher: false, manager: false },
  { module: '测评结果', admin: true, psych: true, headteacher: true, manager: true },
  { module: '干预与咨询', admin: false, psych: true, headteacher: false, manager: false },
  { module: '资源中心', admin: false, psych: true, headteacher: true, manager: false },
  { module: '统计报表', admin: false, psych: true, headteacher: false, manager: true },
  { module: '系统管理', admin: true, psych: false, headteacher: false, manager: false },
]

let DICTS: DictItem[] = [
  { id: 'd-01', code: 'risk_level', label: '低风险', value: 'low', sort: 1, enabled: true, remark: '预警分级' },
  { id: 'd-02', code: 'risk_level', label: '中风险', value: 'medium', sort: 2, enabled: true, remark: '预警分级' },
  { id: 'd-03', code: 'risk_level', label: '高风险', value: 'high', sort: 3, enabled: true, remark: '预警分级' },
  { id: 'd-04', code: 'scale_type', label: '对话式测评', value: 'dialogue', sort: 1, enabled: true, remark: '测评量表' },
  { id: 'd-05', code: 'scale_type', label: 'PHQ-9 抑郁量表', value: 'phq9', sort: 2, enabled: true, remark: '测评量表' },
  { id: 'd-06', code: 'scale_type', label: 'GAD-7 焦虑量表', value: 'gad7', sort: 3, enabled: true, remark: '测评量表' },
  { id: 'd-07', code: 'follow_up', label: '待认领', value: 'pending', sort: 1, enabled: true, remark: '跟进状态' },
  { id: 'd-08', code: 'follow_up', label: '跟进中', value: 'in_progress', sort: 2, enabled: true, remark: '跟进状态' },
  { id: 'd-09', code: 'follow_up', label: '已结案', value: 'resolved', sort: 3, enabled: true, remark: '跟进状态' },
]

const AUDIT_LOGS: AuditLog[] = [
  { id: 'log-01', operator: '李老师', roleName: '心理教师', action: '查看报告', target: 'stu-0005 / 危机干预复评', ip: '10.12.30.21', result: 'success', createdAt: '2026-10-10 09:12' },
  { id: 'log-02', operator: '李老师', roleName: '心理教师', action: '处置预警', target: '预警 #W-20261008-003', ip: '10.12.30.21', result: 'success', createdAt: '2026-10-10 09:05' },
  { id: 'log-03', operator: '张管理员', roleName: '系统管理员', action: '导出数据', target: '初三1班测评结果', ip: '10.12.30.6', result: 'success', createdAt: '2026-10-09 17:48' },
  { id: 'log-04', operator: '周老师', roleName: '班主任', action: '登录', target: '管理端', ip: '10.12.31.88', result: 'fail', createdAt: '2026-10-09 17:40' },
  { id: 'log-05', operator: '张管理员', roleName: '系统管理员', action: '修改权限', target: '角色：班主任', ip: '10.12.30.6', result: 'success', createdAt: '2026-10-09 15:20' },
  { id: 'log-06', operator: '王老师', roleName: '心理教师', action: '新建访谈记录', target: 'stu-0018 / 家校沟通', ip: '10.12.30.33', result: 'success', createdAt: '2026-10-09 10:02' },
]

let SECURITY: SecurityPolicy = {
  watermark: true,
  passwordMinLength: 8,
  passwordComplexity: true,
  loginFailLimit: 5,
  sessionTimeout: 30,
  exportConfirm: true,
  ipWhitelist: '10.12.0.0/16',
}

export const systemMock = {
  orgTree: async (): Promise<OrgNode[]> => {
    await delay()
    return ORG_TREE.map((n) => ({ ...n }))
  },
  users: async (): Promise<SysUser[]> => {
    await delay()
    return USERS.map((u) => ({ ...u }))
  },
  setUserStatus: async (id: string, status: SysUser['status']): Promise<void> => {
    await delay()
    const u = USERS.find((x) => x.id === id)
    if (u) u.status = status
  },
  permissions: async (): Promise<PermissionRow[]> => {
    await delay()
    return PERMISSIONS.map((p) => ({ ...p }))
  },
  savePermissions: async (rows: PermissionRow[]): Promise<void> => {
    await delay()
    PERMISSIONS.splice(0, PERMISSIONS.length, ...rows.map((r) => ({ ...r })))
  },
  dicts: async (): Promise<DictItem[]> => {
    await delay()
    return DICTS.map((d) => ({ ...d }))
  },
  setDictEnabled: async (id: string, enabled: boolean): Promise<void> => {
    await delay()
    const d = DICTS.find((x) => x.id === id)
    if (d) d.enabled = enabled
  },
  auditLogs: async (): Promise<AuditLog[]> => {
    await delay()
    return AUDIT_LOGS.map((l) => ({ ...l }))
  },
  getSecurity: async (): Promise<SecurityPolicy> => {
    await delay()
    return { ...SECURITY }
  },
  saveSecurity: async (policy: SecurityPolicy): Promise<void> => {
    await delay()
    SECURITY = { ...policy }
  },
}
