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
export type Stage = 'exploration' | 'crisis' | 'assessment_ready' | 'assessment' | 'completed'

export interface RiskResult {
  risk_level: RiskLevel
  risk_score: number
  risk_reasons: string[]
  risk_types: string[]
  key_evidence: string[]
  requires_intervention: boolean
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
  created_at?: string
  vision_snapshot?: VisionState | null
  audio_snapshot?: AudioState | null
  utterance_id?: string | null
  speech?: SpeechMetadata | null
}

export interface ConsentRecord {
  granted: boolean
  scope: string[]
  granted_at?: string | null
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
  latest_audio_state: AudioState | null
  vision_state_log: VisionState[]
  audio_state_log: AudioState[]
  vision_summary: Record<string, unknown> | null
  audio_summary: Record<string, unknown> | null
  latest_risk: RiskResult
  crisis_mode: boolean
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

/** 收尾原因：主要话题聊完 / 到轮数上限 / 用户主动停止。 */
export type CompletionReason = 'topic_coverage' | 'turn_limit' | 'user_requested'

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
  reply: string
  next_strategy: string
  current_stage: Stage
  risk: RiskResult
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

export interface TtsStatusResponse {
  state: 'ready' | 'unconfigured' | string
  model?: string
  voice?: string
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

export interface HealingSuggestion {
  title: string
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
  status: HealingStatus
  turn_count: number
  report: HealingReport
  messages: { role: 'user' | 'assistant'; content: string; created_at: string }[]
  risk: RiskResult
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
