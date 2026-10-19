<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { audioApi, chatApi, sessionApi } from '@/api'
import { isApiError } from '@/api/http'
import type { ChatResponse, SpeechMetadata, VisionState } from '@/api/types'
import { useRecorder, type RecordingResult } from '@/composables/useRecorder'
import { useVision } from '@/composables/useVision'
import { useTts } from '@/composables/useTts'
import { useAssessStore } from '@/stores/assess'
import { useStudentStore } from '@/stores/student'
import { newUtteranceId } from '@/utils/id'
import { toastError, toastWarn } from '@/utils/toast'
import PxButton from '@/components/base/PxButton.vue'
import PxBubble from '@/components/base/PxBubble.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'

const DEFAULT_OPENER = '你好呀，我是小晴～ 我们随便聊聊最近的心情和状态，好吗？'
/** 录音 59s 保护（后端音频时长上限 60s）。 */
const RECORD_GUARD_MS = 59_000
/**
 * 同一轮里第 2、3 条气泡的出现间隔。
 * 只是上屏节奏，**不额外调用任何模型**：内容在第一次响应里就已经全部拿到。
 */
const BUBBLE_REVEAL_MS = 420

interface Msg {
  role: 'user' | 'assistant' | 'system'
  /** 该条消息的完整文本（= bubbles 的换行拼接）。 */
  text: string
  /** 要显示的气泡；单条消息就是 [text]。 */
  bubbles: string[]
  /** 目前已显示几条气泡（多条时逐条出现）。 */
  shown: number
}

const route = useRoute()
const router = useRouter()
const assess = useAssessStore()
const student = useStudentStore()
const micAllowed = computed(() =>
  student.prefs.allowMic && assess.micEnabled && assess.consentScopes.includes('audio_transcription'))
const cameraAllowed = computed(() =>
  student.prefs.allowCamera && assess.camEnabled && assess.consentScopes.includes('vision_analysis'))

const sid = String(route.params.id ?? '')

const {
  recording,
  elapsedMs,
  start: startRecording,
  stop: stopRecording,
  cancel: cancelRecording,
} = useRecorder()
const { speaking, speak, stop: stopTts } = useTts()
const {
  active: visionActive,
  framesSent: visionFrames,
  uploadError: visionUploadError,
  bindVideo,
  ensureCaptureId,
  start: startVision,
  segment,
  stop: stopVision,
} = useVision()

const videoRef = ref<HTMLVideoElement | null>(null)

const loading = ref(true)
const started = ref(false)
const busy = ref(false)
const messages = ref<Msg[]>([])
const opener = ref(DEFAULT_OPENER)
const lastUtteranceId = ref<string | null>(null)
// 已收尾（后端 assessment_ready）：停止普通追问，等待用户点「生成结果」。
const closing = ref(false)
/**
 * 安全支持热线。
 *
 * 【只走后端】号码来自 `/api/chat` 的 `safety.hotline_numbers`，由后端按部署地区
 * 从**已核实注册表**下发；前端不硬编码、也不猜地区。未配置地区时后端下发空列表，
 * 这里就什么都不显示，绝不套用中国大陆号码。
 *
 * 【只增不减】支持模式是单向锁：后续某一轮若被判为 normal，后端不再下发号码，
 * 但学生仍处在支持模式里，号码不应该跟着消失。因此只在拿到号码时更新。
 */
const safetyHotlines = ref<string[]>([])
// 摄像头开启但起流/上报失败（begin() 里兜底为仅语音）。
const camFailed = ref(false)
// 【演示用】手动输入文字直接送给后端决策模型（跳过语音转写）。
// 竞赛演示的台词是预先设计好的，走这条通道可以避免 ASR 识别抖动；
// 正式面向学生上线前需要重新评估是否保留。
const manualText = ref('')
let guard = 0
const processingController = new AbortController()

/** 气泡逐个出现的定时器；离开页面/重新开始时必须清掉。 */
const revealTimers = new Set<number>()
/** 消息区末尾的哨兵元素，用于把最新气泡滚进视野。 */
const chatEndRef = ref<HTMLElement | null>(null)

