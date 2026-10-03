import test from 'node:test'
import assert from 'node:assert/strict'
import { CaptureController } from './capture.js'

const deferred = () => {
  let resolve
  const promise = new Promise(r => { resolve = r })
  return { promise, resolve }
}
const tick = () => new Promise(resolve => setImmediate(resolve))

function fixture() {
  let clock = 100, id = 0
  const timers = new Map(), timeouts = new Map(), permissions = [], streams = [], captureCalls = [], frameCalls = [], segments = []
  const recorderInstances = []
  class Recorder {
    static isTypeSupported(type) { return type.startsWith('audio/webm') }
    constructor(stream, options) { this.stream = stream; this.mimeType = options.mimeType; this.state = 'inactive'; recorderInstances.push(this) }
    start() { this.state = 'recording' }
    stop() {
      this.state = 'inactive'
      queueMicrotask(() => {
        this.ondataavailable?.({ data: new Blob(['last chunk']) })
        this.onstop?.()
      })
    }
  }
  const api = {
    setVisionCapture: async (...args) => { captureCalls.push(args) },
    analyzeVisionFrame: async (...args) => { frameCalls.push(args) },
    freezeVisionSegment: async body => { segments.push(body); return { vision_snapshot: null } },
  }
  const states = [], errors = []
  const controller = new CaptureController(api, { camera: s => states.push(s), cameraError: e => errors.push(e) }, {
    now: () => clock, uuid: () => `id-${++id}`, MediaRecorder: Recorder,
    getUserMedia: () => { const request = deferred(); permissions.push(request); return request.promise },
    setInterval: fn => { const id = Symbol(); timers.set(id, fn); return id },
    clearInterval: id => timers.delete(id),
    setTimeout: (fn, ms) => { const id = Symbol(); timers.set(id, fn); timeouts.set(id, { fn, ms }); return id },
    clearTimeout: id => { timers.delete(id); timeouts.delete(id) },
  })
  const stream = () => {
    const result = { stopped: false, getTracks: () => [{ stop: () => { result.stopped = true } }] }
    streams.push(result); return result
  }
  const video = { readyState: 2, videoWidth: 1920, videoHeight: 1080, play: async () => {} }
  const canvas = { getContext: () => ({ drawImage: () => {} }), toDataURL: () => 'frame' }
  controller.resetSession('session')
  const expireTimeout = ms => {
    const entry = [...timeouts].find(([, timeout]) => timeout.ms === ms)
    assert.ok(entry, `No pending ${ms} ms timeout`)
    const [id, timeout] = entry
    timers.delete(id); timeouts.delete(id)
    timeout.fn()
  }
  return { controller, api, video, canvas, permissions, stream, streams, timers, states, errors, expireTimeout,
    frameCalls, captureCalls, segments, recorderInstances, setClock: value => { clock = value } }
}

const status = { state: 'ready', max_duration_seconds: 60, supported_mime_types: ['audio/webm'] }

test('native timer wrappers retain their global receiver in a browser', () => {
  const previous = globalThis.setInterval
  globalThis.setInterval = function () { assert.equal(this, globalThis); return 42 }
  try {
    const controller = new CaptureController({}, {}, { uuid: () => 'id' })
    assert.equal(controller.env.setInterval(() => {}, 500), 42)
  } finally { globalThis.setInterval = previous }
})

test('duplicate camera opening creates one stream and shutdown releases all timers', async () => {
  const f = fixture()
  const first = f.controller.openCamera(f.video, f.canvas)
  await f.controller.openCamera(f.video, f.canvas)
  assert.equal(f.permissions.length, 1)
  f.permissions[0].resolve(f.stream())
  await first; await tick()
  assert.equal(f.timers.size, 1)
  assert.equal(f.frameCalls.length, 1)
  assert.equal(f.canvas.width, 640)
  f.controller.stopCamera()
  assert.equal(f.timers.size, 0)
  assert.ok(f.streams.every(s => s.stopped))
})

test('restart while waiting for camera permission invalidates the old stream', async () => {
  const f = fixture()
  const opening = f.controller.openCamera(f.video, f.canvas)
  f.controller.resetSession('new-session')
  f.permissions[0].resolve(f.stream())
  await opening
  assert.ok(f.streams[0].stopped)
  assert.equal(f.timers.size, 0)
  assert.equal(f.frameCalls.length, 0)
  assert.equal(f.controller.stream, null)
})

test('close during backend capture startup leaves no timer or live stream', async () => {
  const f = fixture(), start = deferred()
  f.api.setVisionCapture = async (...args) => { f.captureCalls.push(args); if (args[3]) await start.promise }
  const opening = f.controller.openCamera(f.video, f.canvas)
  f.permissions[0].resolve(f.stream())
  await tick()
  f.controller.stopCamera()
  start.resolve()
  await opening
  assert.equal(f.timers.size, 0)
  assert.ok(f.streams[0].stopped)
  assert.equal(f.captureCalls.at(-1)[3], false)
  assert.ok(f.captureCalls.at(-1)[2] > f.captureCalls.at(-2)[2])
})

