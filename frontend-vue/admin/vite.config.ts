import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

// 端口固定 5173：后端 CORS_ORIGINS 白名单已包含 http://localhost:5173
// base './' + viteSingleFile：构建产物是单个 index.html，双击即可打开（无需服务器）
export default defineConfig({
  base: './',
  plugins: [vue(), viteSingleFile()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: { port: 5173, host: '127.0.0.1' },
  build: { chunkSizeWarningLimit: 5000 },
})
