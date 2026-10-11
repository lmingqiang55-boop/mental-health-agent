import { ref, onUnmounted } from 'vue'
import { ttsApi } from '@/api'
import { isApiError } from '@/api/http'

/**
 * TTS 播报封装：POST /api/tts 返回 audio/mpeg 二进制。
 * - 503 TTS_UNAVAILABLE / 网络失败 → 降级浏览器 speechSynthesis。
 * - 同一时刻只播放一条，新的一条会打断旧的。
 */
export function useTts() {
  const speaking = ref(false)
  const available = ref<boolean | null>(null)

  let audio: HTMLAudioElement | null = null
  let objectUrl: string | null = null

  async function checkStatus() {
    try {
      const s = await ttsApi.status()
      available.value = s.state === 'ready'
    } catch {
      available.value = false
    }
    return available.value
  }

  function stop() {
    if (audio) {
      audio.pause()
      audio.onended = null
      audio = null
    }
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl)
      objectUrl = null
    }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    speaking.value = false
  }

  function speakBrowser(text: string): Promise<void> {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window)) {
        resolve()
        return
      }
      const u = new SpeechSynthesisUtterance(text)
      u.lang = 'zh-CN'
      u.rate = 1
      u.onend = () => {
        speaking.value = false
        resolve()
      }
      u.onerror = () => {
        speaking.value = false
        resolve()
      }
      speaking.value = true
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(u)
    })
  }

  /**
   * 播报某回合助手回复。
   * @param turnCount 0=开场白，>=1=对应回合
   * @param fallbackText 后端 TTS 不可用时用于浏览器语音的文本
   */
  async function speak(sessionId: string, turnCount: number, fallbackText = ''): Promise<void> {
    stop()
    try {
      const blob = await ttsApi.synth(sessionId, turnCount)
      objectUrl = URL.createObjectURL(blob)
      audio = new Audio(objectUrl)
      speaking.value = true
      await new Promise<void>((resolve) => {
        if (!audio) return resolve()
        audio.onended = () => {
          speaking.value = false
          resolve()
        }
        audio.onerror = () => {
          speaking.value = false
          resolve()
        }
        audio.play().catch(() => {
          speaking.value = false
          resolve()
        })
      })
    } catch (e) {
      if (isApiError(e, 'TTS_UNAVAILABLE') || isApiError(e, 'NETWORK_ERROR')) {
        available.value = false
        if (fallbackText) await speakBrowser(fallbackText)
      } else if (fallbackText) {
        // 其它错误（如 REPLY_NOT_FOUND）也降级，避免打断流程
        await speakBrowser(fallbackText)
      }
    }
  }

  onUnmounted(stop)

  return { speaking, available, checkStatus, speak, stop }
}
