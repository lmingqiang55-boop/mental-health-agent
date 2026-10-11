/**
 * 轻量全局 Toast（无 Element Plus 依赖）。
 * 发布/订阅式：任意位置调用 toast()，由 <PxToastHost> 统一渲染。
 */

export type ToastType = 'info' | 'success' | 'warning' | 'error'

export interface ToastItem {
  id: number
  type: ToastType
  message: string
}

type Listener = (items: ToastItem[]) => void

let seq = 0
let items: ToastItem[] = []
const listeners = new Set<Listener>()

function emit() {
  const snapshot = [...items]
  listeners.forEach((fn) => fn(snapshot))
}

export function subscribeToast(fn: Listener): () => void {
  listeners.add(fn)
  fn([...items])
  return () => listeners.delete(fn)
}

export function dismissToast(id: number) {
  items = items.filter((t) => t.id !== id)
  emit()
}

export function toast(message: string, type: ToastType = 'info', duration = 3000): number {
  const id = ++seq
  items = [...items, { id, type, message }]
  emit()
  if (duration > 0) window.setTimeout(() => dismissToast(id), duration)
  return id
}

export const toastError = (msg: string) => toast(msg, 'error', 4000)
export const toastSuccess = (msg: string) => toast(msg, 'success')
export const toastWarn = (msg: string) => toast(msg, 'warning', 3500)
