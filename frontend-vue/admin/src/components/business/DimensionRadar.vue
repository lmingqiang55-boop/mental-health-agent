<template>
  <div ref="chartEl" :style="{ width: '100%', height: height + 'px' }" />
</template>

<script setup lang="ts">
import { computed, useTemplateRef } from 'vue'
import type { EChartsOption } from 'echarts'
import { useChart } from '@/composables/useChart'
import { DIMENSION_MAP } from '@/utils/format'
import type { PsychologicalProfile } from '@/types'

const props = withDefaults(defineProps<{
  profile: Partial<PsychologicalProfile> | null | undefined
  height?: number
  name?: string
}>(), { height: 260, name: '五维画像' })

const option = computed<EChartsOption | null>(() => {
  if (!props.profile) return null
  const dims = Object.keys(DIMENSION_MAP) as (keyof PsychologicalProfile)[]
  return {
    radar: {
      indicator: dims.map((d) => ({ name: DIMENSION_MAP[d], max: 100 })),
      radius: '68%',
      splitArea: { areaStyle: { color: ['#fff', '#fff8f2'] } },
      axisName: { color: '#606266', fontSize: 12 },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: dims.map((d) => props.profile?.[d] ?? 0),
            name: props.name,
            areaStyle: { color: 'rgba(240,131,60,0.25)' },
            lineStyle: { color: '#f0833c', width: 2 },
            itemStyle: { color: '#f0833c' },
          },
        ],
      },
    ],
    tooltip: { trigger: 'item' },
  }
})

const chartEl = useTemplateRef<HTMLElement>('chartEl')
useChart(chartEl, option)
</script>
