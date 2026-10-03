// Text and hold-to-record input share frozen per-utterance visual snapshots.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { CaptureController } from '../media/capture'
import DeviceStatus from '../components/DeviceStatus'
import AssessmentResultView from '../components/AssessmentResultView'

export default function StudentPage() {
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [turnCount, setTurnCount] = useState(0)
  const [stage, setStage] = useState('exploration')
  const [risk, setRisk] = useState('low')
  const [result, setResult] = useState(null)
  const [cameraState, setCameraState] = useState('off')
  const [cameraError, setCameraError] = useState('')
  const [recordState, setRecordState] = useState('idle')
  const [audioStatus, setAudioStatus] = useState(null)
  const [retryJob, setRetryJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [sendingChat, setSendingChat] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef(null)
  const pendingRef = useRef(false)
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const mediaRef = useRef(null)
  const flowRef = useRef(0)
  const abortRef = useRef(null)
  const retryRef = useRef(null)
  const typingStartRef = useRef(null)
  const gestureRef = useRef(null)
  const stopSpeechRef = useRef(null)
  if (!mediaRef.current) {
    mediaRef.current = new CaptureController(api, {
      camera: setCameraState, cameraError: setCameraError, recording: setRecordState,
      recordingError: message => { setError(message); pendingRef.current = false; setBusy(false) },
      limit: () => stopSpeechRef.current?.(),
    })
  }
  const visionOn = cameraState === 'on'
  const recording = recordState === 'recording' || recordState === 'preparing'

  const createSession = useCallback(async () => {
    const flow = ++flowRef.current
    abortRef.current?.abort()
    mediaRef.current.resetSession('')
    pendingRef.current = true
    retryRef.current = null
    gestureRef.current = null
    typingStartRef.current = null
    setRetryJob(null); setSessionId(''); setCameraError('')
    setBusy(true); setSendingChat(false); setError('')
    setMessages([]); setInput(''); setTurnCount(0); setResult(null)
    setStage('exploration'); setRisk('low')
    try {
      const data = await api.createSession()
      if (flow !== flowRef.current) return
      mediaRef.current.resetSession(data.session_id)
      setSessionId(data.session_id)
    } catch (e) { if (flow === flowRef.current) setError(e.message) }
    finally {
      if (flow === flowRef.current) { pendingRef.current = false; setBusy(false) }
    }
  }, [])

  useEffect(() => {
    createSession()
    let mounted = true
    api.audioStatus().then(data => { if (mounted) setAudioStatus(data) }).catch(() => {})
    const cancelOnBlur = () => {
      if (gestureRef.current && !gestureRef.current.released) stopSpeechRef.current?.(true)
    }
    window.addEventListener('blur', cancelOnBlur)
    return () => {
      mounted = false
      flowRef.current++
      abortRef.current?.abort()
      mediaRef.current.resetSession('')
      window.removeEventListener('blur', cancelOnBlur)
    }
  }, [createSession])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  function rememberRetry(job) {
    retryRef.current = job
    setRetryJob(job)
  }

  async function executeJob(job) {
    if (job.sessionId !== mediaRef.current.sessionId) return
    const flow = flowRef.current
    const abort = new AbortController()
    abortRef.current = abort
    pendingRef.current = true
    setBusy(true); setError('')
    try {
      if (!job.body) {
        const vision = job.vision ? Promise.resolve(job.vision) :
          mediaRef.current.freezeInterval(job.utteranceId, job.captureId, job.start, job.end,
            abort.signal).then(data => { job.vision = data; return data })
        let text = Promise.resolve(job.text)
        if (job.kind === 'audio' && !job.text) {
          const form = new FormData()
          const mime = job.blob.type.split(';')[0]
          const extension = mime === 'audio/mp4' ? 'm4a' : mime === 'audio/ogg' ? 'ogg' : 'webm'
          form.append('file', job.blob, `recording.${extension}`)
          form.append('session_id', job.sessionId)
          form.append('utterance_id', job.utteranceId)
          form.append('capture_id', job.captureId)
          form.append('recording_start_ms', String(job.start))
          form.append('recording_end_ms', String(job.end))
          text = api.transcribe(form, { signal: abort.signal }).then(data => {
            if (data.session_id !== job.sessionId || data.utterance_id !== job.utteranceId
              || data.speech.capture_id !== job.captureId
              || data.speech.recording_start_ms !== job.start || data.speech.recording_end_ms !== job.end) {
              throw new Error('识别结果与本次录音不一致，请重新录音。')
            }
            job.text = data.text
            return data.text
          })
        }
        const [aligned, transcript] = await Promise.all([vision, text])
        job.body = { utterance_id: job.utteranceId, vision_snapshot: aligned.vision_snapshot }
        if (job.kind === 'audio') job.body.speech = {
          capture_id: job.captureId, recording_start_ms: job.start, recording_end_ms: job.end,
        }
        job.text = transcript
      }
      if (flow !== flowRef.current || abort.signal.aborted) return
      job.stage = 'chat'
      setSendingChat(true)
      const data = await api.sendChat(job.sessionId, job.text, job.body, { signal: abort.signal })
      if (flow !== flowRef.current) return
      setMessages(prev => [...prev, { role: 'user', content: job.text },
        { role: 'assistant', content: data.reply }])
      setTurnCount(data.turn_count); setStage(data.current_stage); setRisk(data.risk.risk_level)
      setResult(null); setInput(''); typingStartRef.current = null
      rememberRetry(null)
    } catch (e) {
      abort.abort()
      if (flow !== flowRef.current || e.name === 'AbortError') return
      job.uncertain = job.stage === 'chat' && e.status == null
      rememberRetry(job)
      setError(e.status === 404 ? '会话已过期，请点击重新开始。' :
        job.uncertain ? '发送状态不明，请重试确认本次结果，或重新开始会话。' : e.message)
    } finally {
      if (flow === flowRef.current) { pendingRef.current = false; setBusy(false); setSendingChat(false) }
    }
  }

  async function send(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || !sessionId || pendingRef.current || retryRef.current) return
    const end = performance.now()
    const start = Math.max(0, end - 60_000, typingStartRef.current ?? end - 2000)
    const job = { kind: 'text', sessionId, text, utteranceId: crypto.randomUUID(),
      captureId: mediaRef.current.captureId, start, end }
    // A stopped camera must not lend its last observation to a new text turn.
    if (!visionOn) job.vision = { vision_snapshot: null }
    await executeJob(job)
  }

  async function beginSpeech() {
    if (!sessionId || pendingRef.current || retryRef.current) return
    const gesture = { flow: flowRef.current, released: false }
    gestureRef.current = gesture
    pendingRef.current = true
    setBusy(true); setError('')
    try {
      const started = await mediaRef.current.startRecording(audioStatus)
      if (!started && gesture === gestureRef.current && !gesture.released) {
        pendingRef.current = false; setBusy(false)
      }
    } catch (e) {
      if (gesture === gestureRef.current) {
        gesture.released = true
        setError(e.name === 'NotAllowedError' ? '未获得麦克风权限。' : e.message)
        pendingRef.current = false; setBusy(false)
      }
    }
  }

  async function stopSpeech(cancel = false) {
    const gesture = gestureRef.current
    if (!gesture || gesture.released) return
    gesture.released = true
    try {
      const recording = await mediaRef.current.stopRecording(cancel)
      if (gesture.flow !== flowRef.current) return
      if (!recording) { pendingRef.current = false; setBusy(false); return }
      const { speech } = recording
      await executeJob({ kind: 'audio', sessionId: mediaRef.current.sessionId,
        blob: recording.blob, utteranceId: recording.utterance_id,
        captureId: speech.capture_id, start: speech.recording_start_ms,
        end: speech.recording_end_ms })
    } catch (e) {
      if (gesture.flow === flowRef.current) {
        setError(e.message); pendingRef.current = false; setBusy(false)
      }
    }
  }
  stopSpeechRef.current = stopSpeech

  function cancelPending() {
    if (sendingChat || retryRef.current?.uncertain) return
    flowRef.current++
    abortRef.current?.abort()
    mediaRef.current.cancelRecording()
    gestureRef.current = null
    rememberRetry(null)
    pendingRef.current = false
    setBusy(false); setError('')
  }

  async function finishAssessment() {
    if (!sessionId || pendingRef.current || retryRef.current) return
    const flow = flowRef.current
    pendingRef.current = true
    setBusy(true); setError('')
    try {
      const data = await api.triggerAssessment(sessionId)
      if (flow !== flowRef.current) return
      setResult(data.result)
      const session = await api.getSession(sessionId)
      if (flow === flowRef.current) setStage(session.current_stage)
    } catch (e) { if (flow === flowRef.current) setError(e.message) }
    finally {
      if (flow === flowRef.current) { pendingRef.current = false; setBusy(false) }
    }
  }

  function toggleVision() {
    if (pendingRef.current || retryRef.current) return
    typingStartRef.current = null
    setCameraError('')
    if (cameraState !== 'off') mediaRef.current.stopCamera()
    else mediaRef.current.openCamera(videoRef.current, canvasRef.current)
  }

  const showCrisis = risk === 'high'

  return (
    <div className="student-page">
      <header className="page-header">
        <div>
          <h1>心理状态初步筛查</h1>
          <p>通过简短对话记录近期状态 · 框架演示版</p>
        </div>
        <div className="header-actions">
          <button type="button" className="secondary" onClick={toggleVision} disabled={busy || !sessionId || !!retryJob}>
            {cameraState === 'opening' ? '取消开启摄像头' : visionOn ? '关闭摄像头' : '开启摄像头'}
          </button>
          <button type="button" className={`speech-button ${recording ? 'recording' : 'secondary'}`}
            disabled={!sessionId || !!retryJob || (busy && !recording) || cameraState === 'opening'}
            onPointerDown={e => {
              if (e.button !== 0) return
              e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); beginSpeech()
            }}
            onPointerUp={() => stopSpeech()}
            onPointerCancel={() => stopSpeech(true)}
            onLostPointerCapture={() => stopSpeech(true)}
            onKeyDown={e => { if ([' ', 'Enter'].includes(e.key) && !e.repeat) { e.preventDefault(); beginSpeech() } }}
            onKeyUp={e => { if ([' ', 'Enter'].includes(e.key)) { e.preventDefault(); stopSpeech() } }}>
            {recordState === 'preparing' ? '等待麦克风…' : recordState === 'recording' ? '松开发送' : '按住说话'}
          </button>
          {(recording || (busy && !!abortRef.current && !sendingChat)) && <button type="button" className="secondary"
            onClick={cancelPending}>取消本次输入</button>}
          <button type="button" onClick={finishAssessment}
            disabled={busy || !!retryJob || !sessionId || turnCount === 0}>生成初步结果</button>
          <button type="button" className="secondary" onClick={createSession}>重新开始</button>
        </div>
      </header>

      {showCrisis && (
        <div className="crisis-banner" role="alert">
          检测到你可能正处于危机中，请立即联系身边可信任的人或拨打急救电话。你不是一个人。
        </div>
      )}

      <div className="student-layout">
        <section className="chat-panel card">
          <div className="messages" aria-live="polite">
            {messages.length === 0 && (
              <p className="empty">可以从最近的心情、压力、睡眠或人际状态开始说起。</p>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`message ${m.role}`}>
                <span className="speaker">{m.role === 'user' ? '你' : '助手'}</span>
                <p>{m.content}</p>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          {retryJob && <div className="retry-input">
            <p>{retryJob.text || '本次录音尚未成功转写。'}</p>
            <button type="button" disabled={busy} onClick={() => executeJob(retryRef.current)}>
              {retryJob.body ? '重试发送' : '重试本次输入'}
            </button>
            <button type="button" className="secondary" disabled={busy || retryJob.uncertain} onClick={cancelPending}>放弃本次</button>
          </div>}
          <form onSubmit={send}>
            <div className="composer">
              <input value={input} onChange={e => {
                if (typingStartRef.current == null && e.target.value.trim()) typingStartRef.current = performance.now()
                if (!e.target.value.trim()) typingStartRef.current = null
                setInput(e.target.value)
              }}
                placeholder="例如：最近总是觉得压力很大、睡不好"
                maxLength={4000} disabled={!sessionId || busy || !!retryJob || cameraState === 'opening'} />
              <button type="submit" disabled={!input.trim() || !sessionId || busy || !!retryJob || cameraState === 'opening'}>
                {busy ? '处理中…' : '发送'}
              </button>
            </div>
            <p className="device-hint">按住「按住说话」录音，松开后自动发送；最长 {audioStatus?.max_duration_seconds ?? 60} 秒。
              {audioStatus && audioStatus.state !== 'ready' && ' 语音服务尚未就绪，仍可使用文字输入。'}</p>
          </form>
        </section>

        <aside className="sidebar">
          <section className="card session-summary">
            <h3>会话状态</h3>
            <dl>
              <dt>回合数</dt><dd>{turnCount}</dd>
              <dt>当前阶段</dt><dd>{stage}</dd>
              <dt>风险等级</dt>
              <dd className={`risk-text risk-${risk}`}>
                {risk === 'low' ? '低' : risk === 'medium' ? '中' : '高'}
              </dd>
            </dl>
            <p className="device-hint">对话没有自动结束条件，确认聊完后点「生成初步结果」。</p>
          </section>
          <section className="card camera-preview">
            <h3>摄像头预览</h3>
            <video ref={videoRef} muted playsInline aria-label="摄像头预览" />
            <canvas ref={canvasRef} className="capture-canvas" />
            {cameraError && <p className="error" role="alert">{cameraError}</p>}
            <p className="device-hint">采集帧按本次发言的时间区间聚合，不保存原始画面；没有有效画面时保持缺测。</p>
          </section>
          <DeviceStatus visionEnabled={visionOn} audioEnabled={recordState === 'recording'}
            cameraError={cameraError} />
        </aside>
      </div>

      {result && <AssessmentResultView result={result} />}
    </div>
  )
}
