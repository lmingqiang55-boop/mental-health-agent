/**
 * 时间 / 数值 格式化工具（Dayjs）。
 */
import dayjs from 'dayjs'

/** 今天日期，格式 YYYY-MM-DD（用于 /api/heal/mood 的 date 字段）。 */
export function todayStr(): string {
  return dayjs().format('YYYY-MM-DD')
}

/** 日期时间 → 「10-09 14:32」 */
export function fmtDateTime(input?: string | number | null): string {
  if (!input) return '—'
  const d = dayjs(input)
  return d.isValid() ? d.format('MM-DD HH:mm') : String(input)
}

/** 日期时间 → 「2026-10-09 14:32」 */
export function fmtFullDateTime(input?: string | number | null): string {
  if (!input) return '—'
  const d = dayjs(input)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : String(input)
}

/** 日期时间 → 「2026-10-09」 */
export function fmtDate(input?: string | number | null): string {
  if (!input) return '—'
  const d = dayjs(input)
  return d.isValid() ? d.format('YYYY-MM-DD') : String(input)
}

/** 相对时间：「刚刚 / 5 分钟前 / 昨天 / 10-09」 */
export function fmtRelative(input?: string | number | null): string {
  if (!input) return '—'
  const d = dayjs(input)
  if (!d.isValid()) return String(input)
  const diffMin = dayjs().diff(d, 'minute')
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffH = dayjs().diff(d, 'hour')
  if (diffH < 24) return `${diffH} 小时前`
  const diffD = dayjs().diff(d, 'day')
  if (diffD === 1) return '昨天'
  if (diffD < 7) return `${diffD} 天前`
  return d.format('MM-DD')
}

/** 秒 → mm:ss */
export function fmtClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
}
