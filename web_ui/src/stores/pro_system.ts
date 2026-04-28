// Pro System Store
// 运行时兼容层：只负责健康检查、心跳与模型控制
// 连接配置的唯一来源是全局 tts store，不再在此重复维护 baseUrl/apiKey 状态

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ProHealthStatus } from '@/types'
import { createCosyVoiceClientFromActiveConfig } from '@/api/client_factory'

export const useProSystemStore = defineStore('proSystem', () => {
    const isOnline = ref(false)
    const isModelLoaded = ref(false)
    const healthInfo = ref<ProHealthStatus | null>(null)
    const isLoading = ref(false)
    const error = ref('')

    // ── 心跳定时器 ──
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null

    /** 获取 API 客户端实例（带鉴权） */
    function getClient() {
        return createCosyVoiceClientFromActiveConfig()
    }

    /**
     * 执行一次健康检查。
     * 核心规则：
     * - 网络请求成功 → isOnline = true
     * - status === 'ok' 且 model_loaded → isModelLoaded = true
     * - status === 'degraded'（模型未加载）→ isOnline 仍为 true，但 isModelLoaded = false
     * - 网络请求失败 → isOnline = false, isModelLoaded = false
     */
    async function checkHealth() {
        try {
            const result = await getClient().health()
            healthInfo.value = result
            // 只要服务端有响应（无论 ok / degraded），就认定"在线"
            isOnline.value = true
            // 模型加载状态独立判断
            isModelLoaded.value = !!result.model_loaded
            error.value = ''
        } catch (e: unknown) {
            isOnline.value = false
            isModelLoaded.value = false
            healthInfo.value = null
            error.value = (e as Error).message
        }
    }

    /** 启动心跳检测（每 5 秒） */
    function startHeartbeat() {
        stopHeartbeat()
        // 立即执行一次
        checkHealth()
        heartbeatTimer = setInterval(checkHealth, 5000)
    }

    /** 停止心跳检测 */
    function stopHeartbeat() {
        if (heartbeatTimer) {
            clearInterval(heartbeatTimer)
            heartbeatTimer = null
        }
    }

    /** 系统摘要描述（UI 用） */
    const statusLabel = computed(() => {
        if (!isOnline.value) return '离线'
        if (!isModelLoaded.value) return '在线（模型未加载）'
        return '在线'
    })

    /** 卸载模型（释放显存） */
    async function unloadModel() {
        isLoading.value = true
        error.value = ''
        try {
            const result = await getClient().unloadModel()
            // 卸载后刷新健康状态
            await checkHealth()
            return result
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    /** 重载模型 */
    async function reloadModel() {
        isLoading.value = true
        error.value = ''
        try {
            const result = await getClient().reloadModel()
            // 重载后刷新健康状态
            await checkHealth()
            return result
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    return {
        isOnline,
        isModelLoaded,
        healthInfo,
        isLoading,
        error,
        statusLabel,
        getClient,
        checkHealth,
        startHeartbeat,
        stopHeartbeat,
        unloadModel,
        reloadModel,
    }
})
