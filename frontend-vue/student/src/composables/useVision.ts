import { ref, onUnmounted } from 'vue'
import { visionApi } from '@/api'
import { isApiError } from '@/api/http'
import type { VisionState } from '@/api/types'
import { newFrameId } from '@/utils/id'

/**
 * 摄像头采集封装（可完全关闭）。
 * 链路：capture(开) → frame(按间隔送帧) → segment(回合结束冻结快照)。
 * 关闭摄像头时全部 no-op，聊天请求不带 vision_snapshot（不影响评估有效性）。
 */
export function useVision() {
  const active = ref(false)
  const error = ref('')
  const videoEl = ref<HTMLVideoElement | null>(null)
  const faceDetected = ref<boolean | null>(null)
  // 采集健康度：已成功上报的帧数，以及最近一次取帧/快照失败原因。
  // 供 UI 区分「摄像头没开」与「开了但数据没上去」。
  const framesSent = ref(0)
  const uploadError = ref('')

  let stream: MediaStream | null = null
  let timer = 0
  let captureId = ''
  let generation = 0
  let sessionId = ''
  let originAt = 0

  function bindVideo(el: HTMLVideoElement | null) {
    videoEl.value = el
    if (el && stream) el.srcObject = stream
  }

  /**
   * 本会话稳定的采集标识。
   * 转写(/api/audio/transcribe)与取帧必须共用同一个 capture_id：
   * 关闭摄像头时也要用同一个 id，否则转写会因字段缺失被 422 拒绝。
   */
  function ensureCaptureId(): string {
    if (!captureId) captureId = `cap-${Date.now().toString(36)}`
    return captureId
  }

  async function openCamera(): Promise<MediaStream> {
    if (stream) return stream
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 960 }, height: { ideal: 540 }, facingMode: 'user' },
      audio: false,
    })
    if (videoEl.value) {
      videoEl.value.srcObject = stream
      await videoEl.value.play().catch(() => undefined)
    }
    return stream
  }

  function grabFrameBase64(): string | null {
    const el = videoEl.value
    if (!el || !el.videoWidth) return null
    const maxW = 1280
    const scale = Math.min(1, maxW / el.videoWidth)
    const w = Math.round(el.videoWidth * scale)
    const h = Math.round(el.videoHeight * scale)
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(el, 0, 0, w, h)
    return canvas.toDataURL('image/jpeg', 0.7)
  }

  async function sendFrame() {
    const image = grabFrameBase64()
    if (!image || !sessionId || !captureId) return
    try {
      // 高频（约 1 帧/秒）请求用 silent：失败不弹 toast 刷屏，
      // 改由 uploadError/framesSent 暴露到会话页的采集状态里。
      await visionApi.frame(
        {
          session_id: sessionId,
          image_base64: image,
          frame_id: newFrameId(),
          capture_id: captureId,
          captured_at_ms: performance.now() - originAt,
        },
        { silent: true },
      )
      framesSent.value += 1
      uploadError.value = ''
    } catch (e) {
      // 单帧失败不打断采集，但要把原因记下来给 UI 用。
      uploadError.value = isApiError(e) ? e.message : '摄像头数据未能上传'
    }
  }

  /** 开启采集：sessionId + 摄像头流，并开始定时送帧（约 1 帧/秒）。 */
  async function start(sid: string, originMs: number) {
    error.value = ''
    uploadError.value = ''
    framesSent.value = 0
    sessionId = sid
    originAt = originMs
    try {
      await openCamera()
      generation += 1
      captureId = ensureCaptureId()
      await visionApi.capture(sid, captureId, generation, true)
      active.value = true
      timer = window.setInterval(sendFrame, 1000)
    } catch (e) {
      error.value = (e as Error)?.message || '摄像头不可用'
      active.value = false
      throw e
    }
  }

  /** 回合结束：按 [startMs,endMs) 冻结视觉快照（无帧则得到 null）。 */
  async function segment(utteranceId: string, startMs: number, endMs: number): Promise<VisionState | null> {
    if (!active.value || !sessionId || !captureId) return null
    try {
      const res = await visionApi.segment({
        session_id: sessionId,
        utterance_id: utteranceId,
        capture_id: captureId,
        start_ms: Math.round(startMs),
        end_ms: Math.round(endMs),
      })
      faceDetected.value = res.vision_snapshot?.face_detected ?? null
      return res.vision_snapshot
    } catch (e) {
      // 快照失败：不阻断对话（这段仍按仅语音评估），但要暴露原因。
      uploadError.value = isApiError(e) ? e.message : '视觉快照获取失败'
      return null
    }
  }

  async function stop() {
    window.clearInterval(timer)
    timer = 0
    if (active.value && sessionId) {
      try {
        generation += 1
        await visionApi.capture(sessionId, captureId, generation, false)
      } catch {
        /* ignore */
      }
      active.value = false
    }
    stream?.getTracks().forEach((t) => t.stop())
    stream = null
    if (videoEl.value) videoEl.value.srcObject = null
  }

  onUnmounted(() => {
    void stop()
  })

  return {
    active,
    error,
    videoEl,
    faceDetected,
    framesSent,
    uploadError,
    bindVideo,
    ensureCaptureId,
    start,
    segment,
    stop,
  }
}
