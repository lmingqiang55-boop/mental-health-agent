/**
 * 后端契约类型（严格对齐 新前端/docs/新前端接入说明.md §5 / §4）。
 * 后端返回裸 JSON；错误为 { error: { code, message } }。
 */

// ---------------- 通用 ----------------

export interface ApiErrorShape {
  code: string
  message: string
  status: number
}

export type RiskLevel = 'low' | 'medium' | 'high'
export type Stage =
  | 'exploration'
  | 'safety_review'
  | 'safety_stop'
  | 'assessment_ready'
  | 'assessment'
  | 'completed'

export interface RiskResult {
  risk_level: RiskLevel
  risk_score: number
  risk_reasons: string[]
  risk_types: string[]
  key_evidence: string[]
  requires_intervention: boolean
}

// ---------------- 心理安全（新版 Safety，系统唯一安全状态来源） ----------------

export type SafetyLevel = 'normal' | 'uncertain' | 'high' | 'imminent'
export type SafetyRoute = 'continue' | 'safety_review' | 'safety_stop'
export type SafetyModelStatus = 'ok' | 'timeout' | 'parse_error' | 'unavailable'
/** none：普通评估；review：安全澄清中；stopped：安全支持中（会话内不会自动解除）。 */
export type SafetyStage = 'none' | 'review' | 'stopped'

/** 危险表达关键词线索。仅作线索，不决定风险等级。 */
export interface SafetySignal {
  term: string
  negated: boolean
  source: 'latest_message' | 'history'
}

export interface SafetyVerdict {
  risk_detected: boolean
  risk_level: SafetyLevel
  /** 路由由等级在后端派生，前端不应自行推导。 */
  route: SafetyRoute
  /** 面向用户的消息（≤3 条）。号码不在这里，见 hotline_numbers。 */
  messages: string[]
  /** 已核实的热线号码；仅在 route 为 safety_stop 时非空。 */
  hotline_numbers: string[]
  model_status: SafetyModelStatus
  keyword_signals: SafetySignal[]
  rationale: string | null
  evidence_quotes: string[]
  engine: string
}

export interface VisionState {
  emotion?: string | null
  emotion_confidence?: number | null
  valence?: number | null
  arousal?: number | null
  engagement?: number | null
  attention_score?: number | null
  gaze_focus?: number | null
  micro_expression_intensity?: number | null
  face_detected?: boolean | null
  timestamp?: string | null
}

export interface AudioState {
  text?: string | null
  speech_rate?: number | null
  pause_ratio?: number | null
  energy?: number | null
  pitch_mean?: number | null
  pitch_variability?: number | null
  audio_available?: boolean | null
  timestamp?: string | null
}

export interface SpeechMetadata {
  duration_ms?: number | null
  speech_rate?: number | null
  pause_ratio?: number | null
  energy?: number | null
  pitch_mean?: number | null
  pitch_variability?: number | null
  audio_available?: boolean | null
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'counselor' | 'system'
  content: string
  /**
   * 该条助手消息的气泡（1~3 条）。
   * `content` 是它们的换行拼接；一轮用户输入只对应一条消息，气泡不额外占轮次。
   * 本次改动之前的历史记录可能没有这个字段，此时按 `[content]` 处理。
   */
  messages?: string[]
  created_at?: string
  vision_snapshot?: VisionState | null
  audio_snapshot?: AudioState | null
  utterance_id?: string | null
  speech?: SpeechMetadata | null
  /**
   * 用户消息附带的本轮安全结论。续测时用它恢复安全支持热线，
   * 免得中途某一轮判为 normal 就把号码弄丢了。
   */
  safety?: SafetyVerdict | null
}

export interface ConsentRecord {
  status: 'not_provided' | 'granted' | 'withdrawn'
  scope: string[]
  version: string
  granted_at?: string | null
  withdrawn_at?: string | null
}

// ---------------- Session ----------------

export interface CreateSessionResponse {
  session_id: string
  student_ref: string
  opening_message: string
  status: string
}

export interface SessionState {
  session_id: string
  student_ref: string | null
  conversation_history: ChatMessage[]
  turn_count: number
  current_stage: Stage
  latest_vision_state: VisionState | null
  vision_capture_generation: number
  latest_audio_state: AudioState | null
  vision_state_log: VisionState[]
  audio_state_log: AudioState[]
  vision_summary: Record<string, unknown> | null
  audio_summary: Record<string, unknown> | null
  /** 本轮的安全结论（新版 Safety），每轮都有。 */
  latest_safety: SafetyVerdict | null
  /** 已进入安全支持模式；会话内不会自动解除，仅人工/管理端可解除。 */
  safety_halted: boolean
  safety_stage: SafetyStage
  consent: ConsentRecord
  assessment_result_id: string | null
  created_at: string
  updated_at: string
}

export interface ConsentResponse {
  session_id: string
  consent: ConsentRecord
}

// ---------------- Chat ----------------

