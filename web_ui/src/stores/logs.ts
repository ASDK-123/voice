import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { downloadBlob } from '@/utils/audio'
import { useTtsStore } from '@/stores/tts'
import { downloadLogFile, exportDiagnosticBundle, isLogsApiError, listLogSources, tailLogs } from '@/api/logs'
import type { LogApiErrorKind, LogFocusPreset, LogItem, LogLevel, LogSourceId, LogSourceOption } from '@/types'

const MAX_ITEMS = 500
const POLL_INTERVAL_MS = 1000
const DEFAULT_SOURCES: LogSourceOption[] = [
  { id: 'app', label: '应用日志', available: false },
  { id: 'access', label: '访问日志', available: false },
  { id: 'crash', label: '崩溃日志', available: false },
  { id: 'local_bridge', label: '本地桥接日志', available: false },
]

function mergeItems(existing: LogItem[], incoming: LogItem[]): LogItem[] {
  const map = new Map<string, LogItem>()
  for (const item of existing) {
    map.set(item.id, item)
  }
  for (const item of incoming) {
    map.set(item.id, item)
  }
  const merged = Array.from(map.values())
  return merged.slice(Math.max(0, merged.length - MAX_ITEMS))
}

export const useLogsStore = defineStore('logs', () => {
  const tts = useTtsStore()

  const sources = ref<LogSourceOption[]>(DEFAULT_SOURCES.map(item => ({ ...item })))
  const currentSource = ref<LogSourceId>('app')
  const levelFilter = ref<LogLevel | ''>('')
  const query = ref('')
  const items = ref<LogItem[]>([])
  const cursor = ref('')
  const isLoading = ref(false)
  const isPolling = ref(false)
  const error = ref('')
  const errorKind = ref<LogApiErrorKind | ''>('')
  const autoScroll = ref(true)
  const lastUpdatedAt = ref('')
  const selectedItemId = ref('')
  const focusReason = ref('')
  const focusOrigin = ref<LogFocusPreset['origin'] | ''>('')
  const pollingSuspended = ref(false)

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollInFlight = false

  const connectionName = computed(() => tts.currentConfig?.name || '未选择 TTS 配置')
  const connectionBaseUrl = computed(() => tts.currentConfig?.baseUrl || '')
  const currentSourceMeta = computed<LogSourceOption | null>(() => {
    return sources.value.find(item => item.id === currentSource.value) || null
  })
  const currentSourceAvailable = computed(() => currentSourceMeta.value?.available ?? false)
  const selectedItem = computed(() => {
    return items.value.find(item => item.id === selectedItemId.value) || null
  })

  function updateSourceAvailability(source: LogSourceId, available: boolean) {
    sources.value = sources.value.map(item =>
      item.id === source ? { ...item, available } : item,
    )
  }

  function resetState() {
    items.value = []
    cursor.value = ''
    error.value = ''
    errorKind.value = ''
    selectedItemId.value = ''
  }

  function applyError(nextError: unknown) {
    if (isLogsApiError(nextError)) {
      error.value = nextError.message
      errorKind.value = nextError.kind
      return
    }
    error.value = (nextError as Error).message
    errorKind.value = ''
  }

  async function fetchSources() {
    try {
      const next = await listLogSources()
      sources.value = next
      pollingSuspended.value = false
      if (!next.some(item => item.id === currentSource.value)) {
        currentSource.value = 'app'
      }
      error.value = ''
      errorKind.value = ''
    } catch (e) {
      sources.value = DEFAULT_SOURCES.map(item => ({ ...item }))
      applyError(e)
      throw e
    }
  }

  async function pollOnce(reset = false) {
    if (pollInFlight) return
    pollInFlight = true
    if (reset) {
      items.value = []
      cursor.value = ''
      selectedItemId.value = ''
    }

    isLoading.value = true
    try {
      const payload = await tailLogs({
        source: currentSource.value,
        cursor: cursor.value || undefined,
        limit: 200,
        level: levelFilter.value || undefined,
        q: query.value || undefined,
      })
      updateSourceAvailability(currentSource.value, payload.source_available)
      cursor.value = payload.next_cursor
      lastUpdatedAt.value = new Date().toISOString()
      pollingSuspended.value = false
      error.value = ''
      errorKind.value = ''

      if (payload.reset_required || reset || !items.value.length) {
        items.value = payload.items.slice(-MAX_ITEMS)
      } else if (payload.items.length > 0) {
        items.value = mergeItems(items.value, payload.items)
      }
    } catch (e) {
      applyError(e)
      if (errorKind.value === 'logs_route_missing' || errorKind.value === 'non_json_response') {
        pollingSuspended.value = true
        stopPolling()
      }
    } finally {
      isLoading.value = false
      pollInFlight = false
    }
  }

  async function initialize() {
    await fetchSources()
    await pollOnce(true)
  }

  function startPolling(options?: { skipInitialize?: boolean }) {
    stopPolling()
    isPolling.value = true
    if (!options?.skipInitialize) {
      void initialize().catch(() => {})
    }
    pollTimer = setInterval(() => {
      if (pollingSuspended.value) {
        return
      }
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return
      }
      void pollOnce(false)
    }, POLL_INTERVAL_MS)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    isPolling.value = false
  }

  async function setSource(source: LogSourceId) {
    if (currentSource.value === source) return
    currentSource.value = source
    await pollOnce(true)
  }

  async function setLevel(level: LogLevel | '') {
    if (levelFilter.value === level) return
    levelFilter.value = level
    await pollOnce(true)
  }

  async function setQuery(nextQuery: string) {
    const normalized = nextQuery.trim()
    if (query.value === normalized) return
    query.value = normalized
    await pollOnce(true)
  }

  function setAutoScroll(value: boolean) {
    autoScroll.value = value
  }

  function selectItem(itemId: string) {
    selectedItemId.value = itemId
  }

  function clearSelection() {
    selectedItemId.value = ''
  }

  async function applyFocusPreset(preset: LogFocusPreset) {
    focusReason.value = preset.reason
    focusOrigin.value = preset.origin
    currentSource.value = preset.source
    levelFilter.value = preset.level
    query.value = preset.query.trim()
    autoScroll.value = true
    await fetchSources()
    await pollOnce(true)
  }

  async function showAllLevels() {
    levelFilter.value = ''
    await pollOnce(true)
  }

  async function clearFocusReason() {
    focusReason.value = ''
    focusOrigin.value = ''
    levelFilter.value = ''
    query.value = ''
    await pollOnce(true)
  }

  async function refreshNow() {
    pollingSuspended.value = false
    errorKind.value = ''
    await fetchSources()
    await pollOnce(true)
  }

  async function downloadCurrentSource() {
    const result = await downloadLogFile(currentSource.value)
    downloadBlob(result.blob, result.filename)
  }

  async function exportBundle() {
    const result = await exportDiagnosticBundle()
    downloadBlob(result.blob, result.filename)
  }

  return {
    sources,
    currentSource,
    currentSourceMeta,
    currentSourceAvailable,
    levelFilter,
    query,
    items,
    isLoading,
    isPolling,
    error,
    errorKind,
    autoScroll,
    lastUpdatedAt,
    connectionName,
    connectionBaseUrl,
    pollingSuspended,
    selectedItemId,
    selectedItem,
    focusReason,
    focusOrigin,
    resetState,
    fetchSources,
    pollOnce,
    initialize,
    startPolling,
    stopPolling,
    setSource,
    setLevel,
    setQuery,
    setAutoScroll,
    selectItem,
    clearSelection,
    applyFocusPreset,
    showAllLevels,
    clearFocusReason,
    refreshNow,
    downloadCurrentSource,
    exportBundle,
  }
})
