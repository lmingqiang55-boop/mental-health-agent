import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { SourceTextModule, SyntheticModule, createContext } from 'node:vm'
import ts from 'typescript'
import { computed, ref } from 'vue'

const expired = { code: 'HEALING_SESSION_EXPIRED', status: 404 }
const missing = { code: 'HEALING_NOT_FOUND', status: 404 }
const active = (session_id, status = 'active') => ({
  session_id, healing_id: `heal-${session_id}`, status,
  messages: [], report: { question: '想聊些什么？' }, risk: { risk_level: 'normal' },
})

async function page({ query = {}, pointer = null, latest = '', get, historyError } = {}) {
  const calls = [], starts = [], replacements = []
  let cached = pointer, clearCount = 0
  const route = { query }
  const context = createContext({})
  const dependencies = {
    vue: { computed, ref, nextTick: async () => {}, watch() {}, onMounted() {} },
    'vue-router': {
      useRoute: () => route,
      useRouter: () => ({ replace: async ({ query }) => {
        route.query = query; replacements.push(query)
      } }),
    },
    '@/api': {
      historyApi: { byStudent: async () => {
        if (historyError) throw historyError
        return { records: latest ? [{ result: { session_id: latest } }] : [] }
      } },
      healingApi: {
        get: async (sid, options) => { calls.push({ sid, options }); return get(sid) },
        start: async (request) => { starts.push(request); return active(request.session_id) },
      },
    },
    '@/api/http': { isApiError: (e, code) => e?.code === code },
    '@/stores/heal': { useHealStore: () => ({
      pointer: () => cached,
      remember: (state) => { cached = { sessionId: state.session_id } },
      clear: () => { cached = null; clearCount++ },
    }) },
    '@/stores/student': { useStudentStore: () => ({ studentRef: 'test-student' }) },
    '@/utils/id': { newRequestId: () => 'request', newMessageId: () => 'message' },
    '@/utils/format': { fmtDateTime: (value) => value },
    '@/utils/toast': { toastError() {}, toastSuccess() {}, toastWarn() {} },
  }
  const source = await readFile(new URL('../src/views/heal/HealChat.vue', import.meta.url), 'utf8')
  const setup = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const compiled = ts.transpileModule(`${setup}\nexport { load, state, blocked, loading };`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  const module = new SourceTextModule(compiled, { context })
  await module.link((specifier) => {
    const exports = dependencies[specifier]
    assert.ok(exports, `Unexpected import ${specifier}`)
    return new SyntheticModule(Object.keys(exports), function () {
      for (const [key, value] of Object.entries(exports)) this.setExport(key, value)
    }, { context })
  })
  await module.evaluate()
  await module.namespace.load()
  return { view: module.namespace, calls, starts, replacements,
    cached: () => cached, clearCount: () => clearCount }
}

test('new assessment replaces an older cached companionship session', async () => {
  const p = await page({ pointer: { sessionId: 'expired-old' }, latest: 'latest', get: active })
  assert.deepEqual(p.calls.map((call) => call.sid), ['latest'])
  assert.equal(p.cached().sessionId, 'latest')
  assert.equal(p.view.loading.value, false)
})

test('expired deep link moves once to the latest assessment and creates its companionship', async () => {
  const p = await page({ query: { session: 'old' }, pointer: { sessionId: 'old' }, latest: 'latest',
    get: async (sid) => { throw sid === 'old' ? expired : missing },
  })
  assert.deepEqual(p.calls.map((call) => call.sid), ['old', 'latest'])
  assert.equal(p.calls[0].options.silent, true)
  assert.equal(p.replacements[0].session, 'latest')
  assert.equal(p.starts.length, 1)
  assert.equal(p.starts[0].session_id, 'latest')
  assert.equal(p.clearCount(), 1)
  assert.equal(p.view.state.value.status, 'active')
})

test('an explicitly selected live safety referral stays on that session', async () => {
  const p = await page({ query: { session: 'referred' }, latest: 'newer',
    get: (sid) => active(sid, 'referred'),
  })
  assert.deepEqual(p.calls.map((call) => call.sid), ['referred'])
  assert.equal(p.view.state.value.status, 'referred')
  assert.equal(p.replacements.length, 0)
  assert.equal(p.starts.length, 0)
})

test('expiry of the latest assessment stops recovery without creating a new screening session', async () => {
  const p = await page({ query: { session: 'old' }, latest: 'latest', get: async () => { throw expired } })
  assert.deepEqual(p.calls.map((call) => call.sid), ['old', 'latest'])
  assert.match(p.view.blocked.value, /没有找到可恢复/)
  assert.equal(p.view.loading.value, false)
  assert.equal(p.starts.length, 0)
})

test('history failure preserves a working cached companionship session', async () => {
  const p = await page({ pointer: { sessionId: 'cached' }, historyError: new Error('offline'), get: active })
  assert.deepEqual(p.calls.map((call) => call.sid), ['cached'])
  assert.equal(p.view.blocked.value, '')
})

test('a recoverable old companionship is kept even when a newer assessment exists', async () => {
  const p = await page({ query: { session: 'archived' }, latest: 'newer', get: active })
  assert.deepEqual(p.calls.map((call) => call.sid), ['archived'])
  assert.equal(p.cached().sessionId, 'archived')
  assert.equal(p.replacements.length, 0)
  assert.equal(p.starts.length, 0)
})

test('a temporary service failure does not switch sessions or generate a new companionship', async () => {
  const p = await page({ query: { session: 'selected' }, latest: 'newer',
    get: async () => { throw { code: 'HEALING_UNAVAILABLE', status: 503 } },
  })
  assert.deepEqual(p.calls.map((call) => call.sid), ['selected'])
  assert.equal(p.replacements.length, 0)
  assert.equal(p.starts.length, 0)
  assert.equal(p.view.loading.value, false)
})
