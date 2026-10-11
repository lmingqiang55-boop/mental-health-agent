import { ref, computed, onMounted, onUnmounted } from 'vue'

/**
 * 响应式断点（移动优先）：
 * mobile < 640 / mobileLg 640-767 / tablet 768-1023 / desktopSm 1024-1279 / desktop >= 1280
 */
export function useBreakpoint() {
  const width = ref(typeof window !== 'undefined' ? window.innerWidth : 1024)

  function update() {
    width.value = window.innerWidth
  }

  onMounted(() => {
    update()
    window.addEventListener('resize', update, { passive: true })
  })
  onUnmounted(() => window.removeEventListener('resize', update))

  const isMobile = computed(() => width.value < 640)
  const isTablet = computed(() => width.value >= 640 && width.value < 1024)
  const isDesktop = computed(() => width.value >= 1024)
  /** 是否显示底部 Tab（手机/平板用底部 Tab） */
  const useTabBar = computed(() => width.value < 1024)

  return { width, isMobile, isTablet, isDesktop, useTabBar }
}
