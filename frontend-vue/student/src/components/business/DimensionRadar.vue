<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import type { ECharts } from 'echarts'
import type { Profile5 } from '@/api/types'

const props = withDefaults(
  defineProps<{
    profile: Profile5
    height?: number
  }>(),
  { height: 260 },
)

const el = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null

const LABELS: Record<keyof Profile5, string> = {
  emotion: '情绪',
  interest_motivation: '兴趣动力',
  sleep_energy: '睡眠精力',
  attention_thinking: '注意力思维',
  social_daily: '社交日常',
}
const KEYS = Object.keys(LABELS) as (keyof Profile5)[]

function clamp(v: number | null | undefined): number {
  return Math.max(0, Math.min(100, Math.round(v ?? 0)))
}

function buildOption() {
  return {
    radar: {
      indicator: KEYS.map((k) => ({ name: LABELS[k], max: 100 })),
      radius: '62%',
      splitNumber: 4,
      axisName: { color: '#9b8578', fontSize: 12 },
      splitLine: { lineStyle: { color: '#f0e2d2' } },
      splitArea: { areaStyle: { color: ['rgba(255,138,92,0.05)', 'transparent'] } },
      axisLine: { lineStyle: { color: '#f0e2d2' } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 6,
        data: [
          {
            value: KEYS.map((k) => clamp(props.profile[k])),
            name: '心理画像',
            areaStyle: { color: 'rgba(255,138,92,0.22)' },
            lineStyle: { color: '#ff8a5c', width: 2 },
            itemStyle: { color: '#ee6f3c' },
          },
        ],
      },
    ],
  }
}

async function render() {
  if (!el.value) return
  if (!chart) {
    const mod = await import('echarts')
    chart = mod.init(el.value)
  }
  chart.setOption(buildOption())
}

onMounted(render)
watch(() => props.profile, render, { deep: true })
onUnmounted(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" class="dim-radar" :style="{ height: `${height}px` }" />
</template>

<style scoped>
.dim-radar {
  width: 100%;
}
</style>