export interface ChatRequest {
  session_id: string
  text: string
  vision_snapshot?: VisionState | null
  utterance_id?: string
  speech?: SpeechMetadata | null
}

/** 收尾原因；topic_coverage 仅兼容旧记录，新流程由模型结束、轮数上限或用户停止。 */
export type CompletionReason = 'topic_coverage' | 'turn_limit' | 'user_requested' | 'model_finished'

/** 话题覆盖度（不是量表得分，也不代表信息完整）。 */
export interface ScreeningProgress {
  pending_topic: string | null
  topic_turns: Record<string, number>
  end_reason: CompletionReason | null
}

/** 视觉观察的诊断信息，前端不必展示给学生。 */
export interface VisualFeedback {
  reason: string
  emotion: string | null
}

export interface ChatResponse {
  session_id: string
  /**
   * 本轮回复全文（= `messages` 用换行拼接）。
   * 仅作向后兼容与降级文本使用；**前端渲染气泡只读 `messages`**，不要两者都渲染。
   */
  reply: string
  next_strategy: string
  current_stage: Stage
  /** 本轮安全结论。安全分支下 reply 为 messages[0]。 */
  safety: SafetyVerdict | null
  /**
   * 本轮面向学生的消息（1~3 条），一条气泡一条。
   * Safety 分支为 1~3 条；普通对话由 Dialogue 决定条数（也是 1~3 条）。
   */
  messages: string[]
  turn_count: number
  /** 本轮是否收尾：true 表示停止普通追问、可生成结果。 */
  assessment_ready: boolean
  completion_reason: CompletionReason | null
  screening_progress: ScreeningProgress
  visual_feedback: VisualFeedback
}

// ---------------- Vision ----------------

export interface VisionCaptureResponse {
  session_id: string
  capture_id: string | null
  generation: number
}

export interface VisionSegmentResponse {
  session_id: string
  utterance_id: string
  capture_id: string
  start_ms: number
  end_ms: number
  frame_count: number
  valid_frame_count: number
  vision_snapshot: VisionState | null
}

// ---------------- Audio ----------------

export interface AudioStatusResponse {
  state: string
  provider: string
  model: string
  max_upload_bytes: number
  max_duration_seconds: number
  timeout_seconds: number
  max_pending: number
  supported_mime_types: string[]
}

export interface TranscriptionResponse {
  session_id: string
  utterance_id: string
  text: string
  speech: SpeechMetadata
}

// ---------------- TTS ----------------

/** POST /api/tts/probe 的真合成自检结果（status.last_probe 复用同一结构）。 */
export interface TtsProbeResult {
  provider: string
  voice?: string | null
  model?: string | null
  checked_at: number
  ok: boolean
  latency_ms: number | null
  audio_bytes: number
  error: string | null
  /** true 表示这条结果来自缓存（60 秒内）。 */
  cached: boolean
}

export interface TtsStatusResponse {
  /** ready=可出声；degraded=配置就绪但上次合成失败；unconfigured=未配置。 */
  state: 'ready' | 'degraded' | 'unconfigured' | string
  /** 实际生效的 provider（配置的不可用时会静默回退）。 */
  provider: string
  /** 配置文件里指定的 provider，和 provider 不同即发生了回退。 */
  configured_provider: string
  /** 发生了回退时的原因；未回退为 null。 */
  fallback_reason?: string | null
  model?: string | null
  voice?: string | null
  /** state!=ready 时的不可用原因。 */
  reason?: string | null
  /** 上次合成失败原因；成功合成一次后清空。 */
  last_error?: string | null
  /** 最近一次真合成自检；没探测过为 null（别把 null 当成"通"）。 */
  last_probe?: TtsProbeResult | null
}

// ---------------- Assessment ----------------

export interface Profile5 {
  emotion: number
  interest_motivation: number
  sleep_energy: number
  attention_thinking: number
  social_daily: number
}

export type OverallLevel = 'low_concern' | 'mild_concern' | 'moderate_concern' | 'high_concern'
export type DimensionKey = keyof Profile5

export interface ReportBlock {
  overall_status: { level: OverallLevel; concern_index: number; summary: string }
  psychological_profile: Profile5
  primary_concern: { dimension: DimensionKey; description: string }
  key_findings: { title: string; description: string }[]
  multimodal_observation: {
    consistency_score: number | null
    consistency_level: 'low' | 'moderate' | 'high' | 'unknown'
    summary: string
  }
  trend_and_suggestions: {
    trend: 'improving' | 'stable' | 'fluctuating' | 'worsening' | 'unclear'
    trend_summary: string
    suggestions: string[]
  }
  metadata: { schema_version: string; assessment_id: string; generated_at: string }
}

export interface EvaluationResult {
  result_id: string
  session_id: string
  student_ref: string | null
  age: number | null
  grade: string | null
  psychological_profile: Profile5
  concern_index: number
  overall_level: OverallLevel
  risk: RiskResult
  report: ReportBlock | null
  assessment_method: string
  data_sources: ('text' | 'audio_transcription' | 'vision_analysis')[]
  consent_version: string
  created_at: string
}

