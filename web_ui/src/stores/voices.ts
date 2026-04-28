// Voices Store
// 剧本域兼容音色 Store：主要服务 Script Studio 的角色匹配与单行合成
// 正式音色与资产管理主线已迁移到 pro_voice 域

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Voice, Asset } from '@/types'
import { createCosyVoiceClientFromActiveConfig } from '@/api/client_factory'

export const useVoicesStore = defineStore('voices', () => {
    // ── 状态 ──
    const v2Voices = ref<Voice[]>([])
    const v2Assets = ref<Asset[]>([])
    const isLoading = ref(false)
    const panelError = ref('')

    /** P6.1: 提取所有可用角色身份（去重） */
    const uniqueCharacters = computed(() => {
        const chars = new Set<string>()
        v2Voices.value.forEach(v => {
            if (v.character) chars.add(v.character)
            else if (v.name && v.name.includes('#')) {
                const parts = v.name.split('#')
                if (parts[0]) chars.add(parts[0])
            }
        })
        return Array.from(chars).sort()
    })

    // ── 获取 API Client ──

    function getClient() {
        return createCosyVoiceClientFromActiveConfig()
    }

    // ── Voices CRUD ──

    async function refreshVoices() {
        isLoading.value = true
        panelError.value = ''
        try {
            v2Voices.value = await getClient().listVoices()
        } catch (e: unknown) {
            panelError.value = (e as Error).message
        } finally {
            isLoading.value = false
        }
    }

    // ── Voice 解析（合成时使用） ──

    /** 根据角色名+情绪查找最匹配的 voice_id */
    function pickVoiceId(character: string, emotion: string): string | null {
        const normalEmo = (emotion || '中立').trim()

        // 1. 精确匹配 "角色#情绪"
        const exactKey = `${character}#${normalEmo}`
        if (v2Voices.value.some(v => v.name === exactKey)) {
            return exactKey
        }

        // 2. 回退 "角色#default"
        const defaultKey = `${character}#default`
        if (v2Voices.value.some(v => v.name === defaultKey)) {
            return defaultKey
        }

        // 3. character 字段匹配
        const match = v2Voices.value.find(v => v.character === character)
        if (match) return match.name

        return null
    }
    return {
        v2Voices,
        v2Assets,
        isLoading,
        panelError,
        uniqueCharacters,
        refreshVoices,
        pickVoiceId,
    }
})
