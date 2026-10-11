<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { fmtClock } from '@/utils/format'
import PxButton from '@/components/base/PxButton.vue'

const props = withDefaults(
  defineProps<{
    focusMinutes?: number
    breakMinutes?: number
  }>(),
  { focusMinutes: 25, breakMinutes: 5 },
)

const emit = defineEmits<{ (e: 'complete', minutes: number): void }>()

type Phase = 'idle' | 'focus' | 'break' | 'paused'
const phase = ref<Phase>('idle')
const remaining = ref(props.focusMinutes * 60)
const rounds = ref(0)
let timer = 0
let lastPhase: 'focus' | 'break' = 'focus'

const running = computed(() => phase.value === 'focus' || phase.value === 'break')
const label = computed(() => {
  if (phase.value === 'idle') return '准备开始'
  if (phase.value === 'paused') return '已暂停'
  return phase.value === 'focus' ? '专注中' : '休息一下'
})

function tick() {
  remaining.value -= 1
  if (remaining.value > 0) return
  window.clearInterval(timer)
  if (phase.value === 'focus') {
    rounds.value += 1
    emit('complete', props.focusMinutes)
    lastPhase = 'break'
    phase.value = 'break'
    remaining.value = props.breakMinutes * 60
  } else {
    lastPhase = 'focus'
    phase.value = 'idle'
    remaining.value = props.focusMinutes * 60
  }
}

function start() {
  if (running.value) return
  if (phase.value === 'paused') {
    phase.value = lastPhase
  } else {
    lastPhase = 'focus'
    phase.value = 'focus'
    if (remaining.value <= 0) remaining.value = props.focusMinutes * 60
  }
  window.clearInterval(timer)
  timer = window.setInterval(tick, 1000)
}

function pause() {
  if (!running.value) return
  if (phase.value === 'focus' || phase.value === 'break') lastPhase = phase.value
  phase.value = 'paused'
  window.clearInterval(timer)
}

function reset() {
  window.clearInterval(timer)
  phase.value = 'idle'
  lastPhase = 'focus'
  remaining.value = props.focusMinutes * 60
}

onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <div class="focus-timer">
    <div class="focus-timer__ring" :class="`is-${phase}`">
      <div class="focus-timer__time">{{ fmtClock(remaining) }}</div>
      <div class="focus-timer__label">{{ label }}</div>
    </div>
    <div class="focus-timer__meta">
      <span>本轮已专注 {{ focusMinutes }} 分钟</span>
      <span>已完成 {{ rounds }} 轮</span>
    </div>
    <div class="focus-timer__actions">
      <PxButton v-if="!running" variant="primary" @click="start">
        {{ phase === 'paused' ? '继续' : '开始专注' }}
      </PxButton>
      <PxButton v-else variant="secondary" @click="pause">暂停</PxButton>
      <PxButton variant="ghost" @click="reset">重置</PxButton>
    </div>
  </div>
</template>

<style scoped>
.focus-timer {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--xq-sp-4);
}
.focus-timer__ring {
  width: 200px;
  height: 200px;
  border: var(--xq-border-pixel);
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: var(--xq-surface);
  box-shadow: var(--xq-shadow-pixel);
  transition: background var(--xq-dur-base) var(--xq-ease-base);
}
.focus-timer__ring.is-focus {
  background: var(--xq-primary-soft);
}
.focus-timer__ring.is-break {
  background: var(--xq-secondary-soft);
}
.focus-timer__ring.is-paused {
  background: var(--xq-surface-2);
}
.focus-timer__time {
  font-family: var(--xq-font-pixel);
  font-size: 40px;
  line-height: 1;
}
.focus-timer__label {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.focus-timer__meta {
  display: flex;
  gap: var(--xq-sp-4);
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.focus-timer__actions {
  display: flex;
  gap: var(--xq-sp-3);
}
</style>
