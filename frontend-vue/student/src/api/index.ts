import { http, type RequestConfig } from './http'
import type {
  AssessmentResponse,
  AudioStatusResponse,
  ChatRequest,
  ChatResponse,
  CommunicationMessage,
  ConsentResponse,
  CreateSessionResponse,
  EmergencyContact,
  EvaluationRecord,
  FocusSession,
  GrowthResponse,
  HabitRecord,
  HealContent,
  HealingResponse,
  MoodEntry,
  SchoolStage,
  SessionState,
  StartHealingRequest,
  StudentProfile,
  TranscriptionResponse,
  TtsStatusResponse,
  VisionSegmentResponse,
} from './types'

// ---------------- 健康检查 ----------------

export const healthApi = {
  check: () => http.get<{ status: string }>('/api/health').then((r) => r.data),
}

// ---------------- Session ----------------

export const sessionApi = {
  create: (studentRef: string) =>
    http.post<CreateSessionResponse>('/api/session', { student_ref: studentRef }).then((r) => r.data),

  get: (sessionId: string) => http.get<SessionState>(`/api/session/${sessionId}`).then((r) => r.data),

  remove: (sessionId: string) =>
    http.delete<{ status: string }>(`/api/session/${sessionId}`).then((r) => r.data),

  consent: (sessionId: string, granted: boolean, scope: string[] = ['screening', 'result_storage']) =>
    http
      .put<ConsentResponse>(`/api/session/${sessionId}/consent`, {
        session_id: sessionId,
        granted,
        scope,
      })
      .then((r) => r.data),
}

// ---------------- Chat ----------------

export const chatApi = {
  send: (payload: ChatRequest) =>
    http.post<ChatResponse>('/api/chat', payload).then((r) => r.data),
}

// ---------------- Vision ----------------

export const visionApi = {
  /** 开关采集（代次隔离）。注意 extra=forbid，不要多传字段。 */
  capture: (sessionId: string, captureId: string, generation: number, active: boolean) =>
    http
      .post('/api/vision/capture', {
        session_id: sessionId,
        capture_id: active ? captureId : null,
        generation,
        active,
      })
      .then((r) => r.data),

  /** 提交一帧即时分析（不落盘）。带时间的三件套必须同时给。 */
  frame: (
    payload: {
      session_id: string
      image_base64: string
      frame_id?: string
      capture_id?: string
      captured_at_ms?: number
    },
    config?: RequestConfig,
  ) => http.post('/api/vision/frame', payload, config).then((r) => r.data),

  /** 按发言区间聚合冻结快照；聊天复用返回的 vision_snapshot。 */
  segment: (payload: {
    session_id: string
    utterance_id: string
    capture_id: string
    start_ms: number
    end_ms: number
  }) => http.post<VisionSegmentResponse>('/api/vision/segment', payload).then((r) => r.data),
}

// ---------------- Audio ----------------

export const audioApi = {
  status: () => http.get<AudioStatusResponse>('/api/audio/status').then((r) => r.data),

  /** multipart 转写；不要手动设置 Content-Type（boundary 由浏览器补）。 */
  transcribe: (params: {
    file: Blob
    filename: string
    sessionId: string
    utteranceId: string
    captureId?: string
    recordingStartMs: number
    recordingEndMs: number
  }) => {
    const fd = new FormData()
    fd.append('file', params.file, params.filename)
    fd.append('session_id', params.sessionId)
    fd.append('utterance_id', params.utteranceId)
    if (params.captureId) fd.append('capture_id', params.captureId)
    fd.append('recording_start_ms', String(Math.round(params.recordingStartMs)))
    fd.append('recording_end_ms', String(Math.round(params.recordingEndMs)))
    return http.post<TranscriptionResponse>('/api/audio/transcribe', fd).then((r) => r.data)
  },
}

// ---------------- TTS ----------------

export const ttsApi = {
  status: () => http.get<TtsStatusResponse>('/api/tts/status').then((r) => r.data),

  /** 返回 audio/mpeg 二进制；失败抛 ApiError（503 时页面降级浏览器语音）。 */
  synth: (sessionId: string, turnCount: number) =>
    http
      .post('/api/tts', { session_id: sessionId, turn_count: turnCount }, { responseType: 'blob' })
      .then((r) => r.data as Blob),
}

