import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

/**
 * ECharts 挂载辅助：传入模板 ref（useTemplateRef）与 option，
 * 自动初始化、响应 option 变化、跟随容器尺寸、卸载销毁。
 */
export function useChart(el: Ref<HTMLElement | null>, option: Ref<EChartsOption | null>) {
  let chart: echarts.ECharts | null = null
  let observer: ResizeObserver | null = null

  function render() {
    if (!el.value || !option.value) return
    if (!chart) chart = echarts.init(el.value)
    chart.setOption(option.value, true)
  }

  onMounted(() => {
    render()
    if (el.value) {
      observer = new ResizeObserver(() => chart?.resize())
      observer.observe(el.value)
    }
  })

  watch(option, render, { deep: true })

  onBeforeUnmount(() => {
    observer?.disconnect()
    chart?.dispose()
    chart = null
  })
}
