import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@/styles/index.css'
import App from './App.vue'
import { router } from './router'
import { ensureStudentRef } from '@/utils/studentRef'

// 首次进入即确保匿名身份存在（无鉴权，身份仅用于归属历史/日记）
ensureStudentRef()

createApp(App).use(createPinia()).use(router).mount('#app')
