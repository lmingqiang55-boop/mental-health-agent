<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'
import PxInput from '@/components/base/PxInput.vue'
import PxBubble from '@/components/base/PxBubble.vue'
import PxEmpty from '@/components/base/PxEmpty.vue'
import PxTag from '@/components/base/PxTag.vue'
import { healingApi, historyApi } from '@/api'
import { isApiError } from '@/api/http'
import type { HealingResponse } from '@/api/types'
import { useHealStore } from '@/stores/heal'
import { useStudentStore } from '@/stores/student'
import { newMessageId, newRequestId } from '@/utils/id'
import { fmtDateTime } from '@/utils/format'
import { toastSuccess, toastWarn } from '@/utils/toast'

const route = useRoute()
const router = useRouter()
const heal = useHealStore()
const student = useStudentStore()

const loading = ref(true)
const starting = ref(false)
const sending = ref(false)
const state = ref<HealingResponse | null>(null)

/** 无法进入时的提示（缺测评 / 会话过期）。 */
const blocked = ref('')
/** 输入框草稿。 */
const draft = ref('')
/** 乐观插入的那条「我的消息」。 */
const pending = ref<{ role: 'user' | 'assistant'; content: string; created_at: string } | null>(null)
/** 发送失败时记住 (消息标识, 内容)，重试复用同一个标识（后端幂等要求）。 */
const failed = ref<{ id: string; text: string } | null>(null)

const showSuggestions = ref(false)
const composing = ref(false)
const scroller = ref<HTMLElement | null>(null)

const preparing = computed(() => loading.value || (starting.value && !state.value))
const status = computed(() => state.value?.status ?? 'active')
const ended = computed(() => status.value === 'ended' || status.value === 'referred')
const highRisk = computed(() => state.value?.risk?.risk_level === 'high')
const locked = computed(() => ended.value || !!blocked.value)

/** 报告里的第一个提问如果没有落进消息流，就补成小晴的开场白。 */
const visibleMessages = computed(() => {
  const s = state.value
  if (!s) return []
  const base = s.messages.length
    ? s.messages
    : s.report.question
      ? [
          {
            role: 'assistant' as const,
            content: s.report.question,
            created_at: s.report.generated_at,
          },
        ]
      : []
  return pending.value ? [...base, pending.value] : base
})

async function scrollDown() {
  await nextTick()
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}

watch([() => visibleMessages.value.length, sending], () => void scrollDown(), { flush: 'post' })

/** 优先用路由带来的 session；其次用上次记住的；最后回退到最近一次测评。 */
async function resolveSessionId(): Promise<string> {
  const q = route.query.session
  if (typeof q === 'string' && q) return q
  const pointer = heal.pointer()
  if (pointer?.sessionId) return pointer.sessionId
  try {
    const res = await historyApi.byStudent(student.studentRef)
    return res.records[0]?.result.session_id ?? ''
  } catch {
    return ''
  }
}

async function refresh(sessionId: string) {
  try {
    const res = await healingApi.get(sessionId)
    state.value = res
    heal.remember(res)
  } catch {
    /* 保持原状态 */
  }
}

async function generate(sessionId: string, regenerate: boolean) {
  starting.value = true
  blocked.value = ''
  try {
    const res = await healingApi.start({
      session_id: sessionId,
      request_id: newRequestId(),
      ...(regenerate ? { regenerate: true, expected_healing_id: state.value?.healing_id } : {}),
    })
    state.value = res
    heal.remember(res)
    failed.value = null
    toastSuccess('报告已经准备好了，慢慢看')
    await scrollDown()
  } catch (e) {
    if (isApiError(e, 'HEALING_ASSESSMENT_REQUIRED')) {
      blocked.value = '这个会话还没有测评结果，治愈陪伴需要先有一份初步筛查。'
    } else if (isApiError(e, 'HEALING_SESSION_EXPIRED')) {
      blocked.value = '上一次会话已经过期了，重新做一次初步筛查就能继续。'
    } else if (isApiError(e, 'HEALING_STATE_CHANGED')) {
      toastWarn('陪伴已更新，正在为你刷新')
      await refresh(sessionId)
    }
    /* 其余错误由 axios 拦截器统一提示 */
  } finally {
    starting.value = false
    loading.value = false
  }
}