// ---------------- Assessment ----------------

export const assessmentApi = {
  /** 唯一评估入口。 */
  run: (sessionId: string) =>
    http
      .post<AssessmentResponse>('/api/assessment', { session_id: sessionId, evaluation_input: null })
      .then((r) => r.data),

  /** 读结果必须同时给 result_id + session_id。后端返回包裹体，这里解包出 result。 */
  result: (resultId: string, sessionId: string) =>
    http
      .get<AssessmentResponse>(`/api/assessment/result/${resultId}`, { params: { session_id: sessionId } })
      .then((r) => r.data.result),
}

// ---------------- History ----------------

export const historyApi = {
  byStudent: (studentRef: string) =>
    http
      .get<{ student_ref: string; records: EvaluationRecord[]; total: number }>(
        `/api/history/${studentRef}`,
      )
      .then((r) => r.data),
}

// ---------------- Healing（#13 治愈陪伴）-------------------

export const healingApi = {
  /** 需该 session_id 已有评估记录；不要传 age（会 422）。 */
  start: (payload: StartHealingRequest) => {
    const body: StartHealingRequest = {
      session_id: payload.session_id,
      request_id: payload.request_id,
    }
    if (payload.regenerate !== undefined) body.regenerate = payload.regenerate
    if (payload.expected_healing_id) body.expected_healing_id = payload.expected_healing_id
    if (payload.background) body.background = payload.background
    return http.post<HealingResponse>('/api/healing/start', body).then((r) => r.data)
  },

  get: (sessionId: string) =>
    http.get<HealingResponse>(`/api/healing/${sessionId}`).then((r) => r.data),

  chat: (sessionId: string, healingId: string, messageId: string, text: string) =>
    http
      .post<HealingResponse>('/api/healing/chat', {
        session_id: sessionId,
        healing_id: healingId,
        message_id: messageId,
        text,
      })
      .then((r) => r.data),
}

// ---------------- Heal 小工具 ----------------

export const healApi = {
  contents: (mood?: number, tag?: string) =>
    http
      .get<{ contents: HealContent[]; tags: string[] }>('/api/heal/contents', {
        params: { ...(mood ? { mood } : {}), ...(tag ? { tag } : {}) },
      })
      .then((r) => r.data),

  saveMood: (payload: {
    student_ref: string
    date: string
    mood: number
    weather?: string | null
    color?: string | null
    tags?: string[]
    note?: string | null
    voice_text?: string | null
  }) => http.post<{ status: string; entry: MoodEntry }>('/api/heal/mood', payload).then((r) => r.data),

  listMood: (studentRef: string, days = 30) =>
    http
      .get<{ student_ref: string; entries: MoodEntry[] }>('/api/heal/mood', {
        params: { student_ref: studentRef, days },
      })
      .then((r) => r.data),

  saveHabits: (studentRef: string, items: string[], date?: string) =>
    http
      .post<{ status: string; record: HabitRecord; streak: number; total_days: number }>(
        '/api/heal/habits',
        { student_ref: studentRef, date: date ?? null, items },
      )
      .then((r) => r.data),

  listHabits: (studentRef: string, days = 30) =>
    http
      .get<{ student_ref: string; records: HabitRecord[]; streak: number; total_days: number }>(
        '/api/heal/habits',
        { params: { student_ref: studentRef, days } },
      )
      .then((r) => r.data),

  saveFocus: (studentRef: string, minutes: number, moodBefore?: number, moodAfter?: number) =>
    http
      .post<{ status: string; session: FocusSession }>('/api/heal/focus', {
        student_ref: studentRef,
        minutes,
        ...(moodBefore ? { mood_before: moodBefore } : {}),
        ...(moodAfter ? { mood_after: moodAfter } : {}),
      })
      .then((r) => r.data),

  listFocus: (studentRef: string, days = 30) =>
    http
      .get<{ student_ref: string; sessions: FocusSession[]; total_minutes: number }>('/api/heal/focus', {
        params: { student_ref: studentRef, days },
      })
      .then((r) => r.data),

  growth: (studentRef: string, days = 90) =>
    http
      .get<GrowthResponse>('/api/heal/growth', { params: { student_ref: studentRef, days } })
      .then((r) => r.data),
}

