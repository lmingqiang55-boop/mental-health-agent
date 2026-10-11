import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 学生端开发端口固定 5174。
// 注意：后端 CORS 白名单默认只含 5173，使用 5174 前需把
// http://localhost:5174 与 http://127.0.0.1:5174 加进 backend 的 CORS_ORIGINS 并重启后端。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    host: '127.0.0.1',
  },
})
