import { useEffect, useRef, useState } from 'react'

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.error?.message || '请求失败，请稍后重试。')
  }
  return data
}

export default function App() {
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [turnCount, setTurnCount] = useState(0)
  const [stage, setStage] = useState('exploration')
  const [risk, setRisk] = useState('low')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef(null)
  const pendingRef = useRef(false)

  async function createSession() {
    if (pendingRef.current) return
    pendingRef.current = true
    setBusy(true)
    setError('')
    try {
      const data = await api('/api/session', { method: 'POST' })
      setSessionId(data.session_id)
      setMessages([])
      setInput('')
      setTurnCount(0)
      setStage('exploration')
      setRisk('low')
    } catch (caught) {
      setError(caught.message)
    } finally {
      pendingRef.current = false
      setBusy(false)
    }
  }

  useEffect(() => { createSession() }, [])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function send(event) {
    event.preventDefault()
    const text = input.trim()
    if (!text || !sessionId || pendingRef.current) return
    pendingRef.current = true
    setBusy(true)
    setError('')
    setInput('')
    try {
      const data = await api('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, text }),
      })
      setMessages(previous => [...previous,
        { role: 'user', content: text },
        { role: 'assistant', content: data.reply },
      ])
      setTurnCount(data.turn_count)
      setStage(data.current_stage)
      setRisk(data.risk.risk_level)
    } catch (caught) {
      setInput(text)
      setError(caught.message)
    } finally {
      pendingRef.current = false
      setBusy(false)
    }
  }

  return (
    <main className="app">
      <header>
        <div>
          <h1>心理状态初步筛查</h1>
          <p>通过简短对话记录近期状态 · v0.1 演示版</p>
        </div>
        <button type="button" onClick={createSession} disabled={busy}>创建新会话</button>
      </header>

      <div className="layout">
        <section className="chat-panel" aria-label="对话区域">
          <div className="messages" aria-live="polite">
            {messages.length === 0 && <p className="empty">可以从最近的心情、睡眠或精力变化开始说起。</p>}
            {messages.map((message, index) => (
              <div className={`message ${message.role}`} key={index}>
                <span className="speaker">{message.role === 'user' ? '你' : '助手'}</span>
                <p>{message.content}</p>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          <form onSubmit={send}>
            <label htmlFor="message-input">输入消息</label>
            <div className="composer">
              <input id="message-input" value={input} onChange={event => setInput(event.target.value)}
                placeholder="例如：最近总是觉得没什么精神" maxLength={4000} disabled={!sessionId || busy} />
              <button type="submit" disabled={!input.trim() || !sessionId || busy}>{busy ? '处理中…' : '发送'}</button>
            </div>
          </form>
        </section>

        <aside aria-label="会话状态">
          <h2>会话状态</h2>
          <dl>
            <dt>Session ID</dt><dd className="session-id">{sessionId || '创建中…'}</dd>
            <dt>Turn Count</dt><dd>{turnCount}</dd>
            <dt>Current Stage</dt><dd>{stage}</dd>
            <dt>Risk Level</dt><dd>{risk}</dd>
          </dl>
          <p className="note">本工具仅作演示和初步风险提示，不提供临床诊断。遇到紧急危险，请联系当地急救服务。</p>
        </aside>
      </div>
    </main>
  )
}
