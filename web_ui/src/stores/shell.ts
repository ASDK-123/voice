import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { LogFocusPreset } from '@/types'

export type AppShellTab =
  | 'home'
  | 'script'
  | 'task'
  | 'voice'
  | 'assets'
  | 'library'
  | 'export'
  | 'system'
  | 'logs'

export const useShellStore = defineStore('shell', () => {
  const activeTab = ref<AppShellTab>('home')
  const pendingLogFocus = ref<LogFocusPreset | null>(null)

  function setActiveTab(tab: AppShellTab) {
    activeTab.value = tab
  }

  function openLogsWithFocus(preset: LogFocusPreset) {
    pendingLogFocus.value = preset
    activeTab.value = 'logs'
  }

  function consumePendingLogFocus() {
    const next = pendingLogFocus.value
    pendingLogFocus.value = null
    return next
  }

  return {
    activeTab,
    pendingLogFocus,
    setActiveTab,
    openLogsWithFocus,
    consumePendingLogFocus,
  }
})
