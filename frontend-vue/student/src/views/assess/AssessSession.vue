<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { audioApi, chatApi, sessionApi } from '@/api'
import { isApiError } from '@/api/http'
import type { ChatResponse, SpeechMetadata, VisionState } from '@/api/types'
import { useRecorder, type RecordingResult } from '@/composables/useRecorder'
import { useVision } from '@/composables/useVision'
import { useTts } from '@/composables/useTts'
import { useAssessStore } from '@/stores/assess'
import { newUtteranceId } from '@/utils/id'
import { toastError, toastWarn } from '@/utils/toast'
import PxButton from '@/components/base/PxButton.vue'
import PxBubble from '@/components/base/PxBubble.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'

const DEFAULT_OPENER = '你好呀，我是小晴～ 我们随便聊聊最近的心情和状态，好吗？'
/** 录音 59s 保护（后端音频时长上限 60s）。 */
const RECORD_GUARD_MS = 59_000

interface Msg {
  role: 'user' | 'assistant' | 'system'
  text: string
}

const route = useRoute()
const router = useRouter()
const assess = useAssessStore()

const sid = String(route.params.id ?? '')

const { recording, elapsedMs, start: startRecording, stop: stopRecording } = useRecorder()
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
// 摄像头开启但起流/上报失败（begin() 里兜底为仅语音）。
const camFailed = ref(false)
// 【临时·测试用】手动输入文字直接送给后端决策模型（跳过语音转写），上线前删除。
const manualText = ref('')
let guard = 0

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
    return assess.camEnabled && !camFailed.value
      ? { tone: 'warn', text: '摄像头开启中…' }
      : { tone: 'off', text: '仅语音模式（摄像头未开启）' }
  }
  if (visionUploadError.value) {
    return { tone: 'warn', text: `摄像头已开启，但数据未能上传：${visionUploadError.value}` }
  }
  return { tone: 'ok', text: `摄像头已开启 · 已上传 ${visionFrames.value} 帧` }
})

function pushMessage(role: Msg['role'], text: string) {
  messages.value.push({ role, text })
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
    assess.setSession(state.session_id, state.turn_count)
    for (const m of state.conversation_history) {
      if (m.role === 'user' || m.role === 'assistant') pushMessage(m.role, m.content)
    }
    opener.value = messages.value.find((m) => m.role === 'assistant')?.text ?? DEFAULT_OPENER
    if (!messages.value.length) pushMessage('assistant', opener.value)
    // 已聊过（续测）：无需再点「开始对话」
    started.value = state.turn_count > 0
    // 续测时若后端已收尾：直接进入收尾态，等待用户生成结果。
    if (state.current_stage === 'assessment_ready' || state.current_stage === 'completed') {
      closing.value = true
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
    if (assess.camEnabled) {
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
    if (recording.value) await stopRecording()
  } catch {
    /* ignore */
  }
  await stopVision()
}

/**
 * 统一处理 /api/chat 结果：上屏收尾回复 → 同步轮次 → 检测收尾 → 播报。
 * 收尾（assessment_ready）时停止输入与录音、关闭摄像头，并保留收尾语音。
 */
async function applyChatResult(res: ChatResponse) {
  pushMessage('assistant', res.reply)
  assess.setSession(sid, res.turn_count)
  if (res.assessment_ready) {
    closing.value = true
    await stopCapture()
  }
  await speak(sid, res.turn_count, res.reply)
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
    })
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
 * 【临时·测试用】手动输入文字，跳过录音与转写，直接送给后端决策模型(/api/chat)。
 * 上线前连同模板与样式一起删除。
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
    })
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
  await stopCapture()
  stopTts()
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
  void init()
})

onUnmounted(() => {
  if (guard) window.clearTimeout(guard)
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
        </div>

        <!-- 采集状态：区分「未开启（仅语音）」与「已开启但未上传/上传中」 -->
        <div
          v-if="started && !closing"
          class="session__vision"
          :class="`is-${visionStatus.tone}`"
        >
          <i class="session__vision-dot" />
          <span>{{ visionStatus.text }}</span>
        </div>
      </header>

      <!-- 采集用 video：正式测评不显示预览（设备检查页已确认过），仅用于取帧上报。 -->
      <video ref="videoRef" class="session__cam" muted playsinline autoplay />

      <!-- 消息区 -->
      <div class="session__chat">
        <PxBubble
          v-for="(m, i) in messages"
          :key="i"
          class="xq-fade-up"
          :role="m.role"
          :speaking="speaking && m.role === 'assistant' && i === messages.length - 1"
        >
          {{ m.text }}
        </PxBubble>
      </div>

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
            {{ busy ? '小晴正在准备…' : '点一下麦克风开始，小晴会先跟你打个招呼' }}
          </p>
          <p v-else-if="recording" class="session__hint session__hint--live">
            正在聆听… 说完点这里结束
          </p>
          <p v-else-if="busy" class="session__hint">小晴正在思考…</p>
          <p v-else-if="speaking" class="session__hint">小晴正在说话…</p>
          <p v-else class="session__hint">准备好了就点麦克风，慢慢说</p>

          <!-- 【临时·测试用】手动输入文字直接送给后端决策模型；上线前删除 -->
          <div class="session__manual">
            <input
              v-model="manualText"
              class="session__manual-input"
              type="text"
              placeholder="测试用：输入文字后回车发送"
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
        语音仅用于当场转写、不留存；视频仅提取特征。本测评为初步筛查，不构成医学诊断。
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

/* ---- 【临时·测试用】手动文字输入；上线前删除 ---- */
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
