// Browser media lifetime and capture clock, independent of React renders.
const FRAME_REQUEST_TIMEOUT_MS = 10_000

export class CaptureController {
  constructor(api, hooks = {}, environment = {}) {
    this.api = api
    this.hooks = hooks
    this.env = {
      now: () => performance.now(), uuid: () => crypto.randomUUID(),
      getUserMedia: options => navigator.mediaDevices.getUserMedia(options),
      MediaRecorder: globalThis.MediaRecorder,
      setInterval: (...args) => globalThis.setInterval(...args),
      clearInterval: (...args) => globalThis.clearInterval(...args),
      setTimeout: (...args) => globalThis.setTimeout(...args),
      clearTimeout: (...args) => globalThis.clearTimeout(...args),
      ...environment,
    }
    this.sessionId = ''
    this.captureId = this.env.uuid()
    this.sessionEpoch = 0
    this.cameraEpoch = 0
    this.recordEpoch = 0
    this.pendingFrames = new Set()
    this.frameJob = null
    this.opening = false
    this.stream = null
    this.record = null
  }

  resetSession(sessionId) {
    this.sessionEpoch++
    this.stopCamera()
    this.cancelRecording()
    this.sessionId = sessionId
    this.captureId = this.env.uuid()
  }

  async openCamera(video, canvas) {
    if (this.opening || this.stream || !this.sessionId) return
    this.opening = true
    const epoch = ++this.cameraEpoch
    const sessionId = this.sessionId
    const captureId = this.env.uuid()
    const current = () => epoch === this.cameraEpoch && sessionId === this.sessionId
    let stream
    this.hooks.camera?.('opening')
    try {
      stream = await this.env.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false,
      })
      if (!current()) { stream.getTracks().forEach(track => track.stop()); return }
      this.stream = stream
      this.video = video
      this.canvas = canvas
      video.srcObject = stream
      await video.play()
      if (!current()) return
      await this.api.setVisionCapture(sessionId, captureId, epoch, true)
      if (!current()) return
      this.captureId = captureId
      this.opening = false
      this.timer = this.env.setInterval(() => this.captureFrame(), 500)
      this.hooks.camera?.('on')
      this.captureFrame()
    } catch (error) {
      if (current()) {
        this.hooks.cameraError?.(error.name === 'NotAllowedError' ? '未获得摄像头权限。' : error.message || '无法打开摄像头。')
        this.stopCamera()
      }
    } finally {
      if (!current()) stream?.getTracks().forEach(track => track.stop())
      if (current()) this.opening = false
    }
  }

  stopCamera() {
    const epoch = ++this.cameraEpoch
    const sessionId = this.sessionId
    const captureId = this.captureId
    this.opening = false
    if (this.timer != null) this.env.clearInterval(this.timer)
    this.timer = null
    this.stream?.getTracks().forEach(track => track.stop())
    this.stream = null
    if (this.video) this.video.srcObject = null
    for (const job of this.pendingFrames) {
      this.env.clearTimeout(job.timer)
      job.abort.abort()
    }
    this.frameJob = null
    this.hooks.camera?.('off')
    if (sessionId) {
      // Generation ordering makes a delayed close unable to stop a new capture.
      this.api.setVisionCapture(sessionId, captureId, epoch, false).catch(error => {
        if (epoch === this.cameraEpoch && sessionId === this.sessionId && error.status !== 404) {
          this.hooks.cameraError?.('摄像头已关闭，但服务端状态更新失败；后续发言不会借用旧帧。')
        }
      })
    }
  }

  captureFrame() {
    if (!this.stream || this.opening || this.frameJob || !this.video || this.video.readyState < 2) return
    const epoch = this.cameraEpoch
    const sessionId = this.sessionId
    const captureId = this.captureId
    const capturedAt = this.env.now()
    const width = this.video.videoWidth || 640
    const height = this.video.videoHeight || 480
    const scale = Math.min(1, 640 / width, 480 / height)
    this.canvas.width = Math.round(width * scale)
    this.canvas.height = Math.round(height * scale)
    this.canvas.getContext('2d').drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height)
    const imageBase64 = this.canvas.toDataURL('image/jpeg', 0.65)
    const job = { captureId, capturedAt, abort: new AbortController() }
    this.frameJob = job
    this.pendingFrames.add(job)
    const frameId = this.env.uuid()
    let onAbort
    // Settle locally as well as aborting fetch, so a hung request cannot hold the sampling slot.
    const cancelled = new Promise((_, reject) => {
      onAbort = () => reject(new DOMException('Cancelled', 'AbortError'))
      job.abort.signal.addEventListener('abort', onAbort, { once: true })
    })
    job.timer = this.env.setTimeout(() => {
      job.timedOut = true
      job.abort.abort()
    }, FRAME_REQUEST_TIMEOUT_MS)
    job.promise = Promise.race([
      Promise.resolve().then(() => {
        if (job.abort.signal.aborted) throw new DOMException('Cancelled', 'AbortError')
        return this.api.analyzeVisionFrame(sessionId, imageBase64, {
          frame_id: frameId, capture_id: captureId, captured_at_ms: capturedAt,
        }, { signal: job.abort.signal })
      }),
      cancelled,
    ]).then(() => {
      if (!job.abort.signal.aborted && epoch === this.cameraEpoch && sessionId === this.sessionId) this.hooks.cameraError?.('')
    }).catch(error => {
      if ((job.timedOut || error.name !== 'AbortError') && epoch === this.cameraEpoch && sessionId === this.sessionId) {
        this.hooks.cameraError?.(job.timedOut ? '画面分析请求超时，后续采样会自动继续。' : error.message)
      }
    }).finally(() => {
      this.env.clearTimeout(job.timer)
      job.abort.signal.removeEventListener('abort', onAbort)
      this.pendingFrames.delete(job)
      if (this.frameJob === job) this.frameJob = null
    })
  }

  async freezeInterval(utteranceId, captureId, start, end, signal) {
    const sessionId = this.sessionId
    const epoch = this.sessionEpoch
    const jobs = [...this.pendingFrames].filter(job => job.captureId === captureId
      && start <= job.capturedAt && job.capturedAt < end)
    let timer
    try {
      await Promise.race([
        Promise.allSettled(jobs.map(job => job.promise)),
        new Promise(resolve => { timer = this.env.setTimeout(resolve, 3000) }),
      ])
    } finally { if (timer != null) this.env.clearTimeout(timer) }
    if (epoch !== this.sessionEpoch || signal?.aborted) throw new DOMException('Cancelled', 'AbortError')
    return this.api.freezeVisionSegment({
      session_id: sessionId, utterance_id: utteranceId, capture_id: captureId,
      start_ms: start, end_ms: end,
    }, { signal })
  }

  async startRecording(status) {
    if (this.record || !this.sessionId) return false
    if (status?.state !== 'ready') throw new Error('语音识别服务尚未就绪，请检查后端语音配置。')
    const Recorder = this.env.MediaRecorder
    if (!Recorder) throw new Error('当前浏览器不支持录音。')
    const epoch = ++this.recordEpoch
    const sessionEpoch = this.sessionEpoch
    const current = () => epoch === this.recordEpoch && sessionEpoch === this.sessionEpoch
    this.hooks.recording?.('preparing')
    let stream
    try {
      stream = await this.env.getUserMedia({ audio: true, video: false })
      if (!current()) { stream.getTracks().forEach(track => track.stop()); return false }
      const candidates = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4', 'audio/webm']
      const mimeType = candidates.find(type => Recorder.isTypeSupported(type)
        && status.supported_mime_types.includes(type.split(';')[0]))
      if (!mimeType) throw new Error('当前浏览器没有与后端兼容的录音格式。')
      const recorder = new Recorder(stream, { mimeType })
      const record = {
        recorder, stream, chunks: [], captureId: this.captureId,
        utteranceId: this.env.uuid(), cancelled: false,
      }
      record.done = new Promise((resolve, reject) => { record.resolve = resolve; record.reject = reject })
      record.done.catch(() => {})
      recorder.ondataavailable = event => { if (event.data.size) record.chunks.push(event.data) }
      recorder.onstop = () => {
        this.env.clearTimeout(record.timer)
        stream.getTracks().forEach(track => track.stop())
        if (this.record === record) this.record = null
        const valid = current() && !record.cancelled
        if (valid) this.hooks.recording?.('idle')
        record.resolve(valid ? {
          blob: new Blob(record.chunks, { type: recorder.mimeType }),
          utterance_id: record.utteranceId,
          speech: { capture_id: record.captureId, recording_start_ms: record.start,
            recording_end_ms: record.end },
        } : null)
      }
      recorder.onerror = event => {
        record.cancelled = true
        this.env.clearTimeout(record.timer)
        stream.getTracks().forEach(track => track.stop())
        if (this.record === record) this.record = null
        record.reject(event.error || new Error('录音失败，请重新录音。'))
        if (current()) {
          this.hooks.recording?.('idle')
          this.hooks.recordingError?.('录音失败，请重新录音。')
        }
      }
      this.record = record
      record.start = this.env.now()
      recorder.start()
      this.hooks.recording?.('recording')
      this.captureFrame()
      record.timer = this.env.setTimeout(() => this.hooks.limit?.(),
        Math.max(1, Math.min(60, status.max_duration_seconds) * 1000 - 50))
      return true
    } catch (error) {
      stream?.getTracks().forEach(track => track.stop())
      if (current()) {
        this.record = null
        this.hooks.recording?.('idle')
        throw error
      }
      return false
    }
  }

  stopRecording(cancel = false) {
    const record = this.record
    if (!record) {
      this.recordEpoch++ // Invalidate a pending microphone permission prompt.
      this.hooks.recording?.('idle')
      return Promise.resolve(null)
    }
    record.cancelled ||= cancel
    if (record.recorder.state !== 'inactive') {
      record.end = this.env.now()
      record.recorder.stop()
    }
    return record.done
  }

  cancelRecording() {
    this.stopRecording(true).catch(() => {})
    this.recordEpoch++
    this.hooks.recording?.('idle')
  }
}