async function scrollToEnd() {
  await nextTick()
  chatEndRef.value?.scrollIntoView({ block: 'end', behavior: 'smooth' })
}

function clearRevealTimers() {
  for (const id of revealTimers) window.clearTimeout(id)
  revealTimers.clear()
}

/** 把一个后端消息对象归一成"至少一条气泡"。 */
function toBubbles(text: string, items?: string[] | null): string[] {
  const list = (items?.length ? items : [text])
    .map((item) => (item ?? '').trim())
    .filter(Boolean)
  return list.length ? list : [text]
}

/**
 * 时间轴原点：整场会话只取一次 performance.now()。
 * 录音的 recording_start_ms/end_ms 与视觉 segment 的 start_ms/end_ms 都相对它计算，
 * 保证音频与视觉在同一时间轴上对齐。
 */
const originAt = performance.now()
function originMs(): number {
  return performance.now() - originAt
}

const recordSeconds = computed(() => Math.min(59, Math.floor(elapsedMs.value / 1000)))

/**
 * 采集状态（P1-6）：让「没开摄像头」与「开了但没传上去」在界面上可区分。
 * - off  ：仅语音模式（未开启 / 起流失败兜底）
 * - warn ：已开启但上报失败，或尚未开始采集
 * - ok   ：已开启且帧正常上报
 */
const visionStatus = computed<{ tone: 'off' | 'warn' | 'ok'; text: string }>(() => {
  if (!visionActive.value) {
    return cameraAllowed.value && assess.camEnabled && !camFailed.value
      ? { tone: 'warn', text: '摄像头开启中…' }
      : { tone: 'off', text: '仅语音模式（摄像头未开启）' }
  }
  if (visionUploadError.value) {
    return { tone: 'warn', text: `摄像头已开启，但数据未能上传：${visionUploadError.value}` }
  }
  return { tone: 'ok', text: `摄像头已开启 · 已上传 ${visionFrames.value} 帧` }
})

function pushMessage(role: Msg['role'], text: string, items?: string[] | null) {
  const bubbles = toBubbles(text, items)
  messages.value.push({ role, text, bubbles, shown: bubbles.length })
  void scrollToEnd()
}

/**
 * 追加一条助手消息：第 1 条气泡立即上屏，其余按 BUBBLE_REVEAL_MS 逐条出现。
 * 历史恢复时走 pushMessage（一次全部显示），不会重新"演"一遍。
 */
function pushAssistantMessage(text: string, items?: string[] | null) {
  const bubbles = toBubbles(text, items)
  const msg: Msg = { role: 'assistant', text, bubbles, shown: 1 }
  messages.value.push(msg)
  void scrollToEnd()
  for (let index = 1; index < bubbles.length; index += 1) {
    const id = window.setTimeout(() => {
      revealTimers.delete(id)
      msg.shown = Math.min(index + 1, bubbles.length)
      void scrollToEnd()
    }, BUBBLE_REVEAL_MS * index)
    revealTimers.add(id)
  }
}

