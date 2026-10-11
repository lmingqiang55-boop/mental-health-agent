/**
 * 匿名学生标识 student_ref 的生成与持久化。
 * 约束：^[A-Za-z0-9_-]+$，长度 1~128（后端会校验）。
 * 它不是登录凭据，仅用于把「历史记录 / 治愈日记」归属到同一匿名身份。
 */

const KEY = 'xq_student_ref'
const VALID = /^[A-Za-z0-9_-]+$/

function randomRef(): string {
  const rand = Math.random().toString(36).slice(2, 10)
  return `xq-${Date.now().toString(36)}${rand}`
}

/** 读取已存在的 student_ref；不存在或非法则生成并写入。 */
export function ensureStudentRef(): string {
  let ref = ''
  try {
    ref = localStorage.getItem(KEY) ?? ''
  } catch {
    ref = ''
  }
  if (ref && VALID.test(ref) && ref.length <= 128) return ref

  const next = randomRef()
  try {
    localStorage.setItem(KEY, next)
  } catch {
    /* 隐私模式等场景忽略 */
  }
  return next
}

/** 强制写入新身份（「重置身份」用）。 */
export function resetStudentRef(): string {
  const next = randomRef()
  try {
    localStorage.setItem(KEY, next)
  } catch {
    /* ignore */
  }
  return next
}
