import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useTtsStore } from './tts'
import { useLlmStore } from './llm'
import { useProSystemStore } from './pro_system'
import { ensureRuntimeReady, isLocalTtsBaseUrl, probeLocalBridge } from '@/api/local_bridge'
import { probeLogsCapability } from '@/api/logs'
import { useShellStore } from './shell'
import type { SystemBridgeStatus, SystemLogsCapability, SystemRuntimeIncident, SystemRuntimeMode } from '@/types'

export const useSystemStore = defineStore('system', () => {
  const runtime = useProSystemStore()
  const tts = useTtsStore()
  const llm = useLlmStore()
  const shell = useShellStore()

  const currentTtsConfig = computed(() => tts.currentConfig)
  const currentLlmConfig = computed(() => llm.currentConfig)
  const apiKeyEnabled = computed(() => !!currentTtsConfig.value?.apiKey)
  const gpuName = computed(() => runtime.healthInfo?.gpu_name || '')
  const promptModeLabel = computed(() => llm.useCustomPrompt ? '自定义模板' : '默认模板')
  const canUseLocalBridge = computed(() => {
    return !!currentTtsConfig.value?.baseUrl && isLocalTtsBaseUrl(currentTtsConfig.value.baseUrl)
  })
  const runtimeMode = computed<SystemRuntimeMode>(() => {
    if (!currentTtsConfig.value?.baseUrl) return 'unknown'
    return canUseLocalBridge.value ? 'local' : 'remote'
  })
  const runtimeModeLabel = computed(() => {
    if (runtimeMode.value === 'local') return '本地模式'
    if (runtimeMode.value === 'remote') return '远程模式'
    return '未选择连接'
  })
  const bridgeStatus = ref<SystemBridgeStatus>('unknown')
  const logsCapability = ref<SystemLogsCapability>('unknown')
  const lastRuntimeIncident = ref<SystemRuntimeIncident | null>(null)
  const lastRuntimeActionAt = ref('')
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  const primaryRuntimeActionLabel = computed(() => {
    if (!runtime.isOnline) return canUseLocalBridge.value ? '启动服务并加载模型' : '请先启动远程服务'
    if (!runtime.isModelLoaded) return '加载模型'
    return '重载模型'
  })
  const bridgeStatusLabel = computed(() => {
    if (bridgeStatus.value === 'online') return '本地桥接在线'
    if (bridgeStatus.value === 'offline') return '本地桥接离线'
    if (bridgeStatus.value === 'unavailable') return '本地桥接不适用'
    return '本地桥接未检查'
  })
  const logsCapabilityLabel = computed(() => {
    if (logsCapability.value === 'supported') return '日志中心可用'
    if (logsCapability.value === 'missing') {
      return runtimeMode.value === 'local' ? '日志中心需重启后端' : '日志中心需升级远程服务'
    }
    return '日志能力未检查'
  })
  const logsCapabilityDetail = computed(() => {
    if (!currentTtsConfig.value?.baseUrl) return '请先选择 TTS 配置'
    if (logsCapability.value === 'supported') return '当前后端已提供日志接口，可直接进入日志页。'
    if (logsCapability.value === 'missing') {
      return runtimeMode.value === 'local'
        ? '当前后端为旧进程，需要重启 StartWebUI.bat 或重启本地 API 后再刷新。'
        : '当前远程后端未提供日志接口，请升级或重启远程服务。'
    }
    return runtime.isOnline ? '等待日志能力探测结果。' : '需先连接后端再探测日志能力。'
  })
  const logsCapabilityWarningTitle = computed(() => {
    if (logsCapability.value !== 'missing') return ''
    return runtimeMode.value === 'local' ? '当前后端为旧进程，需要重启以启用日志中心' : '当前远程后端版本过旧，需升级或重启'
  })
  const logsCapabilityWarningMessage = computed(() => {
    if (logsCapability.value !== 'missing') return ''
    return runtimeMode.value === 'local'
      ? '当前连接的本地后端在线，但未加载日志接口。请重启 StartWebUI.bat 或重启本地 API 后，再回到日志页刷新。'
      : '当前连接的远程后端在线，但未提供日志接口。请升级或重启远程服务后，再回到日志页刷新。'
  })

  const summaryCards = computed(() => [
    {
      id: 'service',
      label: '服务状态',
      value: runtime.statusLabel,
      meta: gpuName.value || '尚未连接 TTS 服务',
    },
    {
      id: 'tts',
      label: 'TTS 配置',
      value: currentTtsConfig.value?.name || '未选择',
      meta: currentTtsConfig.value?.baseUrl || '请先配置后端地址',
    },
    {
      id: 'llm',
      label: 'LLM 配置',
      value: currentLlmConfig.value?.name || '未选择',
      meta: currentLlmConfig.value?.model || '请先配置模型',
    },
    {
      id: 'prompt',
      label: 'Prompt 模板',
      value: promptModeLabel.value,
      meta: llm.useCustomPrompt ? '当前使用自定义分析模板' : '当前使用内置分析模板',
    },
    {
      id: 'runtime-mode',
      label: '运行模式',
      value: runtimeModeLabel.value,
      meta: bridgeStatusLabel.value,
    },
    {
      id: 'logs-capability',
      label: '日志中心',
      value: logsCapabilityLabel.value,
      meta: logsCapabilityDetail.value,
    },
  ])

  const readinessChecks = computed(() => [
    {
      id: 'tts-config',
      label: 'TTS 连接',
      detail: currentTtsConfig.value?.baseUrl || '未选择 TTS 配置',
      ok: !!currentTtsConfig.value,
    },
    {
      id: 'tts-auth',
      label: '鉴权状态',
      detail: apiKeyEnabled.value ? '已启用 API Key' : '未启用 API Key',
      ok: true,
    },
    {
      id: 'service-online',
      label: '服务联机',
      detail: runtime.isOnline ? '后端联机正常' : '当前无法连接后端',
      ok: runtime.isOnline,
    },
    {
      id: 'model-loaded',
      label: '模型状态',
      detail: runtime.isModelLoaded ? '模型已加载，可直接合成' : '模型未加载，需要重载',
      ok: runtime.isModelLoaded,
    },
    {
      id: 'llm-config',
      label: 'LLM 配置',
      detail: currentLlmConfig.value?.baseUrl || '未选择 LLM 配置',
      ok: !!currentLlmConfig.value,
    },
    {
      id: 'bridge',
      label: '本地桥接',
      detail: bridgeStatusLabel.value,
      ok: bridgeStatus.value === 'online' || bridgeStatus.value === 'unavailable',
    },
    {
      id: 'logs-capability',
      label: '日志中心',
      detail: logsCapabilityDetail.value,
      ok: logsCapability.value === 'supported',
    },
  ])

  function touchRuntimeAction() {
    lastRuntimeActionAt.value = new Date().toISOString()
  }

  function buildIncident(payload: Omit<SystemRuntimeIncident, 'id' | 'occurredAt'>): SystemRuntimeIncident {
    return {
      ...payload,
      id: `runtime_${Date.now()}`,
      occurredAt: new Date().toISOString(),
    }
  }

  function clearRuntimeIncident() {
    lastRuntimeIncident.value = null
  }

  function focusLogsForIncident(incident: SystemRuntimeIncident) {
    shell.openLogsWithFocus({
      source: incident.logSource,
      level: incident.logLevel,
      query: incident.query,
      reason: incident.detail,
      origin: 'system-runtime',
    })
  }

  function setRuntimeIncident(incident: SystemRuntimeIncident, options?: { openLogs?: boolean }) {
    lastRuntimeIncident.value = incident
    lastRuntimeActionAt.value = incident.occurredAt
    if (options?.openLogs) {
      focusLogsForIncident(incident)
    }
  }

  async function refreshBridgeStatus() {
    if (!currentTtsConfig.value?.baseUrl) {
      bridgeStatus.value = 'unknown'
      return bridgeStatus.value
    }
    if (!canUseLocalBridge.value) {
      bridgeStatus.value = 'unavailable'
      return bridgeStatus.value
    }
    const online = await probeLocalBridge()
    bridgeStatus.value = online ? 'online' : 'offline'
    return bridgeStatus.value
  }

  async function refreshLogsCapability() {
    if (!currentTtsConfig.value?.baseUrl || !runtime.isOnline) {
      logsCapability.value = 'unknown'
      return logsCapability.value
    }
    try {
      logsCapability.value = await probeLogsCapability()
    } catch {
      logsCapability.value = 'unknown'
    }
    return logsCapability.value
  }

  async function checkHealth() {
    const wasOnline = runtime.isOnline
    await runtime.checkHealth()
    await refreshBridgeStatus()
    await refreshLogsCapability()
    if (wasOnline && !runtime.isOnline && shell.activeTab === 'system') {
      const incident = buildIncident({
        kind: 'crash',
        level: 'ERROR',
        title: '服务连接中断',
        detail: runtime.error || '后端连接已中断，请查看崩溃日志或应用日志。',
        logSource: 'crash',
        logLevel: 'ERROR',
        query: '',
      })
      setRuntimeIncident(incident, { openLogs: true })
    }
  }

  function startHeartbeat() {
    stopHeartbeat()
    runtime.stopHeartbeat()
    void checkHealth()
    heartbeatTimer = setInterval(() => {
      void checkHealth()
    }, 5000)
  }

  function stopHeartbeat() {
    runtime.stopHeartbeat()
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  async function reloadModel() {
    touchRuntimeAction()
    try {
      const result = await runtime.reloadModel()
      clearRuntimeIncident()
      await refreshBridgeStatus()
      await refreshLogsCapability()
      return result
    } catch (e) {
      const message = (e as Error).message || '模型加载失败'
      const incident = buildIncident({
        kind: 'model',
        level: 'ERROR',
        title: '模型加载失败',
        detail: message,
        logSource: 'app',
        logLevel: 'ERROR',
        query: '',
      })
      setRuntimeIncident(incident, { openLogs: true })
      throw e
    }
  }

  async function unloadModel() {
    touchRuntimeAction()
    try {
      const result = await runtime.unloadModel()
      clearRuntimeIncident()
      await refreshBridgeStatus()
      await refreshLogsCapability()
      return result
    } catch (e) {
      const message = (e as Error).message || '模型卸载失败'
      const incident = buildIncident({
        kind: 'model',
        level: 'ERROR',
        title: '模型卸载失败',
        detail: message,
        logSource: 'app',
        logLevel: 'ERROR',
        query: '',
      })
      setRuntimeIncident(incident, { openLogs: true })
      throw e
    }
  }

  function getClient() {
    return runtime.getClient()
  }

  async function ensureRuntime() {
    const cfg = currentTtsConfig.value
    if (!cfg) {
      throw new Error('请先在系统页选择一个 TTS 配置')
    }
    touchRuntimeAction()
    if (!runtime.isOnline) {
      if (!canUseLocalBridge.value) {
        const error = new Error('当前是远程服务模式，请先在远程服务端启动后端。')
        const incident = buildIncident({
          kind: 'service',
          level: 'ERROR',
          title: '远程服务不可达',
          detail: error.message,
          logSource: 'app',
          logLevel: 'ERROR',
          query: '',
        })
        setRuntimeIncident(incident, { openLogs: true })
        throw error
      }
      const bridgeState = await refreshBridgeStatus()
      if (bridgeState !== 'online') {
        const error = new Error('本地桥接未运行，请使用 StartWebUI.bat 启动 WebUI。')
        const incident = buildIncident({
          kind: 'bridge',
          level: 'ERROR',
          title: '本地桥接离线',
          detail: error.message,
          logSource: 'local_bridge',
          logLevel: 'ERROR',
          query: '',
        })
        setRuntimeIncident(incident, { openLogs: true })
        throw error
      }
      try {
        const result = await ensureRuntimeReady({
          baseUrl: cfg.baseUrl,
          apiKey: cfg.apiKey || '',
        })
        await runtime.checkHealth()
        clearRuntimeIncident()
        await refreshBridgeStatus()
        await refreshLogsCapability()
        return result
      } catch (e) {
        const message = (e as Error).message || '本地桥接启动失败'
        const incident = buildIncident({
          kind: 'bridge',
          level: 'ERROR',
          title: '本地桥接启动失败',
          detail: message,
          logSource: 'local_bridge',
          logLevel: 'ERROR',
          query: '',
        })
        setRuntimeIncident(incident, { openLogs: true })
        throw e
      }
    }
    const result = await reloadModel()
    return {
      status: result.status,
      base_url: cfg.baseUrl,
      started_service: false,
      triggered_reload: true,
      model_loaded: true,
      health: runtime.healthInfo || {},
    }
  }

  function saveTtsConfig() {
    tts.saveConfig()
  }

  function editTtsConfig(id: string) {
    tts.editConfig(id)
  }

  function deleteTtsConfig(id: string) {
    tts.deleteConfig(id)
  }

  function selectTtsConfig(id: string) {
    tts.currentConfigId = id
  }

  function saveLlmConfig() {
    llm.saveConfig()
  }

  function editLlmConfig(id: string) {
    llm.editConfig(id)
  }

  function deleteLlmConfig(id: string) {
    llm.deleteConfig(id)
  }

  function selectLlmConfig(id: string) {
    llm.currentConfigId = id
  }

  return {
    isOnline: computed(() => runtime.isOnline),
    isModelLoaded: computed(() => runtime.isModelLoaded),
    healthInfo: computed(() => runtime.healthInfo),
    isLoading: computed(() => runtime.isLoading),
    error: computed(() => runtime.error),
    statusLabel: computed(() => runtime.statusLabel),
    gpuName,
    apiKeyEnabled,
    currentTtsConfig,
    currentLlmConfig,
    promptModeLabel,
    canUseLocalBridge,
    runtimeMode,
    runtimeModeLabel,
    bridgeStatus,
    bridgeStatusLabel,
    logsCapability,
    logsCapabilityLabel,
    logsCapabilityDetail,
    logsCapabilityWarningTitle,
    logsCapabilityWarningMessage,
    lastRuntimeIncident,
    lastRuntimeActionAt,
    primaryRuntimeActionLabel,
    summaryCards,
    readinessChecks,
    ttsConfigCount: computed(() => tts.configs.length),
    llmConfigCount: computed(() => llm.configs.length),
    startHeartbeat,
    stopHeartbeat,
    checkHealth,
    refreshBridgeStatus,
    refreshLogsCapability,
    reloadModel,
    unloadModel,
    ensureRuntime,
    clearRuntimeIncident,
    focusLogsForIncident,
    getClient,
    saveTtsConfig,
    editTtsConfig,
    deleteTtsConfig,
    selectTtsConfig,
    saveLlmConfig,
    editLlmConfig,
    deleteLlmConfig,
    selectLlmConfig,
    savePrompt: llm.savePrompt,
  }
})