async function init() {
  if (!sid) {
    toastWarn('缺少测评会话，请重新开始')
    void router.replace({ name: 'assess' })
    return
  }
  loading.value = true
  try {
    const state = await sessionApi.get(sid)
    if (state.consent.status !== 'granted') {
      toastWarn('本次会话尚未完成知情同意')
      await router.replace({ name: 'assess-consent' })
      return
    }
    assess.setSession(state.session_id, state.turn_count)
    assess.setConsentScopes(state.consent.scope)
    for (const m of state.conversation_history) {
      if (m.role === 'user' || m.role === 'assistant') pushMessage(m.role, m.content, m.messages)
    }
    opener.value = messages.value.find((m) => m.role === 'assistant')?.text ?? DEFAULT_OPENER
    if (!messages.value.length) pushMessage('assistant', opener.value)
    void scrollToEnd()
    // 已聊过（续测）：无需再点「开始对话」
    started.value = state.turn_count > 0
    // 续测时若后端已收尾：直接进入收尾态，等待用户生成结果。
    if (state.current_stage === 'assessment_ready' || state.current_stage === 'completed') {
      closing.value = true
    }
    // 续测时恢复安全支持热线：从历史里找一条带号码的安全结论。
    // 只看 last_safety 不够——中途若有一轮判为 normal，那一轮就不会带号码。
    if (state.safety_halted || state.safety_stage === 'stopped') {
      const fromHistory = state.conversation_history
        .map((m) => m.safety?.hotline_numbers ?? [])
        .find((numbers) => numbers.length)
      safetyHotlines.value = fromHistory ?? state.latest_safety?.hotline_numbers ?? []
    }
  } catch (e) {
    if (isApiError(e, 'SESSION_NOT_FOUND')) {
      toastWarn('测评会话不存在或已过期，请重新开始')
      void router.replace({ name: 'assess' })
    }
  } finally {
    loading.value = false
  }
}

/** 开始对话：用户手势内解锁音频，播报开场白。 */
async function begin() {
  if (started.value || closing.value) return
  started.value = true
  busy.value = true
  try {
    if (cameraAllowed.value && assess.camEnabled) {
      try {
        await startVision(sid, originMs())
        camFailed.value = false
      } catch {
        camFailed.value = true
        toastWarn('摄像头不可用，已切换为仅语音')
      }
    }
    await speak(sid, 0, opener.value)
  } finally {
    busy.value = false
  }
}

async function startRecord() {
  if (busy.value || speaking.value || recording.value || closing.value) return
  if (!micAllowed.value) {
    toastWarn('麦克风已在隐私设置中关闭，请使用文字回答')
    return
  }
  busy.value = true
  try {
    await startRecording(originMs())
    guard = window.setTimeout(() => {
      void finishRecord()
    }, RECORD_GUARD_MS)
  } catch {
    toastError('无法访问麦克风，请检查权限后重试')
  } finally {
    busy.value = false
  }
}

/** 停止录音 + 关闭摄像头采集（收尾时用；不停 TTS，让收尾语音播报完整）。 */
async function stopCapture() {
  if (guard) {
    window.clearTimeout(guard)
    guard = 0
  }
  try {
    if (recording.value) cancelRecording()
  } catch {
    /* ignore */
  }
  await stopVision()
}

function callHotline(number: string) {
  window.location.href = `tel:${number}`
}

/**
 * 统一处理 /api/chat 结果：逐条上屏气泡 → 同步轮次 → 检测收尾 → 播报。
 * 收尾（assessment_ready）时停止输入与录音、关闭摄像头，并保留收尾语音。
 *
 * 语音按**整轮**合成一次（`/api/tts` 用 turn_count 定位这一轮的全部气泡），
 * 因此不会漏读第 2、3 条，也不会因为 reply 兼容字段把同一句话读两遍。
 */
async function applyChatResult(res: ChatResponse) {
  const bubbles = toBubbles(res.reply, res.messages)
  pushAssistantMessage(res.reply, bubbles)
  assess.setSession(sid, res.turn_count)
  // 安全支持热线：只取后端下发的已核实号码。只在拿到号码时更新（见 safetyHotlines 注释）。
  const hotlines = res.safety?.hotline_numbers ?? []
  if (hotlines.length) safetyHotlines.value = hotlines
  if (res.assessment_ready) {
    closing.value = true
    await stopCapture()
  }
  await speak(sid, res.turn_count, bubbles.join('\n'))
}

