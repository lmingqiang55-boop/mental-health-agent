// 学生端页面：实时对话闭环 + 结果展示。

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import DimensionProgress from '../components/DimensionProgress'
import DeviceStatus from '../components/DeviceStatus'
import AssessmentResultView from '../components/AssessmentResultView'

const DIMENSION_LABELS = {
  mood: '情绪', pressure: '压力', interpersonal: '人际关系',
  self_cognition: '自我认知', study_life: '学习生活', duration: '持续时间',
}

export default function StudentPage() {
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [turnCount, setTurnCount] = useState(0)
  const [stage, setStage] = useState('exploration')
  const [risk, setRisk] = useState('low')
  const [assessmentState, setAssessmentState] = useState({})
  const [result, setResult] = useState(null)
  const [visionOn, setVisionOn] = useState(false)
  const [audioOn, setAudioOn] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef(null)
  const pendingRef = useRef(false)

  const createSession = useCallback(async () => {
    if (pendingRef.current) return
    pendingRef.current = true
    setBusy(true); setError('')
    try {
      const data = await api.createSession()
      setSessionId(data.session_id)
      setMessages([]); setInput(''); setTurnCount(0)
      setStage('exploration'); setRisk('low')
      setAssessmentState({}); setResult(null)
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

      const session = await api.getSession(sessionId)
      setAssessmentState(session.assessment_state)

      if (data.next_strategy === 'finish_assessment' && session.assessment_result_id) {
        const resData = await api.getResult(session.assessment_result_id, sessionId)
        setResult(resData.result)
      }
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

  // 框架阶段：模拟设备开关，提交 Mock 多模态状态
  async function toggleVision() {
    const next = !visionOn
    setVisionOn(next)
    if (next && sessionId) {
      await api.submitVision(sessionId, {
        emotion: 'neutral', emotion_confidence: 0.78,
        valence: -0.15, arousal: 0.35, engagement: 0.65,
        attention_score: 0.6, face_detected: true,
      })
    }
  }
  async function toggleAudio() {
    const next = !audioOn
    setAudioOn(next)
    if (next && sessionId) {
      await api.submitAudio(sessionId, {
        speech_rate: 0.7, pause_ratio: 0.3, energy: 0.45,
        pitch_mean: 0.5, audio_available: true,
      })
    }
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
          <button type="button" className="secondary" onClick={toggleVision}>
            {visionOn ? '关闭摄像头' : '开启摄像头'}
          </button>
          <button type="button" className="secondary" onClick={toggleAudio}>
            {audioOn ? '关闭麦克风' : '开启麦克风'}
          </button>
          <button type="button" onClick={createSession} disabled={busy}>重新开始</button>
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
          </section>
          <DimensionProgress assessmentState={assessmentState} />
          <DeviceStatus visionEnabled={visionOn} audioEnabled={audioOn} />
        </aside>
      </div>

      {result && <AssessmentResultView result={result} />}
    </div>
  )
}