export interface AssessmentResponse {
  session_id: string
  status: string
  result: EvaluationResult
}

// ---------------- History ----------------

export type FollowUpStatus = 'none' | 'pending' | 'in_progress' | 'resolved'

export interface CounselorNote {
  note_id: string
  counselor_ref: string
  content: string
  created_at: string
}

/** /api/history 与 /api/teacher/* 用的记录：评估结果被包裹在 result 里。 */
export interface EvaluationRecord {
  record_id: string
  student_ref: string
  result: EvaluationResult
  follow_up_status: FollowUpStatus
  counselor_notes: CounselorNote[]
  created_at: string
  archived: boolean
  risk_input_fields?: string[] | null
}

// ---------------- Healing（#13 治愈陪伴）-------------------

export type HealingStatus = 'active' | 'paused' | 'ended' | 'referred'
export type SuggestionExecution =
  | 'unconfirmed'
  | 'not_attempted'
  | 'prepared'
  | 'attempted'
  | 'declined'
export type SuggestionEffect = 'unknown' | 'helpful' | 'ineffective' | 'worse'

/** 回答下方那行浅字：知识库原文，学生可见；不含来源信息。 */
export interface MessageReference {
  title: string
  /** 这条方法原本的说法，已连成一段话，直接当一行渲染。 */
  text: string
  /** 本来就要求的执行条件；可能为空数组。 */
  conditions: string[]
  /** 本来就带的注意事项；可能为空数组。 */
  cautions: string[]
}

export interface HealingSuggestion {
  title: string
  /** 这条方法的知识库原文（目标与步骤已连成一段话），与 messages[].references[].text 同一份文字。 */
  text: string
  goal: string
  steps: string[]
  prerequisites: string[]
  cautions: string[]
  execution: SuggestionExecution
  effect: SuggestionEffect
  active: boolean
}

export interface HealingReport {
  understanding: string
  focus: string
  suggestions: HealingSuggestion[]
  cautions: string[]
  question: string | null
  generated_at: string
}

export interface HealingResponse {
  session_id: string
  healing_id: string
  assessment_result_id: string
  assessment_session_id?: string
  status: HealingStatus
  turn_count: number
  report: HealingReport
  messages: {
    role: 'user' | 'assistant'
    content: string
    created_at: string
    /** 浅字原文；只有新方法/恢复的方法/简化版才附，正常闲聊为 []。旧数据可能没有这个键。 */
    references?: MessageReference[]
  }[]
  /** 本会话当前生效的安全结论：后端 HealingResponse.risk 现在是 SafetyVerdict。 */
  risk: SafetyVerdict
  notice: string
}

export interface HealingBackgroundInput {
  school_stage?: 'primary' | 'middle' | 'high'
  current_concern?: string
  important_events?: string[]
  preferences?: string[]
  constraints?: string[]
  previous_attempts?: string[]
  adult_support_available?: boolean
}

export interface StartHealingRequest {
  session_id: string
  request_id: string
  regenerate?: boolean
  expected_healing_id?: string
  background?: HealingBackgroundInput
}

// ---------------- Heal 小工具 ----------------

export interface HealContent {
  id: string
  title: string
  body?: string
  summary?: string
  tags?: string[]
  mood_min?: number | null
  mood_max?: number | null
  category?: string
  [k: string]: unknown
}

export interface MoodEntry {
  student_ref: string
  date: string
  mood: number
  weather?: string | null
  color?: string | null
  tags?: string[]
  note?: string | null
  voice_text?: string | null
  created_at?: string
}

export interface HabitRecord {
  student_ref: string
  date: string
  items: string[]
  created_at?: string
}

export interface FocusSession {
  student_ref: string
  minutes: number
  mood_before?: number
  mood_after?: number
  created_at?: string
}

export interface GrowthResponse {
  student_ref: string
  days: number
  mood_days: number
  habit_days: number
  streak: number
  focus_sessions: number
  focus_minutes: number
  mood_tag_counts: Record<string, number>
  moods: MoodEntry[]
  habits: HabitRecord[]
}

// ---------------- Communication ----------------

export interface CommunicationMessage {
  id?: string
  student_ref: string
  counselor_ref: string | null
  direction: 'student_to_counselor' | 'counselor_to_student'
  content: string
  created_at: string
}

// ---------------- 学生档案 / 紧急联系人 ----------------

export type SchoolStage = 'primary' | 'middle' | 'high'

/** GET /api/profile/{student_ref} 与 PUT /api/profile 的档案体。 */
export interface StudentProfile {
  student_ref: string
  nickname: string
  school_stage: SchoolStage | null
  class_name: string
  updated_at?: string
}

/** 紧急联系人：id 由后端生成，前端只读。 */
export interface EmergencyContact {
  id: string
  name: string
  relation: string
  phone: string
  created_at?: string
}