/** 结束说话：视觉分段 → 转写 → 出题(chat) → 播报。 */
async function finishRecord() {
  if (guard) {
    window.clearTimeout(guard)
    guard = 0
  }
  if (!recording.value) return
  busy.value = true
  const utteranceId = newUtteranceId()
  try {
    const rec: RecordingResult = await stopRecording()

    let visionSnapshot: VisionState | null = null
    try {
      visionSnapshot = await segment(utteranceId, rec.startMs, rec.endMs)
    } catch {
      visionSnapshot = null
    }

    const ext = rec.mimeType.includes('mp4') ? 'm4a' : 'webm'
    const tr = await audioApi.transcribe({
      file: rec.blob,
      filename: `turn-${utteranceId}.${ext}`,
      sessionId: sid,
      utteranceId,
      // capture_id 为必填：与取帧/片段共用同一标识，关闭摄像头时也要传。
      captureId: ensureCaptureId(),
      recordingStartMs: rec.startMs,
      recordingEndMs: rec.endMs,
      signal: processingController.signal,
    })
    const text: string = tr.text
    const speech: SpeechMetadata = tr.speech

    if (!text.trim()) {
      pushMessage('system', '这次没有听清，请再说一次～')
      return
    }
    pushMessage('user', text)

    const res = await chatApi.send({
      session_id: sid,
      text,
      vision_snapshot: visionSnapshot,
      utterance_id: utteranceId,
      speech,
    }, processingController.signal)
    lastUtteranceId.value = utteranceId
    assess.saveProgress(utteranceId)
    await applyChatResult(res)
  } catch (e) {
    // 后端已收尾：普通输入被拒绝(409)，进入收尾态等待生成结果。
    if (isApiError(e, 'SCREENING_FINISHED')) {
      closing.value = true
      await stopCapture()
    }
    /* 其余错误拦截器已 toastError */
  } finally {
    busy.value = false
  }
}

/**
 * 【演示用】手动输入文字，跳过录音与转写，直接送给后端决策模型(/api/chat)。
 * 与语音通道共用同一套 applyChatResult，因此气泡拆分、视觉线索、Agent 轨迹
 * 的行为完全一致，只是输入来源不同。
 */
async function sendManualText() {
  const text = manualText.value.trim()
  if (!text || busy.value || speaking.value || recording.value || closing.value) return
  busy.value = true
  const utteranceId = newUtteranceId()
  try {
    let visionSnapshot: VisionState | null = null
    try {
      const now = originMs()
      visionSnapshot = await segment(utteranceId, Math.max(0, now - 1000), now)
    } catch {
      visionSnapshot = null
    }

    pushMessage('user', text)
    const res = await chatApi.send({
      session_id: sid,
      text,
      vision_snapshot: visionSnapshot,
      utterance_id: utteranceId,
    }, processingController.signal)
    lastUtteranceId.value = utteranceId
    assess.saveProgress(utteranceId)
    manualText.value = ''
    await applyChatResult(res)
  } catch (e) {
    // 后端已收尾：普通输入被拒绝(409)，进入收尾态等待生成结果。
    if (isApiError(e, 'SCREENING_FINISHED')) {
      closing.value = true
      await stopCapture()
    }
    /* 其余错误拦截器已 toastError */
  } finally {
    busy.value = false
  }
}

async function stopAll() {
  clearRevealTimers()
  processingController.abort()
  await stopCapture()
  stopTts()
}

function cancelCurrentRecording() {
  if (guard) window.clearTimeout(guard)
  guard = 0
  cancelRecording()
  pushMessage('system', '本次录音已取消，没有上传。')
}

async function disableCamera() {
  await stopVision()
  assess.setCamEnabled(false)
  student.prefs.allowCamera = false
  toastWarn('摄像头已关闭，后续不会再发送画面')
}

async function withdrawConsent() {
  if (!window.confirm('撤回后会立即停止设备、取消未完成请求并删除当前会话。已保存的历史结果不会自动删除，是否继续？')) return
  processingController.abort()
  cancelRecording()
  await stopVision()
  stopTts()
  await sessionApi.consent(sid, false, []).catch(() => undefined)
  await sessionApi.remove(sid).catch(() => undefined)
  messages.value = []
  manualText.value = ''
  assess.clearProgress()
  await router.replace({ name: 'me-privacy' })
}

function onVisibilityChange() {
  if (!document.hidden) return
  if (recording.value) cancelCurrentRecording()
  if (visionActive.value) void disableCamera()
}

