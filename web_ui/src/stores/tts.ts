// TTS 配置 Store
// 管理 TTS 后端配置列表（localStorage 持久化）

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { TtsConfig } from '@/types'
import { createDefaultTtsConfig } from '@/types'

const STORAGE_KEY = 'unitale_tts_configs'
const CURRENT_KEY = 'unitale_tts_current'

export const useTtsStore = defineStore('tts', () => {
    // ── 状态 ──
    const configs = ref<TtsConfig[]>([])
    const currentConfigId = ref('')

    /** 当前选中的配置 */
    const currentConfig = computed(() =>
        configs.value.find(c => c.id === currentConfigId.value) || null,
    )

    // ── 表单 ──
    const form = ref<Partial<TtsConfig>>({ name: '', baseUrl: 'http://localhost:9880', apiKey: '' })
    const isEditing = ref(false)

    // ── 合成状态 ──
    const isLoading = ref(false)
    const error = ref('')

    // ── Actions ──

    function saveConfig() {
        const name = (form.value.name || '').trim()
        const baseUrl = (form.value.baseUrl || '').trim()
        const apiKey = (form.value.apiKey || '').trim()
        if (!name || !baseUrl) return

        if (isEditing.value && form.value.id) {
            // 编辑已有
            const idx = configs.value.findIndex(c => c.id === form.value.id)
            if (idx >= 0) {
                configs.value[idx] = { id: configs.value[idx]!.id, name, baseUrl, apiKey }
            }
        } else {
            // 新增
            configs.value.push(createDefaultTtsConfig({ name, baseUrl, apiKey }))
        }
        resetForm()
    }

    function editConfig(id: string) {
        const cfg = configs.value.find(c => c.id === id)
        if (!cfg) return
        form.value = { ...cfg }
        isEditing.value = true
    }

    function deleteConfig(id: string) {
        configs.value = configs.value.filter(c => c.id !== id)
        if (currentConfigId.value === id) {
            currentConfigId.value = configs.value[0]?.id || ''
        }
        ensureDefaultConfig()
    }

    function resetForm() {
        form.value = { name: '', baseUrl: 'http://localhost:9880', apiKey: '' }
        isEditing.value = false
    }

    // ── localStorage 持久化 ──

    function loadFromStorage() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY)
            if (raw) {
                const parsed = JSON.parse(raw)
                if (Array.isArray(parsed)) {
                    configs.value = parsed.map(cfg => createDefaultTtsConfig({
                        ...(cfg || {}),
                        id: String(cfg?.id || `tts_${Date.now()}`),
                        name: String(cfg?.name || ''),
                        baseUrl: String(cfg?.baseUrl || 'http://localhost:9880'),
                        apiKey: String(cfg?.apiKey || ''),
                    }))
                }
            }
            const cur = localStorage.getItem(CURRENT_KEY)
            if (cur) currentConfigId.value = cur
        } catch {
            // 忽略解析错误
        }
        ensureDefaultConfig()
    }

    function ensureDefaultConfig() {
        if (configs.value.length === 0) {
            const fallback = createDefaultTtsConfig({
                name: '本地默认',
                baseUrl: 'http://localhost:9880',
                apiKey: '',
            })
            configs.value = [fallback]
            currentConfigId.value = fallback.id
            return
        }
        if (!configs.value.some(c => c.id === currentConfigId.value)) {
            currentConfigId.value = configs.value[0]!.id
        }
    }

    // 监听变化自动保存
    watch(configs, val => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
    }, { deep: true })

    watch(currentConfigId, val => {
        localStorage.setItem(CURRENT_KEY, val)
    })

    // 初始加载
    loadFromStorage()

    ensureDefaultConfig()

    return {
        configs,
        currentConfigId,
        currentConfig,
        form,
        isEditing,
        isLoading,
        error,
        saveConfig,
        editConfig,
        deleteConfig,
        resetForm,
    }
})
