/**
 * localStorage 安全封装（统一 xq_ 前缀）。
 * 所有本地态键集中在此声明，避免散落各处拼字符串。
 */

export const STORAGE_KEYS = {
  studentRef: 'xq_student_ref',
  theme: 'xq_theme',
  camEnabled: 'xq_device_cam',
  assessProgress: 'xq_assess_progress',
  healing: 'xq_healing',
  nickname: 'xq_nickname',
  contacts: 'xq_contacts',
  consentPrefs: 'xq_consent_prefs',
  consentAck: 'xq_consent_ack',
  moodDraft: 'xq_mood_draft',
  artWorks: 'xq_art_works',
  icbtProgress: 'xq_icbt_progress',
  reframeNotes: 'xq_reframe_notes',
} as const

export function readLS<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function writeLS(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 忽略写入失败（容量/隐私模式） */
  }
}

export function removeLS(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    /* ignore */
  }
}

/** 仅用于 sessionStorage 的布尔开关（设备检查结果，会话内有效）。 */
export function readSessionFlag(key: string): boolean | null {
  try {
    const v = sessionStorage.getItem(key)
    if (v === null) return null
    return v === '1'
  } catch {
    return null
  }
}

export function writeSessionFlag(key: string, value: boolean): void {
  try {
    sessionStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* ignore */
  }
}