/** 生成结果：保存进度、彻底停机 → 进入安全检查页（由该页调 /api/assessment）。 */
async function goGenerate() {
  assess.saveProgress(lastUtteranceId.value)
  await stopAll()
  started.value = false
  await router.replace({ name: 'assess-safety' })
}

/** 提前结束对话（未达收尾条件时手动触发）。 */
async function endSession() {
  if (!window.confirm('确认结束本次对话吗？接下来会为你生成报告。')) return
  await goGenerate()
}

// video 在 loading 结束后才挂载：用 watch 在元素真正挂载时绑定实时流。
watch(videoRef, (el) => bindVideo(el), { flush: 'post' })

onMounted(() => {
  if (!cameraAllowed.value && assess.camEnabled) assess.setCamEnabled(false)
  if (!micAllowed.value) assess.setMicEnabled(false)
  void init()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  if (guard) window.clearTimeout(guard)
  clearRevealTimers()
  document.removeEventListener('visibilitychange', onVisibilityChange)
  processingController.abort()
  cancelRecording()
})

onBeforeRouteLeave(() => {
  // 已收尾：对话结束，离开无需确认
  if (closing.value) return true
  // 主动结束（跳安全页）不计入离开确认
  if (!started.value && !recording.value) return true
  const leave = window.confirm('测评还没结束，确定离开吗？进度会保留，可稍后在测评中心继续。')
  if (leave) {
    assess.saveProgress(lastUtteranceId.value)
    void stopAll()
    started.value = false
  }
  return leave
})
</script>

