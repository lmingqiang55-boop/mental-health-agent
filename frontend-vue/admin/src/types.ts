/**
 * 与后端契约一致的类型定义。
 * 权威来源：backend/backend/models/* 与 backend/backend/api/teacher.py
 */

// ---- 枚举 ----
export type RiskLevel = 'low' | 'medium' | 'high'
export type FollowUpStatus = 'none' | 'pending' | 'in_progress' | 'resolved'
export type OverallLevel = 'low_concern' | 'mild_concern' | 'moderate_concern' | 'high_concern'

// ---- 评估结果 ----
export interface RiskResult {
  risk_level: RiskLevel
  risk_score: number
  risk_reasons: string[]
  risk_types: string[]
  key_evidence: string[]
  requires_intervention: boolean
}

/** 五维画像，0~100，数值越高 = 越值得关注 */
export interface PsychologicalProfile {
  emotion: number
  interest_motivation: number
  sleep_energy: number
  attention_thinking: number
  social_daily: number
}

export interface EvaluationReport {
  overall_status: { level: OverallLevel; concern_index: number; summary: string }
  psychological_profile: PsychologicalProfile
  primary_concern: { dimension: keyof PsychologicalProfile; description: string }
  key_findings: { title: string; description: string }[]
  multimodal_observation: {
    consistency_score: number | null
    consistency_level: 'low' | 'moderate' | 'high' | 'unknown'
    summary: string
  }
  trend_and_suggestions: { trend: string; trend_summary: string; suggestions: string[] }
  metadata: Record<string, unknown>
}

export interface EvaluationResult {
  result_id: string
  session_id: string
  student_ref: string | null
  age: number | null
  grade: string | null
  psychological_profile: PsychologicalProfile
  concern_index: number
  overall_level: OverallLevel
  risk: RiskResult
  report: EvaluationReport
  assessment_method: 'evaluation_agent'
  created_at: string
}

export interface CounselorNote {
  note_id: string
  counselor_ref: string
  content: string
  created_at: string
}

export interface EvaluationRecord {
  record_id: string
  student_ref: string
  result: EvaluationResult
  follow_up_status: FollowUpStatus
  counselor_notes: CounselorNote[]
  created_at: string
  archived: boolean
}

// ---- 老师端接口响应 ----
export interface RecordSummary {
  record_id: string
  student_ref: string
  concern_index: number
  overall_level: OverallLevel
  risk_level: RiskLevel
  created_at: string
  follow_up_status: FollowUpStatus
}

export interface HighRiskItem {
  record_id: string
  student_ref: string
  risk_level: RiskLevel
  risk_types: string[]
  risk_reasons: string[]
  key_evidence: string[]
  follow_up_status: FollowUpStatus
}

export interface GroupStats {
  total_students: number
  risk_distribution: Partial<Record<RiskLevel, number>>
  dimension_averages: Partial<Record<keyof PsychologicalProfile, number>>
}

// ---- 沟通 ----
export interface CommunicationMessage {
  message_id: string
  student_ref: string
  counselor_ref: string | null
  direction: 'student_to_counselor' | 'counselor_to_student'
  content: string
  read: boolean
  created_at: string
}
