<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import PxPageHead from '@/components/base/PxPageHead.vue'
import PxCard from '@/components/base/PxCard.vue'
import PxButton from '@/components/base/PxButton.vue'

type PhaseKind = 'in' | 'hold' | 'out'
interface Phase {
  kind: PhaseKind
  label: string
  seconds: number
}
interface Pattern {
  key: string
  title: string
  desc: string
  phases: Phase[]
}

const PATTERNS: Pattern[] = [
  {
    key: '478',
    title: '4-7-8 呼吸',
    desc: '吸气 4 秒 · 屏息 7 秒 · 呼气 8 秒，帮你快速安静下来',
    phases: [
      { kind: 'in', label: '慢慢吸气', seconds: 4 },
      { kind: 'hold', label: '轻轻屏住', seconds: 7 },
      { kind: 'out', label: '缓缓呼气', seconds: 8 },
    ],
  },
  {
    key: 'box',
    title: '箱式呼吸',
    desc: '4 · 4 · 4 · 4，像画一个方框，适合考前稳定心跳',
    phases: [
      { kind: 'in', label: '吸气', seconds: 4 },
      { kind: 'hold', label: '屏息', seconds: 4 },
      { kind: 'out', label: '呼气', seconds: 4 },
      { kind: 'hold', label: '屏息', seconds: 4 },
    ],
  },
  {
    key: 'calm',
    title: '舒缓呼吸',
    desc: '吸气 4 秒 · 呼气 6 秒，呼气比吸气长，更容易放松',
    phases: [
      { kind: 'in', label: '吸气', seconds: 4 },
      { kind: 'out', label: '呼气', seconds: 6 },
    ],
  },
]

const patternKey = ref('478')
const pattern = computed(() => PATTERNS.find((p) => p.key === patternKey.value) ?? PATTERNS[0])

const running = ref(false)
const phaseIdx = ref(0)
const elapsed = ref(0)
const cycles = ref(0)

let timer: number | null = null

const phase = computed(() => pattern.value.phases[phaseIdx.value] ?? pattern.value.phases[0])
const phaseRemain = computed(() => Math.max(0, Math.ceil(phase.value.seconds - elapsed.value)))

/** 圆的缩放：吸气变大、呼气变小、屏息保持上一阶段的大小。 */
const scale = computed(() => {
  const p = Math.min(1, elapsed.value / phase.value.seconds)
  if (phase.value.kind === 'in') return 0.62 + 0.38 * p
  if (phase.value.kind === 'out') return 1 - 0.38 * p
  const prev = pattern.value.phases[(phaseIdx.value - 1 + pattern.value.phases.length) % pattern.value.phases.length]
  return prev.kind === 'out' ? 0.62 : 1
})

const phaseDuration = computed(() => pattern.value.phases.reduce((a, p) => a + p.seconds, 0))
const cycleProgress = computed(() => {
  const before = pattern.value.phases.slice(0, phaseIdx.value).reduce((a, p) => a + p.seconds, 0)
  return (before + elapsed.value) / phaseDuration.value
})

function tick() {
  elapsed.value += 0.1
  if (elapsed.value >= phase.value.seconds) {
    elapsed.value = 0
    if (phaseIdx.value + 1 >= pattern.value.phases.length) {
      phaseIdx.value = 0
      cycles.value += 1
    } else {
      phaseIdx.value += 1
    }
  }
}

function start() {
  if (running.value) return
  running.value = true
  timer = window.setInterval(tick, 100)
}

function stop() {
  running.value = false
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

function reset() {
  stop()
  phaseIdx.value = 0
  elapsed.value = 0
  cycles.value = 0
}

function choose(key: string) {
  patternKey.value = key
  reset()
}

onUnmounted(stop)
</script>

<template>
  <div class="xq-page">
    <PxPageHead title="冥想正念" sub="跟着呼吸引导，把注意力放回此刻" back />

    <div class="md__patterns">
      <button
        v-for="p in PATTERNS"
        :key="p.key"
        type="button"
        class="md__pattern"
        :class="{ 'is-on': patternKey === p.key }"
        @click="choose(p.key)"
      >
        {{ p.title }}
      </button>
    </div>

    <PxCard class="md__stage-card" :title="pattern.title">
      <div class="md__stage">
        <div class="md__ring" :style="{ transform: `scale(${scale})` }" />
        <div class="md__hint">
          <p class="md__phase">{{ running ? phase.label : '准备好了吗' }}</p>
          <p class="md__count">{{ running ? phaseRemain : pattern.phases[0].seconds }}</p>
        </div>
      </div>
      <p class="md__progress" :style="{ '--p': `${cycleProgress * 100}%` }" />
      <p class="xq-muted md__desc">{{ pattern.desc }}</p>
    </PxCard>

    <PxCard class="md__block" title="今天的练习">
      <ul class="md__stats">
        <li>
          <strong>{{ cycles }}</strong>
          <em>完成轮次</em>
        </li>
        <li>
          <strong>{{ Math.round((cycles * phaseDuration) / 60) }}</strong>
          <em>练习分钟</em>
        </li>
      </ul>
      <div class="md__actions">
        <PxButton block v-if="!running" @click="start">开始</PxButton>
        <PxButton block v-else variant="secondary" @click="stop">暂停</PxButton>
        <PxButton variant="ghost" @click="reset">重置</PxButton>
      </div>
    </PxCard>

    <p class="xq-disclaimer">
      走神了很正常，发现之后把注意力带回呼吸就好。头晕或不适，随时停下来。
    </p>
  </div>
</template>

<style scoped>
.md__patterns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--xq-sp-2);
}
.md__pattern {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  color: var(--xq-text-2);
  padding: 10px 4px;
  font-size: var(--xq-fs-xs);
}
.md__pattern.is-on {
  background: var(--xq-primary-soft);
  color: var(--xq-text);
  box-shadow: var(--xq-shadow-pixel-sm);
}
.md__stage-card {
  margin-top: var(--xq-sp-3);
}
.md__stage {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 240px;
}
.md__ring {
  position: absolute;
  width: 180px;
  height: 180px;
  border: var(--xq-border-pixel);
  background: var(--xq-primary-soft);
  box-shadow: var(--xq-shadow-pixel);
  transition: transform 120ms linear;
}
.md__hint {
  position: relative;
  text-align: center;
}
.md__phase {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-lg);
}
.md__count {
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-3xl);
  color: var(--xq-primary-deep);
  line-height: 1.2;
}
.md__progress {
  height: 8px;
  border: var(--xq-border-pixel-thin);
  background: linear-gradient(
    to right,
    var(--xq-primary) var(--p),
    var(--xq-surface-2) var(--p)
  );
  margin-bottom: var(--xq-sp-3);
}
.md__desc {
  line-height: 1.7;
}
.md__block {
  margin-top: var(--xq-sp-3);
}
.md__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  text-align: center;
  margin-bottom: var(--xq-sp-4);
}
.md__stats strong {
  display: block;
  font-family: var(--xq-font-pixel);
  font-size: var(--xq-fs-2xl);
  color: var(--xq-primary-deep);
}
.md__stats em {
  font-style: normal;
  font-size: var(--xq-fs-xs);
  color: var(--xq-text-2);
}
.md__actions {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-2);
}
</style>