<template>
  <div class="xq-page session">
    <PxEmpty v-if="loading" icon="…" text="正在准备你的测评…" />

    <template v-else>
      <!-- 顶部：对话式测评（不按固定题号） -->
      <header class="session__head">
        <div class="session__head-row">
          <div class="session__head-main">
            <p class="session__title">对话测评</p>
            <p class="session__sub">和小晴聊聊最近的心情和状态就好</p>
          </div>
          <button type="button" class="session__pause" @click="router.push({ name: 'assess' })">
            暂停
          </button>
          <button type="button" class="session__pause" @click="withdrawConsent">撤回同意</button>
        </div>

        <!-- 采集状态：区分「未开启（仅语音）」与「已开启但未上传/上传中」 -->
        <div
          v-if="started && !closing"
          class="session__vision"
          :class="`is-${visionStatus.tone}`"
        >
          <i class="session__vision-dot" />
          <span>{{ visionStatus.text }}</span>
          <button v-if="visionActive" type="button" class="session__vision-close" @click="disableCamera">关闭摄像头</button>
        </div>
      </header>

      <!-- 采集用 video：正式测评不显示预览（设备检查页已确认过），仅用于取帧上报。 -->
      <video ref="videoRef" class="session__cam" muted playsinline autoplay />

      <!-- 消息区：一轮可有多条气泡，同一轮的气泡贴得更近 -->
      <div class="session__chat">
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="session__turn"
          :class="`session__turn--${m.role}`"
        >
          <PxBubble
            v-for="(b, j) in m.bubbles.slice(0, m.shown)"
            :key="`${i}-${j}`"
            class="xq-fade-up"
            :role="m.role"
            :speaking="
              speaking && m.role === 'assistant' && i === messages.length - 1 && j === m.shown - 1
            "
          >
            {{ b }}
          </PxBubble>
        </div>
        <div ref="chatEndRef" class="session__chat-end" aria-hidden="true" />
      </div>

      <!-- 安全支持热线：号码只来自后端已核实配置（未配置地区时后端不下发，这里不显示） -->
      <PxCard
        v-if="safetyHotlines.length"
        class="session__safety"
        tone="danger"
        title="现在最重要的一件事"
      >
        <p class="session__safety-lead">
          我很在意你现在的安全。如果此刻很难受，请立刻联系专业帮助：
        </p>
        <div class="session__safety-calls">
          <PxButton
            v-for="number in safetyHotlines"
            :key="number"
            variant="hotline"
            block
            @click="callHotline(number)"
          >
            心理援助热线：{{ number }}
          </PxButton>
        </div>
        <p class="session__safety-note">
          也可以马上告诉身边可信任的家人、老师，或直接去最近的医院急诊。
        </p>
      </PxCard>

      <!-- 录音区：收尾后切换为「生成结果」 -->
      <div class="session__dock">
        <template v-if="closing">
          <p class="session__hint session__hint--done">
            我们已经聊得差不多啦～ 点下面按钮，为你生成一份状态评估。
          </p>
          <PxButton size="lg" @click="goGenerate">生成结果</PxButton>
        </template>

        <template v-else>
          <span v-if="recording" class="session__pill">
            <i class="session__pill-dot" />语音转写 · {{ recordSeconds }}s
          </span>

          <button
            v-if="micAllowed"
            type="button"
            class="session__mic"
            :class="{ 'is-recording xq-pulse': recording }"
            :disabled="!recording && (busy || speaking)"
            :aria-label="recording ? '结束说话' : '开始说话'"
            @click="!started ? begin() : recording ? finishRecord() : startRecord()"
          >
            <span class="session__mic-ico">{{ recording ? '■' : '🎙' }}</span>
          </button>

          <p v-if="!started" class="session__hint">
            {{
              busy
                ? '小晴正在准备…'
                : micAllowed
                  ? '点一下麦克风开始，小晴会先跟你打个招呼'
                  : '麦克风已关闭，点击下面按钮开始文字测评'
            }}
          </p>
          <p v-else-if="recording" class="session__hint session__hint--live">
            正在聆听… 说完点这里结束
          </p>
          <PxButton v-if="recording" variant="danger" size="sm" @click="cancelCurrentRecording">取消录音（不上传）</PxButton>
          <p v-else-if="busy" class="session__hint">小晴正在思考…</p>
          <p v-else-if="speaking" class="session__hint">小晴正在说话…</p>
          <p v-else class="session__hint">准备好了就点麦克风，慢慢说</p>

          <PxButton v-if="!started && !micAllowed" size="lg" @click="begin">开始文字测评</PxButton>

          <!-- 【演示用】文字输入通道；关闭麦克风时也是正式的无障碍入口。 -->
          <div class="session__manual">
            <input
              v-model="manualText"
              class="session__manual-input"
              type="text"
              :placeholder="micAllowed ? '也可以输入文字回答' : '输入文字回答后按回车发送'"
              :disabled="busy || speaking || recording"
              @keyup.enter="sendManualText"
            />
            <PxButton
              size="sm"
              :disabled="!manualText.trim() || busy || speaking || recording"
              @click="sendManualText"
            >
              发送
            </PxButton>
          </div>

          <PxButton v-if="started" variant="ghost" size="sm" @click="endSession">
            提前结束对话
          </PxButton>
        </template>
      </div>

      <p class="xq-disclaimer">
        语音上传至本机项目后端转写且不长期保存原始录音；摄像头画面发送至本机项目后端实时分析且不写入评估记录。本测评不构成医学诊断。
      </p>
    </template>
  </div>
</template>

<style scoped>
.session {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-4);
  min-height: 100dvh;
}

