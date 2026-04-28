<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useLogsStore } from '@/stores/logs'
import { useShellStore } from '@/stores/shell'
import type { LogLevel, LogSourceId } from '@/types'
import LogToolbar from '@/components/logs/LogToolbar.vue'
import LogList from '@/components/logs/LogList.vue'
import LogDetailDrawer from '@/components/logs/LogDetailDrawer.vue'
import StatusMessage from '@/components/shared/StatusMessage.vue'

const logsStore = useLogsStore()
const shellStore = useShellStore()
const feedbackMessage = ref('')
const searchDraft = ref(logsStore.query)

let searchTimer: ReturnType<typeof setTimeout> | null = null
let feedbackTimer: ReturnType<typeof setTimeout> | null = null

function handleSourceChange(value: string) {
  void logsStore.setSource(value as LogSourceId)
}

function handleLevelChange(value: string) {
  void logsStore.setLevel(value as LogLevel | '')
}

function handleRefresh() {
  void logsStore.refreshNow()
}

function handleOpenSystem() {
  shellStore.setActiveTab('system')
}

function handleDownloadSource() {
  void logsStore.downloadCurrentSource()
}

function handleExportBundle() {
  void logsStore.exportBundle()
}

function handleShowAllLevels() {
  void logsStore.showAllLevels()
}

function handleClearFocus() {
  searchDraft.value = ''
  void logsStore.clearFocusReason()
}

function setFeedback(message: string) {
  feedbackMessage.value = message
  if (feedbackTimer) {
    clearTimeout(feedbackTimer)
  }
  feedbackTimer = setTimeout(() => {
    feedbackMessage.value = ''
    feedbackTimer = null
  }, 2200)
}

async function handleCopy(value: string) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    setFeedback('已复制到剪贴板')
  } catch (e) {
    logsStore.error = (e as Error).message
  }
}

async function handleQueryChange(value: string) {
  searchDraft.value = value
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  searchTimer = setTimeout(() => {
    void logsStore.setQuery(searchDraft.value)
  }, 260)
}

async function initializeView() {
  const preset = shellStore.consumePendingLogFocus()
  if (preset) {
    searchDraft.value = preset.query
    await logsStore.applyFocusPreset(preset)
  } else {
    await logsStore.initialize()
  }
  logsStore.startPolling({ skipInitialize: true })
}

watch(
  () => logsStore.query,
  value => {
    if (value !== searchDraft.value) {
      searchDraft.value = value
    }
  },
)

onMounted(() => {
  void initializeView().catch(() => {})
})

onUnmounted(() => {
  logsStore.stopPolling()
  if (searchTimer) clearTimeout(searchTimer)
  if (feedbackTimer) clearTimeout(feedbackTimer)
})
</script>

<template>
  <div class="page-shell logs-shell">
    <section class="page-hero">
      <p class="page-eyebrow">日志域</p>
      <h2 class="page-title">日志</h2>
      <p class="page-desc">
        统一查看应用日志、访问日志、崩溃日志和本地桥接日志；支持实时轮询、筛选、搜索和诊断包导出。
      </p>
    </section>

    <LogToolbar
      :sources="logsStore.sources"
      :current-source="logsStore.currentSource"
      :current-source-available="logsStore.currentSourceAvailable"
      :level-filter="logsStore.levelFilter"
      :query="searchDraft"
      :auto-scroll="logsStore.autoScroll"
      :is-loading="logsStore.isLoading"
      :connection-name="logsStore.connectionName"
      :connection-base-url="logsStore.connectionBaseUrl"
      :total-count="logsStore.items.length"
      :locked="logsStore.errorKind === 'logs_route_missing'"
      @update:source="handleSourceChange"
      @update:level="handleLevelChange"
      @update:query="handleQueryChange"
      @refresh="handleRefresh"
      @toggle-auto-scroll="logsStore.setAutoScroll"
      @download-source="handleDownloadSource"
      @export-bundle="handleExportBundle"
    />

    <StatusMessage v-if="feedbackMessage" :message="feedbackMessage" tone="success" />
    <StatusMessage
      v-if="logsStore.errorKind === 'logs_route_missing'"
      title="后端在线，但未提供日志接口"
      :message="`${logsStore.error} 当前连接：${logsStore.connectionName}（${logsStore.connectionBaseUrl || '未配置'}）。`"
      tone="warning"
    >
      <template #actions>
        <button class="btn btn-secondary" type="button" @click="handleRefresh">
          刷新
        </button>
        <button class="btn btn-ghost" type="button" @click="handleOpenSystem">
          前往系统页
        </button>
      </template>
    </StatusMessage>
    <StatusMessage
      v-else-if="logsStore.error"
      :message="logsStore.error"
      tone="danger"
    />
    <StatusMessage
      v-if="logsStore.pollingSuspended && logsStore.errorKind !== 'logs_route_missing'"
      title="日志轮询已暂停"
      message="当前日志接口不可用，已停止自动轮询以避免页面持续闪烁和卡顿。修正连接地址或后端后，点击“刷新”即可重新尝试。"
      tone="warning"
    />
    <StatusMessage
      v-if="logsStore.focusReason"
      title="来自系统页的联动定位"
      :message="`${logsStore.focusReason} 当前源：${logsStore.currentSourceMeta?.label || '应用日志'}`"
      tone="warning"
    >
      <template #actions>
        <button class="btn btn-ghost" type="button" @click="handleShowAllLevels">
          查看全部级别
        </button>
        <button class="btn btn-secondary" type="button" @click="handleClearFocus">
          清除联动
        </button>
      </template>
    </StatusMessage>

    <div class="content-grid" :class="{ 'with-drawer': !!logsStore.selectedItem }">
      <LogList
        :items="logsStore.items"
        :auto-scroll="logsStore.autoScroll"
        :selected-item-id="logsStore.selectedItemId"
        @select="logsStore.selectItem"
        @update:auto-scroll="logsStore.setAutoScroll"
      />

      <LogDetailDrawer
        :open="!!logsStore.selectedItem"
        :item="logsStore.selectedItem"
        @close="logsStore.clearSelection"
        @copy="handleCopy"
      />
    </div>
  </div>
</template>

<style scoped>
.logs-shell {
  max-width: 1480px;
}

.content-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 18px;
}

.content-grid.with-drawer {
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
}

@media (max-width: 1080px) {
  .content-grid.with-drawer {
    grid-template-columns: 1fr;
  }
}
</style>
