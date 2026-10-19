import axios, { AxiosError } from 'axios'
import { toastError } from '@/utils/toast'
import type { ApiErrorShape } from './types'

/**
 * 后端契约（见 docs/新前端接入说明.md）：
 * - 返回裸 JSON（不是 { code, data, message } 包裹）
 * - 错误统一为 { error: { code, message } }，校验失败 422 VALIDATION_ERROR
 * - 无鉴权：不带 Authorization 头（CORS 只允许 Content-Type）
 * - 超时放宽到 60s（ASR / 评估 / TTS 都可能较慢）
 */
export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000',
  timeout: 60_000,
})

/** 静默选项：某些调用（如启动时探测 health）不希望弹 toast。 */
export interface RequestConfig {
  silent?: boolean
  signal?: AbortSignal
}

// 让 `silent` 成为 axios 一等配置项，供各接口按请求传入（拦截器据此决定是否弹 toast）。
declare module 'axios' {
  export interface AxiosRequestConfig {
    silent?: boolean
  }
}

http.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ error?: { code?: string; message?: string } }>) => {
    const status = err.response?.status ?? 0
    const code = err.response?.data?.error?.code ?? (status === 0 ? 'NETWORK_ERROR' : 'HTTP_ERROR')
    let message =
      err.response?.data?.error?.message ??
      (err.code === 'ECONNABORTED'
        ? '请求超时，请稍后重试'
        : '无法连接后端服务，请确认 8000 端口已启动')

    if (code === 'VALIDATION_ERROR') message = '提交的数据不符合要求，请检查后重试'
    if (!navigator.onLine) message = '当前网络不可用，请检查网络连接'

    const apiErr: ApiErrorShape = { status, code, message }

    const silent = (err.config as { silent?: boolean } | undefined)?.silent
    const cancelled = err.code === 'ERR_CANCELED'
    if (!silent && !cancelled) {
      toastError(`${message}${code !== 'NETWORK_ERROR' ? `（${code}）` : ''}`)
    }
    return Promise.reject(apiErr)
  },
)

/** 判断是否为指定错误码的 ApiError。 */
export function isApiError(e: unknown, code?: string): e is ApiErrorShape {
  if (!e || typeof e !== 'object') return false
  const err = e as ApiErrorShape
  if (typeof err.code !== 'string' || typeof err.status !== 'number') return false
  return code ? err.code === code : true
}
