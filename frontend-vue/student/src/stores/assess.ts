import { defineStore } from 'pinia'
import { ref } from 'vue'
import { STORAGE_KEYS, readLS, writeLS, removeLS, readSessionFlag, writeSessionFlag } from '@/utils/storage'

export interface AssessProgress {
  sessionId: string
  turnCount: number
  lastUtteranceId: string | null
  updatedAt: number
}

/**
 * 测评会话态：当前 sessionId / turnCount / 设备开关 / 进度暂存（真正断点续测）。
 * session_id 本身是后端内存态（TTL 2h），前端只负责记住并在恢复时校验。
 */
export const useAssessStore = defineStore('assess', () => {
  const sessionId = ref<string>('')
  const turnCount = ref(0)
  /** 摄像头是否启用（设备检查结果，仅前端态；关闭=仅语音，不影响有效性） */
  const camEnabled = ref<boolean>(readSessionFlag(STORAGE_KEYS.camEnabled) ?? false)
  const micEnabled = ref(true)

  function setCamEnabled(v: boolean) {
    camEnabled.value = v
    writeSessionFlag(STORAGE_KEYS.camEnabled, v)
  }
  function setMicEnabled(v: boolean) {
    micEnabled.value = v
  }

  function setSession(id: string, turns = 0) {
    sessionId.value = id
    turnCount.value = turns
  }

  /** 暂存进度（离开测评页时调用）。 */
  function saveProgress(lastUtteranceId: string | null) {
    if (!sessionId.value) return
    const p: AssessProgress = {
      sessionId: sessionId.value,
      turnCount: turnCount.value,
      lastUtteranceId,
      updatedAt: Date.now(),
    }
    writeLS(STORAGE_KEYS.assessProgress, p)
  }

  function readProgress(): AssessProgress | null {
    return readLS<AssessProgress | null>(STORAGE_KEYS.assessProgress, null)
  }

  function clearProgress() {
    removeLS(STORAGE_KEYS.assessProgress)
    sessionId.value = ''
    turnCount.value = 0
  }

  return {
    sessionId,
    turnCount,
    camEnabled,
    micEnabled,
    setCamEnabled,
    setMicEnabled,
    setSession,
    saveProgress,
    readProgress,
    clearProgress,
  }
})
