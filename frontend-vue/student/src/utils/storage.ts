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

const CONSENT_PREFS_KEY = STORAGE_KEYS.consentPrefs

/**
 * 是否允许浏览器持久化业务数据。
 * 授权偏好自身始终可读写，否则用户关闭后刷新页面会被悄悄恢复为默认开启。
 */
export function isLocalStorageAllowed(): boolean {
  try {
    const raw = localStorage.getItem(CONSENT_PREFS_KEY)
    if (raw === null) return true
    const prefs = JSON.parse(raw) as { allowStorage?: boolean }
    return prefs.allowStorage !== false
  } catch {
    return true
  }
}

export function readLS<T>(key: string, fallback: T): T {
  try {
    if (key !== CONSENT_PREFS_KEY && !isLocalStorageAllowed()) return fallback
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function writeLS(key: string, value: unknown): void {
  try {
    if (key !== CONSENT_PREFS_KEY && !isLocalStorageAllowed()) return
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 忽略写入失败（容量/隐私模式） */
  }
}

/** 清除心晴写入的浏览器持久化数据，可选择保留隐私授权本身。 */
export function clearAppLocalStorage(preserveConsent = false): void {
  try {
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key?.startsWith('xq_') && (!preserveConsent || key !== CONSENT_PREFS_KEY)) {
        keys.push(key)
      }
    }
    keys.forEach((key) => localStorage.removeItem(key))
  } catch {
    /* ignore */
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