// ---------------- Communication（同伴支持 / 留言）-------------------

export const communicationApi = {
  list: (studentRef: string) =>
    http
      .get<{ student_ref: string; messages: CommunicationMessage[] }>(`/api/communication/${studentRef}`)
      .then((r) => r.data),

  send: (payload: {
    student_ref: string
    counselor_ref?: string | null
    direction: 'student_to_counselor' | 'counselor_to_student'
    content: string
  }) =>
    http
      .post<{ status: string; message: CommunicationMessage }>('/api/communication', {
        counselor_ref: null,
        ...payload,
      })
      .then((r) => r.data),
}

// ---------------- 学生档案 / 紧急联系人 ----------------

export const profileApi = {
  get: (studentRef: string) =>
    http.get<StudentProfile>(`/api/profile/${studentRef}`).then((r) => r.data),

  save: (payload: {
    student_ref: string
    nickname: string
    school_stage: SchoolStage | null
    class_name: string
  }) =>
    http
      .put<{ status: string; profile: StudentProfile }>('/api/profile', payload)
      .then((r) => r.data),
}

export const contactApi = {
  list: (studentRef: string) =>
    http
      .get<{ student_ref: string; contacts: EmergencyContact[] }>(`/api/contacts/${studentRef}`)
      .then((r) => r.data),

  add: (payload: { student_ref: string; name: string; relation: string; phone: string }) =>
    http
      .post<{ status: string; contact: EmergencyContact }>('/api/contacts', payload)
      .then((r) => r.data),

  remove: (studentRef: string, contactId: string) =>
    http
      .delete<{ status: string }>(`/api/contacts/${studentRef}/${contactId}`)
      .then((r) => r.data),
}

// ---------------- 咨询预约（与管理端共享同一个接口）-------------------

/** 学生视角的预约（后端 slot='YYYY-MM-DD HH:MM'，这里拆成 date + 原始时段文案）。 */
export interface StudentAppointment {
  id: string
  date: string
  slot: string
  topic: string
  status: 'pending' | 'confirmed' | 'done' | 'cancelled'
  createdAt: number
}

interface RawAppointment {
  id: string
  slot: string
  preferred_label: string | null
  topic: string | null
  status: StudentAppointment['status']
  created_at: string
}

function toStudentAppointment(raw: RawAppointment): StudentAppointment {
  return {
    id: raw.id,
    date: raw.slot.slice(0, 10),
    slot: raw.preferred_label || raw.slot.slice(11),
    topic: raw.topic ?? '',
    status: raw.status,
    createdAt: new Date(raw.created_at).getTime() || Date.now(),
  }
}

export const appointmentApi = {
  /** 仅返回未取消的预约（取消后不再出现在「我的预约」里）。 */
  list: (studentRef: string) =>
    http
      .get<{ appointments: RawAppointment[]; total: number }>('/api/counseling/appointments', {
        params: { student_ref: studentRef },
      })
      .then((r) =>
        r.data.appointments.filter((a) => a.status !== 'cancelled').map(toStudentAppointment),
      ),

  create: (studentRef: string, date: string, slot: string, topic: string) =>
    http
      .post<{ appointment: RawAppointment }>('/api/counseling/appointments', {
        student_ref: studentRef,
        date,
        preferred_label: slot,
        topic: topic || null,
      })
      .then((r) => toStudentAppointment(r.data.appointment)),

  cancel: (appointmentId: string) =>
    http
      .post<{ appointment: RawAppointment }>(
        `/api/counseling/appointments/${appointmentId}/status`,
        { status: 'cancelled' },
      )
      .then((r) => toStudentAppointment(r.data.appointment)),
}

// ---------------- iCBT 完成度（单元内容仍在本地，仅进度上报）-------------------

export const icbtApi = {
  getProgress: (studentRef: string) =>
    http
      .get<{ student_ref: string; completed_units: string[] }>('/api/heal/icbt/progress', {
        params: { student_ref: studentRef },
      })
      .then((r) => r.data.completed_units),

  setProgress: (studentRef: string, completedUnits: string[]) =>
    http
      .post<{ student_ref: string; completed_units: string[] }>('/api/heal/icbt/progress', {
        student_ref: studentRef,
        completed_units: completedUnits,
      })
      .then((r) => r.data.completed_units),
}
