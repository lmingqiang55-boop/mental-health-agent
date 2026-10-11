<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import PxButton from '@/components/base/PxButton.vue'

/**
 * 音景：Web Audio 实时合成，不打包任何音频文件。
 * 供「睡眠辅助 / 声音疗愈」共用。关闭页面即释放。
 */
const PRESETS = [
  { key: 'rain', label: '雨声', desc: '淅淅沥沥的雨' },
  { key: 'wave', label: '海浪', desc: '缓慢潮起潮落' },
  { key: 'fire', label: '篝火', desc: '噼啪的炉火' },
  { key: 'forest', label: '森林', desc: '树叶沙沙' },
  { key: 'white', label: '白噪音', desc: '均匀的沙沙声' },
] as const

type PresetKey = (typeof PRESETS)[number]['key']

const current = ref<PresetKey>('rain')
const playing = ref(false)
const volume = ref(0.5)
const errorText = ref('')

let ctx: AudioContext | null = null
let master: GainNode | null = null
let nodes: AudioNode[] = []

function noiseBuffer(context: AudioContext, seconds = 3): AudioBuffer {
  const len = context.sampleRate * seconds
  const buf = context.createBuffer(1, len, context.sampleRate)
  const data = buf.getChannelData(0)
  let last = 0
  for (let i = 0; i < len; i++) {
    const white = Math.random() * 2 - 1
    // 布朗噪声（更接近自然音色）
    last = (last + 0.02 * white) / 1.02
    data[i] = last * 3.5
  }
  return buf
}

function buildChain(preset: PresetKey) {
  if (!ctx || !master) return
  nodes.forEach((n) => {
    try {
      ;(n as OscillatorNode).stop?.()
    } catch {
      /* ignore */
    }
    n.disconnect()
  })
  nodes = []

  const src = ctx.createBufferSource()
  src.buffer = noiseBuffer(ctx)
  src.loop = true

  const filter = ctx.createBiquadFilter()
  const gain = ctx.createGain()

  if (preset === 'rain') {
    filter.type = 'highpass'
    filter.frequency.value = 900
    gain.gain.value = 0.5
  } else if (preset === 'wave') {
    filter.type = 'lowpass'
    filter.frequency.value = 500
    gain.gain.value = 0.4
    const l = ctx.createOscillator()
    l.frequency.value = 0.1
    const lg = ctx.createGain()
    lg.gain.value = 0.28
    l.connect(lg)
    lg.connect(gain.gain)
    l.start()
    nodes.push(lg)
  } else if (preset === 'fire') {
    filter.type = 'bandpass'
    filter.frequency.value = 1200
    filter.Q.value = 0.8
    gain.gain.value = 0.45
  } else if (preset === 'forest') {
    filter.type = 'lowpass'
    filter.frequency.value = 2200
    gain.gain.value = 0.35
  } else {
    filter.type = 'lowpass'
    filter.frequency.value = 8000
    gain.gain.value = 0.4
  }

  src.connect(filter)
  filter.connect(gain)
  gain.connect(master)
  src.start()

  nodes.push(src, filter, gain)
}

async function start() {
  errorText.value = ''
  try {
    if (!ctx) {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      ctx = new Ctor()
      master = ctx.createGain()
      master.gain.value = volume.value
      master.connect(ctx.destination)
    }
    await ctx.resume()
    buildChain(current.value)
    playing.value = true
  } catch {
    errorText.value = '当前浏览器不支持音频合成，可换用耳机或稍后再试。'
    playing.value = false
  }
}

function stop() {
  nodes.forEach((n) => {
    try {
      ;(n as AudioBufferSourceNode).stop?.()
    } catch {
      /* ignore */
    }
    n.disconnect()
  })
  nodes = []
  playing.value = false
}

function toggle() {
  if (playing.value) stop()
  else void start()
}

function choose(key: PresetKey) {
  current.value = key
  if (playing.value) buildChain(key)
}

function setVolume(v: number) {
  volume.value = v
  if (master) master.gain.value = v
}

onUnmounted(() => {
  stop()
  void ctx?.close()
  ctx = null
})
</script>

<template>
  <div class="scape">
    <div class="scape__stage" :class="{ 'is-playing': playing }">
      <span class="scape__icon">{{ playing ? '🎧' : '🌙' }}</span>
      <div class="scape__now">{{ PRESETS.find((p) => p.key === current)?.desc }}</div>
    </div>

    <div class="scape__grid">
      <button
        v-for="p in PRESETS"
        :key="p.key"
        type="button"
        class="scape__item"
        :class="{ 'is-on': current === p.key }"
        @click="choose(p.key)"
      >
        {{ p.label }}
      </button>
    </div>

    <label class="scape__vol">
      <span>音量</span>
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        :value="volume"
        @input="setVolume(Number(($event.target as HTMLInputElement).value))"
      />
    </label>

    <PxButton block :variant="playing ? 'secondary' : 'primary'" @click="toggle">
      {{ playing ? '停止播放' : '开始播放' }}
    </PxButton>

    <p v-if="errorText" class="xq-muted">{{ errorText }}</p>
  </div>
</template>

<style scoped>
.scape {
  display: flex;
  flex-direction: column;
  gap: var(--xq-sp-4);
}
.scape__stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 160px;
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface-2);
  transition: background var(--xq-dur-base) var(--xq-ease-base);
}
.scape__stage.is-playing {
  background: var(--xq-secondary-soft);
}
.scape__icon {
  font-size: 40px;
  line-height: 1;
}
.scape__now {
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.scape__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(72px, 1fr));
  gap: var(--xq-sp-2);
}
.scape__item {
  border: var(--xq-border-pixel-thin);
  background: var(--xq-surface);
  padding: 10px 6px;
  font-size: var(--xq-fs-sm);
  color: var(--xq-text);
}
.scape__item.is-on {
  background: var(--xq-primary);
  color: var(--xq-text-invert);
}
:root[data-theme='dark'] .scape__item.is-on {
  color: #17131f;
}
.scape__vol {
  display: flex;
  align-items: center;
  gap: var(--xq-sp-3);
  font-size: var(--xq-fs-sm);
  color: var(--xq-text-2);
}
.scape__vol input {
  flex: 1;
  accent-color: var(--xq-primary);
}
</style>