async function load() {
  loading.value = true
  blocked.value = ''
  const sessionId = await resolveSessionId()
  if (!sessionId) {
    blocked.value = '还没有可用的会话，先做一次初步筛查吧。'
    loading.value = false
    return
  }
  try {
    const res = await healingApi.get(sessionId)
    state.value = res
    heal.remember(res)
    loading.value = false
    await scrollDown()
  } catch (e) {
    if (isApiError(e, 'HEALING_SESSION_EXPIRED')) {
      blocked.value = '上一次会话已经过期了，重新做一次初步筛查就能继续。'
      loading.value = false
    } else {
      // HEALING_NOT_FOUND：还没生成过 → 现在生成
      await generate(sessionId, false)
    }
  }
}

async function send() {
  const text = draft.value.trim()
  if (!text || sending.value || locked.value || !state.value) return
  sending.value = true
  const id = failed.value && failed.value.text === text ? failed.value.id : newMessageId()
  const sessionId = state.value.session_id
  pending.value = { role: 'user', content: text, created_at: new Date().toISOString() }
  draft.value = ''
  await scrollDown()
  try {
    const res = await healingApi.chat(sessionId, state.value.healing_id, id, text)
    state.value = res
    heal.remember(res)
    pending.value = null
    failed.value = null
  } catch (e) {
    pending.value = null
    draft.value = text
    if (isApiError(e, 'HEALING_STATE_CHANGED')) {
      failed.value = null
      toastWarn('陪伴已重新生成，正在为你刷新')
      await refresh(sessionId)
    } else if (isApiError(e, 'HEALING_ENDED') || isApiError(e, 'HEALING_TURN_LIMIT')) {
      failed.value = null
      await refresh(sessionId)
    } else {
      failed.value = { id, text }
    }
  } finally {
    sending.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter' || e.shiftKey || composing.value) return
  e.preventDefault()
  void send()
}

function regenerate() {
  if (!state.value) return
  void generate(state.value.session_id, true)
}

onMounted(load)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="治愈陪伴" sub="小晴会先看看你的报告，再陪你聊一会儿" back />

    <!-- 准备中 -->
    <PxCard v-if="preparing" title="正在准备">
      <PxEmpty text="小晴正在读你的测评结果，写一份属于你的报告…" />
    </PxCard>

    <!-- 无法进入 -->
    <PxCard v-else-if="blocked" title="还差一步">
      <p class="hc__text">{{ blocked }}</p>
      <div class="hc__row">
        <PxButton @click="router.push('/assess/consent')">去做一次初步筛查</PxButton>
        <PxButton variant="ghost" @click="router.push('/heal')">回到心理自助</PxButton>
      </div>
    </PxCard>

    <template v-else-if="state">
      <!-- 今日心情小结 -->
      <PxCard tone="primary" class="hc__summary xq-fade-up">
        <div class="hc__summary-head">
          <p class="hc__summary-title">今日心情小结</p>
          <PxTag
            v-if="state.risk"
            :tone="state.risk.risk_level === 'high' ? 'danger' : state.risk.risk_level === 'medium' ? 'warning' : 'success'"
          >
            {{ { low: '状态平稳', medium: '轻度关注', high: '需要照顾' }[state.risk.risk_level] }}
          </PxTag>
        </div>

        <p class="hc__label">她这样理解你</p>
        <p class="hc__text">{{ state.report.understanding }}</p>

        <p class="hc__label">这次先关注</p>
        <p class="hc__text">{{ state.report.focus }}</p>

        <div v-if="state.report.suggestions.length" class="hc__tags">
          <PxTag v-for="(s, i) in state.report.suggestions.slice(0, 3)" :key="i" tone="primary" size="sm">
            {{ s.title }}
          </PxTag>
        </div>

        <button
          type="button"
          class="hc__report-link"
          @click="router.push({ name: 'assess-report', params: { resultId: state.assessment_result_id }, query: { session: state.session_id } })"
        >
          查看完整报告 ›
        </button>

        <template v-if="state.report.suggestions.length">
          <button type="button" class="hc__toggle" @click="showSuggestions = !showSuggestions">
            {{ showSuggestions ? '收起建议' : `看看小晴建议的 ${state.report.suggestions.length} 个小方法` }}
            <span>{{ showSuggestions ? '▲' : '▼' }}</span>
          </button>
          <div v-if="showSuggestions" class="hc__suggs">
            <div v-for="(s, i) in state.report.suggestions" :key="i" class="hc__sugg">
              <p class="hc__sugg-title">{{ i + 1 }}. {{ s.title }}</p>
              <p v-if="s.goal" class="hc__text hc__muted">{{ s.goal }}</p>
              <ol v-if="s.steps.length" class="hc__steps">
                <li v-for="(st, j) in s.steps" :key="j">{{ st }}</li>
              </ol>
              <p v-if="s.cautions.length" class="hc__caution">注意：{{ s.cautions.join('；') }}</p>
            </div>
          </div>
        </template>

        <div v-if="state.report.cautions.length" class="hc__cautions">
          <p class="hc__label">要留意的是</p>
          <ul class="hc__steps">
            <li v-for="(c, i) in state.report.cautions" :key="i">{{ c }}</li>
          </ul>
        </div>

        <p class="hc__meta">报告生成于 {{ fmtDateTime(state.report.generated_at) }}</p>
      </PxCard>

      <!-- 风险较高：只给求助方式，不做任何「已预警」的呈现 -->
      <PxCard v-if="highRisk" class="hc__block" tone="danger" title="现在最重要的事">
        <p class="hc__text">
          你此刻的感受很重要，也不需要一个人扛。可以马上拨打 12356 心理援助热线，
          或联系你信任的大人、校内心理老师；如果出现伤害自己的念头，请立刻拨打 110 / 120。
        </p>
        <div class="hc__row">
          <a class="hc__tel" href="tel:12356">拨打 12356</a>
        </div>
      </PxCard>

      <!-- 对话流 -->
      <div ref="scroller" class="hc__chat">
        <PxEmpty
          v-if="!visibleMessages.length && !sending"
          text="先看看上面的报告，有什么想说的都可以告诉她"
        />
        <PxBubble v-for="(m, i) in visibleMessages" :key="i" class="xq-fade-up" :role="m.role">
          {{ m.content }}
        </PxBubble>
        <PxBubble v-if="sending" role="assistant">
          <span class="xq-dots">···</span>
        </PxBubble>
      </div>

      <!-- 结束 / 转介 -->
      <PxCard v-if="ended" class="hc__block" title="这轮陪伴先到这里">
        <p class="hc__text hc__muted">
          {{
            status === 'referred'
              ? '小晴觉得你现在需要更专业的帮助，可以把上面的求助方式用起来。'
              : '你随时可以再开始一轮新的陪伴。'
          }}
        </p>
        <div class="hc__row">
          <PxButton :loading="starting" @click="regenerate">重新生成一轮</PxButton>
          <PxButton variant="ghost" @click="router.push('/heal')">回到心理自助</PxButton>
        </div>
      </PxCard>

      <!-- 输入条 -->
      <div v-else class="hc__composer">
        <div
          class="hc__composer-row"
          @keydown="onKeydown"
          @compositionstart="composing = true"
          @compositionend="composing = false"
        >
          <PxInput
            v-model="draft"
            textarea
            :rows="2"
            :maxlength="500"
            :disabled="sending || preparing"
            placeholder="把此刻的想法写下来，Enter 发送，Shift + Enter 换行"
          />
          <button
            type="button"
            class="hc__send"
            :class="{ 'is-ready': draft.trim() }"
            :disabled="!draft.trim() || sending || preparing"
            aria-label="发送"
            @click="send"
          >
            <span v-if="sending" class="xq-star">✦</span>
            <span v-else>➤</span>
          </button>
        </div>
        <p v-if="failed" class="xq-muted hc__retry">
          刚才那条没发出去，内容还在——再点一次「发送」就会重试同一条。
        </p>
        <p class="xq-muted hc__tip">小晴的回应只是陪伴与自助支持，不构成诊断或治疗建议。</p>
      </div>
    </template>

    <p class="xq-disclaimer">
      如果此刻非常难受，请拨打 12356 心理援助热线，或联系校内心理老师；紧急情况请拨 110 / 120。
    </p>
  </div>
</template>

<style scoped>
/* ---- 今日心情小结 ---- */
.hc__summary-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xq-sp-2);
}
.hc__summary-title {
  font-family: var(--xq-font-pixel);
  font-weight: 700;
  font-size: var(--xq-fs-lg);
}
.hc__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xq-sp-2);
  margin-top: var(--xq-sp-3);
}
.hc__report-link {
  display: inline-flex;
  align-items: center;
  margin-top: var(--xq-sp-4);
  padding: 0;
  border: none;
  background: transparent;
  color: var(--xq-primary-deep);
  font-size: var(--xq-fs-sm);
  font-weight: 600;
}
.hc__report-link:active {
  opacity: 0.7;
}
.hc__label {
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
  margin-top: var(--xq-sp-3);
}
.hc__summary-head + .hc__label {
  margin-top: var(--xq-sp-4);
}
.hc__text {
  font-size: var(--xq-fs-sm);
  line-height: 1.75;
  margin-top: 4px;
}
.hc__muted {
  color: var(--xq-text-2);
}
.hc__meta {
  margin-top: var(--xq-sp-4);
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-disabled);
}
.hc__toggle {
  margin-top: var(--xq-sp-3);
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--xq-sp-2);
  border: none;
  border-radius: var(--xq-radius-m);
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel-sm);
  padding: 10px 14px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-primary-deep);
}
.hc__suggs {
  margin-top: var(--xq-sp-3);
  display: grid;
  gap: var(--xq-sp-3);
}
.hc__sugg {
  border-radius: var(--xq-radius-m);
  background: var(--xq-primary-soft);
  padding: var(--xq-sp-3) var(--xq-sp-4);
}
.hc__sugg-title {
  font-family: var(--xq-font-pixel);
  font-weight: 600;
  font-size: var(--xq-fs-sm);
}
.hc__steps {
  margin-top: 6px;
  padding-left: 1.2em;
  display: grid;
  gap: 3px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
  line-height: 1.65;
}
.hc__caution {
  margin-top: var(--xq-sp-2);
  font-size: var(--xq-fs-xs);
  color: var(--xq-level-high);
}
.hc__cautions {
  margin-top: var(--xq-sp-4);
  border-top: 1px dashed var(--xq-text-disabled);
  padding-top: var(--xq-sp-2);
}
.hc__block {
  margin-top: var(--xq-sp-3);
}

