import axios, { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

/**
 * 后端契约：
 * - 返回裸 JSON（不是 {code,data,message} 包裹）
 * - 错误统一为 { error: { code, message } }，校验失败 422 VALIDATION_ERROR
 * - 无鉴权：不要带 Authorization 头（CORS 只允许 Content-Type）
 */
export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000',
  timeout: 30_000,
})

export interface ApiError {
  code: string
  message: string
  status: number
}

http.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ error?: { code?: string; message?: string } }>) => {
    const apiErr: ApiError = {
      status: err.response?.status ?? 0,
      code: err.response?.data?.error?.code ?? 'NETWORK_ERROR',
      message:
        err.response?.data?.error?.message ??
        (err.code === 'ECONNABORTED' ? '请求超时' : '无法连接后端，请确认 8000 端口服务已启动'),
    }
    ElMessage.error(`${apiErr.message}${apiErr.code !== 'NETWORK_ERROR' ? `（${apiErr.code}）` : ''}`)
    return Promise.reject(apiErr)
  },
)