/* ---- 顶部进度 ---- */
.session__head {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
}
.session__head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-3);
}
.session__title {
  font-family: var(--xq-font-pixel);
  font-weight: 700;
  font-size: var(--xq-fs-lg);
}
.session__sub {
  margin-top: 2px;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.session__pause {
  border: none;
  background: transparent;
  color: var(--xq-text-2);
  font-size: var(--xq-fs-sm);
  padding: var(--xq-sp-2) var(--xq-sp-3);
  border-radius: 999px;
  transition: background var(--xq-dur-fast) var(--xq-ease-base);
}
.session__pause:active {
  background: var(--xq-primary-soft);
  color: var(--xq-primary-deep);
}
.session__vision-close { margin-left: 8px; border: 0; background: transparent; color: inherit; text-decoration: underline; cursor: pointer; }

/* ---- 采集状态指示 ---- */
.session__vision {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  font-size: var(--xq-fs-xs);
  padding: 4px 12px;
  background: var(--xq-surface-2);
  color: var(--xq-text-2);
}
.session__vision-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.session__vision.is-ok {
  background: var(--xq-primary-soft);
  color: var(--xq-primary-deep);
}
.session__vision.is-warn {
  background: rgba(255, 138, 92, 0.16);
  color: var(--xq-hotline);
}

/* ---- 采集用 video：不显示预览，但保留渲染以保证取帧正常 ---- */
.session__cam {
  position: fixed;
  top: 0;
  left: 0;
  width: 2px;
  height: 2px;
  opacity: 0;
  pointer-events: none;
}

/* ---- 消息区 ---- */
.session__chat {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
  flex: 1;
  min-height: 140px;
  padding: var(--xq-sp-2) 0 var(--xq-sp-4);
}

/* 一轮 = 一个 turn 容器：轮与轮之间 var(--xq-sp-3)，同轮气泡之间更近，
   让人一眼看出"这几条是同一个人在连着说"。 */
.session__turn {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.session__turn--user {
  align-items: flex-end;
}
.session__chat-end {
  height: 1px;
  flex: 0 0 auto;
}

/* ---- 安全支持热线 ----
   进入安全支持模式后才出现（号码由后端按部署地区下发）；layout 上放在对话区与
   录音区之间，学生一抬眼就能看到，且不需要离开当前对话去另一个页面。 */
.session__safety-lead {
  margin: 0;
  line-height: 1.7;
}
.session__safety-calls {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
  margin-top: var(--xq-sp-3);
}
.session__safety-note {
  margin: var(--xq-sp-3) 0 0;
  color: var(--xq-text-2);
  font-size: var(--xq-fs-sm);
  line-height: 1.7;
}

/* ---- 录音区 ---- */
.session__dock {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--xq-sp-3);
  padding: var(--xq-sp-4) 0 var(--xq-sp-2);
}
.session__pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  background: var(--xq-primary-soft);
  color: var(--xq-primary-deep);
  font-size: var(--xq-fs-xs);
  padding: 4px 12px;
}
.session__pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--xq-primary-deep);
  animation: xq-twinkle 1.2s ease-in-out infinite;
}
.session__mic {
  width: 84px;
  height: 84px;
  border: none;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #ffa176 0%, var(--xq-primary) 60%, var(--xq-primary-deep) 100%);
  color: #fff;
  box-shadow: 0 10px 24px rgba(255, 138, 92, 0.38);
  transition: transform var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base);
}
.session__mic:active:not(:disabled) {
  transform: scale(0.94);
}
.session__mic:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.session__mic.is-recording {
  background: linear-gradient(135deg, var(--xq-primary) 0%, var(--xq-hotline) 100%);
}
.session__mic-ico {
  font-size: 26px;
  line-height: 1;
}
.session__hint {
  text-align: center;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.session__hint--live {
  color: var(--xq-primary-deep);
}
.session__hint--done {
  color: var(--xq-primary-deep);
  font-size: var(--xq-fs-base);
}

/* ---- 【演示用】文字输入通道 ---- */
.session__manual {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-2);
  width: 100%;
  max-width: 420px;
}
.session__manual-input {
  flex: 1;
  min-width: 0;
  height: 40px;
  padding: 0 var(--xq-sp-3);
  border: var(--xq-border-pixel);
  border-radius: var(--xq-radius-m);
  background: var(--xq-surface);
  color: var(--xq-text);
  font-size: var(--xq-fs-sm);
}
.session__manual-input:focus {
  outline: none;
  border-color: var(--xq-primary);
}
.session__manual-input::placeholder {
  color: var(--xq-text-2);
}

@media (min-width: 1024px) {
  .session {
    max-width: 720px;
    margin: 0 auto;
    gap: var(--xq-sp-5);
  }
  .session__mic {
    width: 96px;
    height: 96px;
  }
}
</style>
