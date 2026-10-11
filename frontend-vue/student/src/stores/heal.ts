import { defineStore } from 'pinia'
import { ref } from 'vue'
import { STORAGE_KEYS, readLS, writeLS, removeLS } from '@/utils/storage'
import type { HealingResponse } from '@/api/types'

interface HealingPointer {
  sessionId: string
  healingId: string
  updatedAt: number
}

/**
 * 治愈陪伴态（#13）。状态是后端进程内存，刷新后需用 GET /api/healing/{session_id} 恢复；
 * 这里只记住「上次的 session_id / healing_id」，恢复失败即视为失效。
 */
export const useHealStore = defineStore('heal', () => {
  const current = ref<HealingResponse | null>(null)
  const sending = ref(false)

  function remember(res: HealingResponse) {
    current.value = res
    writeLS(STORAGE_KEYS.healing, {
      sessionId: res.session_id,
      healingId: res.healing_id,
      updatedAt: Date.now(),
    } satisfies HealingPointer)
  }

  function pointer(): HealingPointer | null {
    return readLS<HealingPointer | null>(STORAGE_KEYS.healing, null)
  }

  function clear() {
    current.value = null
    removeLS(STORAGE_KEYS.healing)
  }

  return { current, sending, remember, pointer, clear }
})
