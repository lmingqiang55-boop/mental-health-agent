import { ref, onUnmounted } from 'vue'

/**
 * MediaRecorder 录音封装。
 * 记录相对会话开始的起止毫秒（recording_start_ms / recording_end_ms），
 * 与视觉 segment 的时间轴一致（同一 origin）。
 */
export interface RecordingResult {
  blob: Blob
  mimeType: string
  durationMs: number
  startMs: number
  endMs: number
}

function pickMime(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  if (typeof MediaRecorder === 'undefined') return ''
  return candidates.find((m) => MediaRecorder.isTypeSupported(m)) ?? ''
}

export function useRecorder() {
  const recording = ref(false)
  const elapsedMs = ref(0)
  const error = ref<string>('')

  let stream: MediaStream | null = null
  let recorder: MediaRecorder | null = null
  let chunks: Blob[] = []
  let startAt = 0
  let t0 = 0
  let tickTimer = 0
  let generation = 0
  let cancelStop: (() => void) | null = null

  async function ensureStream(): Promise<MediaStream> {
    if (stream) return stream
    const current = generation
    const opened = await navigator.mediaDevices.getUserMedia({ audio: true })
    if (current !== generation) {
      opened.getTracks().forEach((track) => track.stop())
      throw new Error('录音已取消')
    }
    stream = opened
    return stream
  }

  /** originMs：会话开始到「按下开始录音」的毫秒数（用于对齐视觉时间轴）。 */
  async function start(originMs = 0): Promise<void> {
    error.value = ''
    const requestedAt = performance.now()
    try {
      const s = await ensureStream()
      const mime = pickMime()
      recorder = mime ? new MediaRecorder(s, { mimeType: mime }) : new MediaRecorder(s)
      chunks = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      startAt = originMs + performance.now() - requestedAt
      recorder.start()
      recording.value = true
      elapsedMs.value = 0
      t0 = performance.now()
      tickTimer = window.setInterval(() => {
        elapsedMs.value = performance.now() - t0
      }, 100)
    } catch (e) {
      error.value = (e as Error)?.message || '无法访问麦克风'
      recording.value = false
      throw e
    }
  }

  function stop(): Promise<RecordingResult> {
    return new Promise((resolve, reject) => {
      if (!recorder || recorder.state === 'inactive') {
        reject(new Error('未在录音中'))
        return
      }
      window.clearInterval(tickTimer)
      const durationMs = Math.round(performance.now() - t0)
      const stoppedRecorder = recorder
      cancelStop = () => reject(new Error('录音已取消'))
      recorder.onstop = () => {
        cancelStop = null
        const type = stoppedRecorder.mimeType || 'audio/webm'
        const blob = new Blob(chunks, { type })
        recording.value = false
        resolve({
          blob,
          mimeType: type,
          durationMs,
          startMs: Math.round(startAt),
          endMs: Math.round(startAt + durationMs),
        })
      }
      recorder.onerror = () => {
        cancelStop = null
        recording.value = false
        reject(new Error('录音失败'))
      }
      recorder.stop()
    })
  }

  function dispose() {
    cancel()
  }

  /** 取消本次录音：丢弃缓冲并释放设备，不生成 Blob，也不会触发上传。 */
  function cancel() {
    generation += 1
    cancelStop?.()
    cancelStop = null
    window.clearInterval(tickTimer)
    if (recorder) {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.onerror = null
      try {
        if (recorder.state !== 'inactive') recorder.stop()
      } catch {
        /* ignore */
      }
    }
    chunks = []
    stream?.getTracks().forEach((t) => t.stop())
    stream = null
    recorder = null
    recording.value = false
    elapsedMs.value = 0
  }

  onUnmounted(dispose)

  return { recording, elapsedMs, error, start, stop, cancel, dispose, ensureStream }
}
