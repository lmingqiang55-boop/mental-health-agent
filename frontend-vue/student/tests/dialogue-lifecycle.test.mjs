import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { SourceTextModule, SyntheticModule, createContext } from 'node:vm'
import ts from 'typescript'
import { ref } from 'vue'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

async function load(name, api, globals = {}) {
  const intervals = new Map()
  const cleanup = []
  let nextTimer = 0
  const clock = { now: () => 10_000 }
  const context = createContext({
    AbortController, Blob, Error, URL, performance: clock,
    window: {
      setInterval: (fn) => { intervals.set(++nextTimer, fn); return nextTimer },
      clearInterval: (id) => intervals.delete(id),
    },
    ...globals,
  })
  const source = await readFile(new URL(`../src/composables/${name}.ts`, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  const dependencies = {
    vue: { ref, onUnmounted: (fn) => cleanup.push(fn) },
    '@/api': api,
    '@/api/http': { isApiError: (e, code) => !!e?.code && (!code || code === e.code) },
    '@/utils/id': { newFrameId: () => 'frame-test' },
  }
  const module = new SourceTextModule(compiled, { context })
  await module.link((specifier) => {
    const exports = dependencies[specifier]
    assert.ok(exports, `Unexpected import ${specifier}`)
    return new SyntheticModule(Object.keys(exports), function () {
      for (const [key, value] of Object.entries(exports)) this.setExport(key, value)
    }, { context })
  })
  await module.evaluate()
  return { instance: module.namespace[name](), clock, intervals,
    unmount: () => cleanup.forEach((fn) => fn()) }
}

async function mustSettle(promise) {
  let timer
  try {
    await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('operation remained pending after cancellation')), 200)
    })])
  } finally { clearTimeout(timer) }
}

test('stopping audio resolves its caller and releases playback resources', async () => {
  const playing = deferred()
  const clips = []
  class Audio {
    constructor() { this.paused = false; clips.push(this) }
    play() { playing.resolve(); return Promise.resolve() }
    pause() { this.paused = true }
  }
  const { instance } = await load('useTts', {
    ttsApi: { synth: async () => new Blob(['audio']) },
  }, { Audio })
  const speech = instance.speak('s', 1)
  await playing.promise
  instance.stop()
  await mustSettle(speech)
  assert.equal(instance.speaking.value, false)
  assert.equal(clips[0].paused, true)
})

test('a late TTS response cannot play after leaving the conversation', async () => {
  const pending = deferred(), requested = deferred()
  let audioCount = 0, signal
  const { instance } = await load('useTts', {
    ttsApi: { synth: (_sid, _turn, abortSignal) => {
      signal = abortSignal; requested.resolve(); return pending.promise
    } },
  }, { Audio: class { constructor() { audioCount++ } } })
  const speech = instance.speak('s', 1, 'fallback')
  await requested.promise
  instance.stop()
  assert.equal(signal.aborted, true)
  pending.resolve(new Blob(['late audio']))
  await mustSettle(speech)
  assert.equal(audioCount, 0)
})

test('browser fallback also resolves when playback is cancelled', async () => {
  const started = deferred()
  const { instance } = await load('useTts', {
    ttsApi: { synth: async () => { throw { code: 'TTS_UNAVAILABLE' } } },
  }, {
    window: { speechSynthesis: { cancel() {}, speak() { started.resolve() } } },
    SpeechSynthesisUtterance: class {},
  })
  const speech = instance.speak('s', 1, 'hello')
  await started.promise
  instance.stop()
  await mustSettle(speech)
  assert.equal(instance.speaking.value, false)
})

test('a continuation after unmount cannot start a new TTS request', async () => {
  let calls = 0
  const { instance, unmount } = await load('useTts', {
    ttsApi: { synth: async () => { calls++; return new Blob(['audio']) } },
  })
  unmount()
  await instance.speak('s', 1, 'late continuation')
  assert.equal(calls, 0)
})

function cameraEnvironment(open) {
  const track = { stopped: false, stop() { this.stopped = true } }
  const stream = { getTracks: () => [track] }
  return { track, stream, globals: {
    navigator: { mediaDevices: { getUserMedia: open ?? (async () => stream) } },
    document: { createElement: () => ({
      getContext: () => ({ drawImage() {} }), toDataURL: () => 'data:image/jpeg;base64,test',
    }) },
  } }
}

test('camera frames use the audio timeline and resume from the server generation', async () => {
  const camera = cameraEnvironment(), frames = [], captures = []
  const stopped = deferred()
  const { instance, clock, intervals } = await load('useVision', { visionApi: {
    capture: async (_sid, id, generation, active) => {
      captures.push({ generation, active })
      if (!active) await stopped.promise
      return { capture_id: active ? id : null, generation }
    },
    frame: async (payload) => { frames.push(payload) },
  } }, camera.globals)
  instance.bindVideo({ videoWidth: 960, videoHeight: 540, play: async () => {} })
  await instance.start('s', 250, 7)
  clock.now = () => 11_000
  await [...intervals.values()][0]()
  assert.equal(frames[0].captured_at_ms, 1250)
  assert.equal(captures[0].generation, 8)
  const stopping = instance.stop()
  assert.equal(camera.track.stopped, true)
  assert.equal(instance.active.value, false)
  stopped.resolve()
  await stopping
})

test('camera startup failure releases the device', async () => {
  const camera = cameraEnvironment()
  const { instance } = await load('useVision', { visionApi: {
    capture: async () => { throw new Error('capture failed') },
  } }, camera.globals)
  await assert.rejects(instance.start('s', 0), /capture failed/)
  assert.equal(camera.track.stopped, true)
  assert.equal(instance.active.value, false)
})

test('cancelling while camera permission is pending cannot restart capture', async () => {
  const permission = deferred(), camera = cameraEnvironment(() => permission.promise)
  let captureCalls = 0
  const { instance } = await load('useVision', { visionApi: {
    capture: async () => { captureCalls++ },
  } }, camera.globals)
  const starting = instance.start('s', 0)
  await instance.stop()
  permission.resolve(camera.stream)
  await starting
  assert.equal(camera.track.stopped, true)
  assert.equal(captureCalls, 0)
})

test('audio timestamps exclude time spent waiting for microphone permission', async () => {
  const permission = deferred(), camera = cameraEnvironment(() => permission.promise)
  class MediaRecorder {
    static isTypeSupported() { return true }
    state = 'inactive'
    mimeType = 'audio/webm'
    start() { this.state = 'recording' }
    stop() { this.state = 'inactive'; this.onstop?.() }
  }
  const { instance, clock } = await load('useRecorder', {}, { ...camera.globals, MediaRecorder })
  const starting = instance.start(500)
  clock.now = () => 11_000
  permission.resolve(camera.stream)
  await starting
  clock.now = () => 12_000
  const recording = await instance.stop()
  assert.equal(recording.startMs, 1500)
  assert.equal(recording.endMs, 2500)
  instance.cancel()
  assert.equal(camera.track.stopped, true)
})