/* ---- 对话流 ---- */
.hc__chat {
  margin-top: var(--xq-sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-3);
  max-height: 52vh;
  overflow-y: auto;
  padding: var(--xq-sp-1) 2px;
}
.hc__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--xq-sp-2);
  margin-top: var(--xq-sp-3);
}
.hc__tel {
  display: inline-block;
  border-radius: 999px;
  background: linear-gradient(135deg, #ff8a6b 0%, var(--xq-hotline) 100%);
  color: #fff;
  box-shadow: 0 6px 16px rgba(255, 107, 74, 0.35);
  padding: 10px 22px;
  font-size: var(--xq-fs-sm);
  font-weight: 600;
}

/* ---- 底部输入条 ---- */
.hc__composer {
  margin-top: var(--xq-sp-4);
}
.hc__composer-row {
  display: flex;
  align-items: flex-end;
  gap: var(--xq-sp-2);
}
.hc__composer-row :deep(.px-field) {
  flex: 1;
  min-width: 0;
}
.hc__composer-row :deep(.px-input--area) {
  border-radius: 22px;
  min-height: 52px;
}
.hc__send {
  flex: 0 0 auto;
  width: 52px;
  height: 52px;
  border: none;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--xq-surface-2);
  color: var(--xq-text-disabled);
  font-size: 18px;
  transition: transform var(--xq-dur-fast) var(--xq-ease-base),
    background var(--xq-dur-fast) var(--xq-ease-base),
    box-shadow var(--xq-dur-fast) var(--xq-ease-base);
}
.hc__send.is-ready {
  background: linear-gradient(135deg, #ffa176 0%, var(--xq-primary) 60%, var(--xq-primary-deep) 100%);
  color: #fff;
  box-shadow: 0 6px 16px rgba(255, 138, 92, 0.35);
}
.hc__send:active:not(:disabled) {
  transform: scale(0.92);
}
.hc__send:disabled {
  cursor: not-allowed;
}
.hc__retry {
  margin-top: var(--xq-sp-1);
  font-size: var(--xq-fs-xs);
}
.hc__tip {
  margin-top: var(--xq-sp-1);
  font-size: var(--xq-fs-xs);
}
@media (min-width: 1024px) {
  .hc__chat {
    max-height: 56vh;
  }
  .hc__composer {
    margin-top: var(--xq-sp-5);
  }
}
</style>
