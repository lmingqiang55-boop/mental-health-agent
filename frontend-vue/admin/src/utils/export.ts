/**
 * 通用 CSV 导出工具（对标开源后台的「导出」能力）。
 *
 * 场景：预警名单 / 测评结果 / 学生档案 / 任务参与明细导出为表格，
 * 供学校上报、存档、家校沟通使用。带 UTF-8 BOM，Excel 直接打开中文不乱码。
 */
export interface CsvColumn<T> {
  title: string
  value: (row: T) => string | number | null | undefined
}

function escapeCell(v: unknown): string {
  const s = v == null ? '' : String(v)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** 触发浏览器下载一份 CSV */
export function exportCsv<T>(filename: string, columns: CsvColumn<T>[], rows: T[]) {
  const header = columns.map((c) => escapeCell(c.title)).join(',')
  const body = rows.map((r) => columns.map((c) => escapeCell(c.value(r))).join(',')).join('\r\n')
  const csv = `\uFEFF${header}\r\n${body}`
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/** 文件名时间戳，如 20261010_1430 */
export function stamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`
}
