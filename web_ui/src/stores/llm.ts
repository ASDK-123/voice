// LLM 配置与聊天 Store
// 管理 LLM 配置、SSE 流式聊天、自定义 Prompt

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { LlmConfig } from '@/types'
import { createDefaultLlmConfig } from '@/types'

const STORAGE_KEY = 'unitale_llm_configs'
const CURRENT_KEY = 'unitale_llm_current'
const PROMPT_KEY = 'unitale_prompt_template'
const USE_CUSTOM_KEY = 'unitale_use_custom_prompt'

export const useLlmStore = defineStore('llm', () => {
    // ── 配置管理 ──
    const configs = ref<LlmConfig[]>([])
    const currentConfigId = ref('')
    const currentConfig = computed(() =>
        configs.value.find(c => c.id === currentConfigId.value) || null,
    )

    const form = ref<Partial<LlmConfig>>({ name: '', baseUrl: '', model: '', key: '', params: '' })
    const isEditing = ref(false)

    // ── 模型列表查询 ──
    const availableModels = ref<string[]>([])
    const modelsFetching = ref(false)
    const modelsError = ref('')

    // ── 聊天状态 ──
    const prompt = ref('')
    const result = ref('')
    const reasoning = ref('')
    const error = ref('')
    const loading = ref(false)
    const abortController = ref<AbortController | null>(null)

    // ── 自定义 Prompt ──
    const customPromptTemplate = ref('')
    const useCustomPrompt = ref(false)

    // ── 配置 CRUD ──

    function saveConfig() {
        const name = (form.value.name || '').trim()
        const baseUrl = (form.value.baseUrl || '').trim()
        if (!name || !baseUrl) return

        if (isEditing.value && form.value.id) {
            const idx = configs.value.findIndex(c => c.id === form.value.id)
            if (idx >= 0) {
                configs.value[idx] = {
                    id: configs.value[idx]!.id,
                    name,
                    baseUrl,
                    model: form.value.model || '',
                    key: form.value.key || '',
                    params: form.value.params || '',
                }
            }
        } else {
            configs.value.push(createDefaultLlmConfig({
                name,
                baseUrl,
                model: form.value.model || '',
                key: form.value.key || '',
                params: form.value.params || '',
            }))
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
    }

    function resetForm() {
        form.value = { name: '', baseUrl: '', model: '', key: '', params: '' }
        isEditing.value = false
        availableModels.value = []
        modelsError.value = ''
    }

    /** 查询可用模型列表（OpenAI 兼容 /v1/models 接口） */
    async function fetchModels() {
        const baseUrl = (form.value.baseUrl || '').trim().replace(/\/+$/, '')
        if (!baseUrl) {
            modelsError.value = '请先填写 Base URL'
            return
        }

        modelsFetching.value = true
        modelsError.value = ''
        availableModels.value = []

        try {
            // 构建 models 端点 URL
            let modelsUrl = baseUrl
            if (modelsUrl.endsWith('/chat/completions')) {
                modelsUrl = modelsUrl.replace('/chat/completions', '/models')
            } else if (modelsUrl.endsWith('/v1')) {
                modelsUrl += '/models'
            } else if (!modelsUrl.endsWith('/models')) {
                // 尝试拼接 /v1/models 或 /models
                modelsUrl = modelsUrl.replace(/\/v1\/?$/, '') + '/v1/models'
            }

            const headers: Record<string, string> = { 'Content-Type': 'application/json' }
            const apiKey = (form.value.key || '').trim()
            if (apiKey) {
                headers['Authorization'] = `Bearer ${apiKey}`
            }

            const res = await fetch(modelsUrl, { method: 'GET', headers })

            if (!res.ok) {
                const text = await res.text()
                throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`)
            }

            const data = await res.json()

            // 兼容多种返回格式
            let models: string[] = []
            if (data.data && Array.isArray(data.data)) {
                // OpenAI 格式: { data: [{ id: "gpt-4" }, ...] }
                models = data.data.map((m: { id?: string; name?: string }) => m.id || m.name || '').filter(Boolean)
            } else if (data.models && Array.isArray(data.models)) {
                // Ollama 等格式: { models: [{ name: "...", model: "..." }, ...] }
                models = data.models.map((m: { name?: string; model?: string }) => m.model || m.name || '').filter(Boolean)
            } else if (Array.isArray(data)) {
                // 纯数组格式
                models = data.map((m: string | { id?: string }) => typeof m === 'string' ? m : (m.id || '')).filter(Boolean)
            }

            if (models.length === 0) {
                modelsError.value = '未找到可用模型（接口返回为空）'
            } else {
                availableModels.value = models.sort()
            }
        } catch (e: unknown) {
            const err = e as Error
            modelsError.value = err.message
            if (err.message.includes('Failed to fetch')) {
                modelsError.value += '\n可能是 CORS 限制或地址不正确'
            }
        } finally {
            modelsFetching.value = false
        }
    }

    // ── 流式聊天 ──

    async function send() {
        const cfg = currentConfig.value
        if (!cfg) return

        loading.value = true
        result.value = ''
        reasoning.value = ''
        error.value = ''
        abortController.value = new AbortController()

        try {
            let url = cfg.baseUrl.trim().replace(/\/+$/, '')
            if (!url.endsWith('/chat/completions')) {
                url += '/chat/completions'
            }

            let body: Record<string, unknown> = {
                model: cfg.model,
                messages: [{ role: 'user', content: prompt.value }],
                stream: true,
            }

            // 合并额外参数
            if (cfg.params) {
                try {
                    const extraParams = JSON.parse(cfg.params)
                    body = { ...body, ...extraParams }
                } catch {
                    console.warn('解析额外参数失败')
                }
            }

            const res = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${cfg.key}`,
                },
                body: JSON.stringify(body),
                signal: abortController.value.signal,
            })

            if (!res.ok) {
                const errData = await res.text()
                throw new Error(`HTTP ${res.status}: ${errData}`)
            }

            const reader = res.body!.getReader()
            const decoder = new TextDecoder()
            let buffer = ''

            while (true) {
                const { done, value } = await reader.read()
                if (done) break

                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split('\n')
                buffer = lines.pop()! // 保持最后一行完整

                for (const line of lines) {
                    const cleanLine = line.replace(/^data: /, '').trim()
                    if (!cleanLine || cleanLine === '[DONE]') continue

                    try {
                        const json = JSON.parse(cleanLine)
                        const delta = json.choices?.[0]?.delta
                        if (delta?.reasoning_content) {
                            reasoning.value += delta.reasoning_content
                        }
                        if (delta?.content) {
                            result.value += delta.content
                        }
                    } catch {
                        // 忽略部分解析错误
                    }
                }
            }
        } catch (e: unknown) {
            const err = e as Error
            if (err.name === 'AbortError') {
                // 用户手动停止
            } else {
                error.value = err.message
                if (err.message.includes('Failed to fetch')) {
                    error.value += '\n\n检测到跨域(CORS)限制！建议：开启浏览器 CORS 插件，或使用后端中转。'
                }
            }
        } finally {
            loading.value = false
            abortController.value = null
        }
    }

    function stopGeneration() {
        if (abortController.value) {
            abortController.value.abort()
            abortController.value = null
            loading.value = false
        }
    }

    function clearAll() {
        prompt.value = ''
        result.value = ''
        reasoning.value = ''
        error.value = ''
    }

    // ── Prompt 管理 ──

    function savePrompt() {
        localStorage.setItem(PROMPT_KEY, customPromptTemplate.value)
        localStorage.setItem(USE_CUSTOM_KEY, JSON.stringify(useCustomPrompt.value))
    }

    function resetPrompt() {
        customPromptTemplate.value = ''
    }

    // ── localStorage 持久化 ──

    function loadFromStorage() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY)
            if (raw) configs.value = JSON.parse(raw)
            const cur = localStorage.getItem(CURRENT_KEY)
            if (cur) currentConfigId.value = cur
            const pt = localStorage.getItem(PROMPT_KEY)
            if (pt) customPromptTemplate.value = pt
            const uc = localStorage.getItem(USE_CUSTOM_KEY)
            if (uc) useCustomPrompt.value = JSON.parse(uc)
        } catch {
            // 忽略
        }
    }

    watch(configs, val => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
    }, { deep: true })

    watch(currentConfigId, val => {
        localStorage.setItem(CURRENT_KEY, val)
    })

    loadFromStorage()

    return {
        configs,
        currentConfigId,
        currentConfig,
        form,
        isEditing,
        availableModels,
        modelsFetching,
        modelsError,
        prompt,
        result,
        reasoning,
        error,
        loading,
        customPromptTemplate,
        useCustomPrompt,
        saveConfig,
        editConfig,
        deleteConfig,
        resetForm,
        fetchModels,
        send,
        stopGeneration,
        clearAll,
        savePrompt,
        resetPrompt,
    }
})