test('permission delay is excluded and stop waits for the final audio chunk', async () => {
  const f = fixture()
  const starting = f.controller.startRecording(status)
  f.setClock(5000)
  f.permissions[0].resolve(f.stream())
  assert.equal(await starting, true)
  f.setClock(5500)
  const result = await f.controller.stopRecording()
  assert.equal(result.speech.recording_start_ms, 5000)
  assert.equal(result.speech.recording_end_ms, 5500)
  assert.equal(await result.blob.text(), 'last chunk')
  assert.ok(f.streams[0].stopped)
  assert.equal(f.timers.size, 0)
})

test('release during microphone permission prevents a late recording', async () => {
  const f = fixture()
  const starting = f.controller.startRecording(status)
  assert.equal(await f.controller.stopRecording(), null)
  f.permissions[0].resolve(f.stream())
  assert.equal(await starting, false)
  assert.ok(f.streams[0].stopped)
  assert.equal(f.recorderInstances.length, 0)
})

test('cancel and session restart discard audio without leaving a microphone live', async () => {
  for (const restart of [false, true]) {
    const f = fixture()
    const starting = f.controller.startRecording(status)
    f.permissions[0].resolve(f.stream()); await starting
    const done = f.controller.record.done
    if (restart) f.controller.resetSession('new-session')
    else f.controller.cancelRecording()
    assert.equal(await done, null)
    assert.ok(f.streams[0].stopped)
    assert.equal(f.timers.size, 0)
  }
})

test('matching in-flight frame is awaited before freezing the interval', async () => {
  const f = fixture(), response = deferred()
  f.api.analyzeVisionFrame = (...args) => { f.frameCalls.push(args); return response.promise }
  const opening = f.controller.openCamera(f.video, f.canvas)
  f.permissions[0].resolve(f.stream()); await opening
  const frozen = f.controller.freezeInterval('u1', f.controller.captureId, 100, 200)
  await tick()
  assert.equal(f.segments.length, 0)
  response.resolve(); await frozen
  assert.equal(f.segments.length, 1)
  assert.equal(f.segments[0].start_ms, 100)
  f.controller.stopCamera()
})

test('a delayed old frame cannot clear the new camera request or report an old error', async () => {
  const f = fixture(), old = deferred(), fresh = deferred()
  let call = 0
  f.api.analyzeVisionFrame = () => ++call === 1 ? old.promise : fresh.promise
  const first = f.controller.openCamera(f.video, f.canvas)
  f.permissions[0].resolve(f.stream()); await first
  f.controller.stopCamera()
  const second = f.controller.openCamera(f.video, f.canvas)
  f.permissions[1].resolve(f.stream()); await second
  const current = f.controller.frameJob
  old.resolve(); await tick()
  assert.equal(f.controller.frameJob, current)
  assert.equal(f.controller.pendingFrames.size, 1)
  fresh.resolve(); await tick()
  f.controller.stopCamera()
})

test('hung frame times out after interval freeze and sampling recovers despite a late response', async () => {
  const f = fixture(), old = deferred(), fresh = deferred()
  f.api.analyzeVisionFrame = (...args) => {
    f.frameCalls.push(args)
    return f.frameCalls.length === 1 ? old.promise : fresh.promise
  }
  const opening = f.controller.openCamera(f.video, f.canvas)
  f.permissions[0].resolve(f.stream()); await opening; await tick()
  const first = f.controller.frameJob
  const frozen = f.controller.freezeInterval('u1', f.controller.captureId, 100, 200)
  f.expireTimeout(3000)
  assert.equal((await frozen).vision_snapshot, null)
  assert.equal(f.controller.frameJob, first)

  f.expireTimeout(10_000)
  await tick()
  assert.equal(f.frameCalls[0][3].signal.aborted, true)
  assert.equal(f.controller.frameJob, null)
  assert.equal(f.controller.pendingFrames.size, 0)
  assert.match(f.errors.at(-1), /超时/)
  assert.equal(f.timers.size, 1) // The camera interval remains active.

  f.setClock(200)
  f.controller.captureFrame(); await tick()
  const current = f.controller.frameJob
  assert.equal(f.frameCalls.length, 2)
  old.resolve(); await tick()
  assert.equal(f.controller.frameJob, current)
  assert.equal(f.controller.pendingFrames.size, 1)
  assert.match(f.errors.at(-1), /超时/)
  assert.equal(f.segments.length, 1)
  fresh.resolve(); await tick()
  assert.equal(f.errors.at(-1), '')
  assert.equal(f.controller.frameJob, null)
  assert.equal(f.timers.size, 1)
  f.controller.stopCamera()
  assert.equal(f.timers.size, 0)
})

test('closing a camera clears the deadline and pending job even when the API ignores abort', async () => {
  const f = fixture()
  f.api.analyzeVisionFrame = () => new Promise(() => {})
  const opening = f.controller.openCamera(f.video, f.canvas)
  f.permissions[0].resolve(f.stream()); await opening; await tick()
  const pending = f.controller.frameJob.promise
  f.controller.stopCamera()
  assert.equal(f.timers.size, 0)
  await pending
  assert.equal(f.controller.pendingFrames.size, 0)
  assert.equal(f.controller.frameJob, null)
  assert.equal(f.errors.length, 0)
})
