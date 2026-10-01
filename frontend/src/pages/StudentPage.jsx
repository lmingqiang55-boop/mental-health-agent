// 学生端页面：实时对话闭环 + 结果展示。
// 下一步提问由后端决策模型决定；学生显式触发综合评估后展示结果。

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
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
  const [visionOn, setVisionOn] = useState(false)
  const [cameraError, setCameraError] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef(null)
  const pendingRef = useRef(false)
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const captureTimerRef = useRef(null)
  const frameBusyRef = useRef(false)

  const createSession = useCallback(async () => {
    if (pendingRef.current) return
    pendingRef.current = true
    stopCamera()
    setBusy(true); setError('')
    try {
      const data = await api.createSession()
      setSessionId(data.session_id)
      setMessages([]); setInput(''); setTurnCount(0)
      setStage('exploration'); setRisk('low')
      setResult(null)
    } catch (e) { setError(e.message) }
    finally { pendingRef.current = false; setBusy(false) }
  }, [])

  useEffect(() => { createSession() }, [createSession])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function send(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || !sessionId || pendingRef.current) return
    pendingRef.current = true
    setBusy(true); setError(''); setInput('')
    try {
      const data = await api.sendChat(sessionId, text)
      setMessages(prev => [...prev,
        { role: 'user', content: text },
        { role: 'assistant', content: data.reply }])
      setTurnCount(data.turn_count)
      setStage(data.current_stage)
      setRisk(data.risk.risk_level)
    } catch (e) {
      setInput(text)
      if (e.status === 404) {
        setError('会话已过期，正在创建新会话…')
        setTimeout(createSession, 800)
      } else {
        setError(e.message)
      }
    } finally { pendingRef.current = false; setBusy(false) }
  }

  // 对话由决策模型一直进行，没有自动结束信号，因此由学生显式触发评估。
  async function finishAssessment() {
    if (!sessionId || pendingRef.current) return
    pendingRef.current = true
    setBusy(true); setError('')
    try {
      const data = await api.triggerAssessment(sessionId)
      setResult(data.result)
      const session = await api.getSession(sessionId)
      setStage(session.current_stage)
    } catch (e) { setError(e.message) }
    finally { pendingRef.current = false; setBusy(false) }
  }

  async function captureVisionFrame() {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || !sessionId || video.readyState < 2 || frameBusyRef.current) return
    const width = video.videoWidth || 640
    const height = video.videoHeight || 480
    canvas.width = width
    canvas.height = height
    canvas.getContext('2d').drawImage(video, 0, 0, width, height)
    frameBusyRef.current = true
    try {
      await api.analyzeVisionFrame(sessionId, canvas.toDataURL('image/jpeg', 0.65))
    } catch (e) {
      if (e.status !== 404) setCameraError(e.message)
    } finally {
      frameBusyRef.current = false
    }
  }

  function stopCamera() {
    if (captureTimerRef.current) clearInterval(captureTimerRef.current)
    captureTimerRef.current = null
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setVisionOn(false)
  }

  async function toggleVision() {
    if (visionOn) {
      stopCamera()
      return
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError('当前浏览器不支持摄像头访问。')
      return
    }
    setCameraError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      })
      streamRef.current = stream
      videoRef.current.srcObject = stream
      await videoRef.current.play()
      setVisionOn(true)
      captureTimerRef.current = setInterval(captureVisionFrame, 1500)
      captureVisionFrame()
    } catch (e) {
      setCameraError(e.name === 'NotAllowedError' ? '未获得摄像头权限。' : '无法打开摄像头。')
      stopCamera()
    }
  }
  useEffect(() => () => stopCamera(), [])

  const showCrisis = risk === 'high'

  return (
    <div className="student-page">
      <header className="page-header">
        <div>
          <h1>心理状态初步筛查</h1>
          <p>通过简短对话记录近期状态 · 框架演示版</p>
        </div>
        <div className="header-actions">
          <button type="button" className="secondary" onClick={toggleVision}>
            {visionOn ? '关闭摄像头' : '开启摄像头'}
          </button>
          <button type="button" className="secondary" disabled>语音功能待接入</button>
          <button type="button" onClick={finishAssessment}
            disabled={busy || !sessionId || turnCount === 0}>生成初步结果</button>
          <button type="button" className="secondary" onClick={createSession}
            disabled={busy}>重新开始</button>
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
          <form onSubmit={send}>
            <div className="composer">
              <input value={input} onChange={e => setInput(e.target.value)}
                placeholder="例如：最近总是觉得压力很大、睡不好"
                maxLength={4000} disabled={!sessionId || busy} />
              <button type="submit" disabled={!input.trim() || !sessionId || busy}>
                {busy ? '处理中…' : '发送'}
              </button>
            </div>
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
            <p className="device-hint">仅按间隔上传压缩帧用于即时分析，不保存原始画面。</p>
          </section>
          <DeviceStatus visionEnabled={visionOn} audioEnabled={false}
            cameraError={cameraError} />
        </aside>
      </div>

      {result && <AssessmentResultView result={result} />}
    </div>
  )
}
