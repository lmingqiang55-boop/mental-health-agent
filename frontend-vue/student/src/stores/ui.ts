import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { STORAGE_KEYS, readLS, writeLS } from '@/utils/storage'

export type ThemeMode = 'light' | 'dark'

/** 全局 UI 态：主题（明/暗）。断点判断见 composables/useBreakpoint。 */
export const useUiStore = defineStore('ui', () => {
  const theme = ref<ThemeMode>(readLS<ThemeMode>(STORAGE_KEYS.theme, 'light'))

  function applyTheme() {
    document.documentElement.setAttribute('data-theme', theme.value)
  }

  function setTheme(t: ThemeMode) {
    theme.value = t
    applyTheme()
  }

  function toggleTheme() {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  watch(theme, (v) => writeLS(STORAGE_KEYS.theme, v))
  applyTheme()

  return { theme, setTheme, toggleTheme, applyTheme }
})
