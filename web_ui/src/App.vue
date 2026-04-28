<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import TabNavigation from '@/components/layout/TabNavigation.vue'
import DashboardHome from '@/views/app_shell/DashboardHome.vue'
import ScriptStudioView from '@/views/app_shell/ScriptStudioView.vue'
import TaskCenterView from '@/views/app_shell/TaskCenterView.vue'
import VoiceCenterView from '@/views/app_shell/VoiceCenterView.vue'
import AssetsCenterView from '@/views/app_shell/AssetsCenterView.vue'
import LibraryCenterView from '@/views/app_shell/LibraryCenterView.vue'
import ExportCenterView from '@/views/app_shell/ExportCenterView.vue'
import SystemCenterView from '@/views/app_shell/SystemCenterView.vue'
import LogCenterView from '@/views/app_shell/LogCenterView.vue'
import { useSystemStore } from '@/stores/system'
import { useProVoiceStore } from '@/stores/pro_voice'
import { useProTaskStore } from '@/stores/pro_task'
import { useShellStore, type AppShellTab } from '@/stores/shell'

const tabs = [
  { id: 'home', label: '工作台' },
  { id: 'script', label: '剧本' },
  { id: 'task', label: '任务' },
  { id: 'voice', label: '音色' },
  { id: 'assets', label: '资产' },
  { id: 'library', label: '资源库' },
  { id: 'export', label: '导出' },
  { id: 'system', label: '系统' },
  { id: 'logs', label: '日志' },
]

const systemStore = useSystemStore()
const voiceStore = useProVoiceStore()
const taskStore = useProTaskStore()
const shellStore = useShellStore()
const activeTab = computed({
  get: () => shellStore.activeTab,
  set: (tab: string) => shellStore.setActiveTab(tab as AppShellTab),
})

function navigateTo(tab: string) {
  shellStore.setActiveTab(tab as AppShellTab)
}

onMounted(() => {
  systemStore.startHeartbeat()
  void voiceStore.fetchVoices()

  const restored = taskStore.loadTaskPlanFromStorage()
  if (!restored && taskStore.taskRows.length === 0) {
    taskStore.addRow()
  }
})

onUnmounted(() => {
  systemStore.stopHeartbeat()
  taskStore.stopPolling()
})
</script>

<template>
  <div class="min-h-screen flex flex-col" style="background-color: var(--color-background);">
    <AppHeader :active-tab="activeTab" />

    <TabNavigation
      :tabs="tabs"
      v-model:active-tab="activeTab"
    />

    <main class="flex-1 px-4 pb-6 md:px-6 lg:px-8 w-full">
      <Transition name="fade" mode="out-in">
        <DashboardHome v-if="activeTab === 'home'" @navigate="navigateTo" />
        <ScriptStudioView v-else-if="activeTab === 'script'" @navigate="navigateTo" />
        <TaskCenterView v-else-if="activeTab === 'task'" />
        <VoiceCenterView v-else-if="activeTab === 'voice'" />
        <AssetsCenterView v-else-if="activeTab === 'assets'" />
        <LibraryCenterView v-else-if="activeTab === 'library'" />
        <ExportCenterView v-else-if="activeTab === 'export'" />
        <SystemCenterView v-else-if="activeTab === 'system'" />
        <LogCenterView v-else-if="activeTab === 'logs'" />
      </Transition>
    </main>
  </div>
</template>
