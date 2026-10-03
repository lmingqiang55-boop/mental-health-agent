import test from 'node:test'
import assert from 'node:assert/strict'
import { api } from './client.js'

test('session creation reuses the anonymous student reference', async () => {
  const previous = globalThis.fetch
  let body
  globalThis.fetch = async (_, options) => {
    body = JSON.parse(options.body)
    return { ok: true, json: async () => ({ session_id: 'new-session', student_ref: body.student_ref }) }
  }
  try {
    const response = await api.createSession('anon-123')
    assert.equal(body.student_ref, 'anon-123')
    assert.equal(response.student_ref, 'anon-123')
  } finally { globalThis.fetch = previous }
})

test('multipart upload lets the browser supply its own boundary', async () => {
  const previous = globalThis.fetch
  let call
  globalThis.fetch = async (...args) => { call = args; return { ok: true, json: async () => ({ text: '没有' }) } }
  try {
    const form = new FormData()
    form.append('file', new Blob(['audio'], { type: 'audio/webm' }), 'recording.webm')
    const signal = new AbortController().signal
    await api.transcribe(form, { signal })
    assert.equal(call[0], '/api/audio/transcribe')
    assert.equal(call[1].body, form)
    assert.equal(call[1].headers['Content-Type'], undefined)
    assert.equal(call[1].signal, signal)
  } finally { globalThis.fetch = previous }
})

test('chat sends visual and speech metadata without replacing the session or text', async () => {
  const previous = globalThis.fetch
  let body
  globalThis.fetch = async (path, options) => {
    body = JSON.parse(options.body)
    assert.equal(options.headers['Content-Type'], 'application/json')
    return { ok: true, json: async () => ({ turn_count: 1 }) }
  }
  try {
    await api.sendChat('session', '没有', { session_id: 'wrong', text: 'wrong',
      utterance_id: 'u1', vision_snapshot: null,
      speech: { capture_id: 'capture', recording_start_ms: 10, recording_end_ms: 20 } })
    assert.equal(body.session_id, 'session')
    assert.equal(body.text, '没有')
    assert.equal(body.utterance_id, 'u1')
    assert.equal(body.vision_snapshot, null)
    assert.equal(body.speech.recording_end_ms, 20)
  } finally { globalThis.fetch = previous }
})
