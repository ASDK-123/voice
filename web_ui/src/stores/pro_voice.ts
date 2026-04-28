// Pro Voice Store
// WebUI 正式音色域：负责音色与参考资产的官方工作流
// 不再依赖 pro_system 传递客户端，统一走共享连接工厂

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { createCosyVoiceClientFromActiveConfig } from '@/api/client_factory'
import type {
    Asset,
    AssetTranscriptStatus,
    LegacyImportExecuteResult,
    LegacyImportOptions,
    LegacyImportPreviewResult,
    VoiceCreatePayload,
} from '@/types'

/** 音色项（兼容后端返回的任意格式） */
export interface ProVoiceItem {
    name: string
    character: string
    emotion: string
    mode: 'zero_shot' | 'instruct' | 'cross_lingual'
    prompt_text: string
    prompt_audio: string
    selection_policy: 'random_per_text' | 'round_robin' | 'first'
    ref_asset_ids: string[]
    color?: string
}

export const useProVoiceStore = defineStore('proVoice', () => {
    // ── 状态 ──
    const voices = ref<ProVoiceItem[]>([])
    const assets = ref<Asset[]>([])
    const selectedVoiceId = ref('')
    const isLoading = ref(false)
    const error = ref('')
    const searchKeyword = ref('')

    /** WebUI 正式音色域统一使用 v2 client，连接配置来自系统域当前 TTS 配置 */
    function getVoiceClient() {
        return createCosyVoiceClientFromActiveConfig()
    }

    /** 拉取音色列表 */
    async function fetchVoices() {
        isLoading.value = true
        error.value = ''
        try {
            const items = await getVoiceClient().listVoices()
            voices.value = items.map((v: any) => ({
                name: v.name || '',
                character: v.character || '',
                emotion: v.emotion || '',
                mode: (v.mode || 'zero_shot') as ProVoiceItem['mode'],
                prompt_text: v.prompt_text || '',
                prompt_audio: v.prompt_audio || '',
                selection_policy: (v.selection_policy || 'random_per_text') as ProVoiceItem['selection_policy'],
                ref_asset_ids: Array.isArray(v.ref_asset_ids) ? [...v.ref_asset_ids] : [],
                color: v.color || '#6366F1',
            }))
        } catch (e: unknown) {
            error.value = (e as Error).message
        } finally {
            isLoading.value = false
        }
    }

    /** 过滤后的音色列表（搜索关键词过滤） */
    const filteredVoices = computed(() => {
        const kw = searchKeyword.value.toLowerCase().trim()
        if (!kw) return voices.value
        return voices.value.filter(
            v =>
                v.name.toLowerCase().includes(kw) ||
                v.character.toLowerCase().includes(kw) ||
                v.emotion.toLowerCase().includes(kw),
        )
    })

    /**
     * 按角色分组（基于 filteredVoices，搜索时自动收敛）。
     * 修复原有 bug：原来 characters 基于全量 voices，搜索不生效。
     */
    const characters = computed(() => {
        const map = new Map<string, ProVoiceItem[]>()
        for (const v of filteredVoices.value) {
            const char = v.character || '未分类'
            if (!map.has(char)) map.set(char, [])
            map.get(char)!.push(v)
        }
        return map
    })

    /** 选择音色 */
    function selectVoice(voiceId: string) {
        selectedVoiceId.value = voiceId
    }

    /** 获取当前选中的音色详情 */
    const selectedVoice = computed(() => {
        return voices.value.find(v => v.name === selectedVoiceId.value) || null
    })

    /** 拉取参考音频资产 */
    async function fetchAssets(filter?: { character?: string; emotion?: string; kind?: string }) {
        isLoading.value = true
        error.value = ''
        try {
            assets.value = await getVoiceClient().listAssets(filter)
        } catch (e: unknown) {
            error.value = (e as Error).message
        } finally {
            isLoading.value = false
        }
    }

    function getVoiceOrThrow(voiceName: string): ProVoiceItem {
        const voice = voices.value.find(v => v.name === voiceName)
        if (!voice) throw new Error(`音色不存在: ${voiceName}`)
        return voice
    }

    function getAssetTranscriptStatus(asset: Asset): AssetTranscriptStatus {
        const transcript = String(asset.transcript_text || '').trim()
        if (transcript) return 'complete'
        const legacy = String(asset.prompt_text || '').trim()
        if (legacy) return 'legacy_only'
        return 'missing'
    }

    async function updateVoiceRefs(voiceName: string, refAssetIds: string[]) {
        const voice = getVoiceOrThrow(voiceName)
        await getVoiceClient().updateVoice(voice.name, {
            name: voice.name,
            character: voice.character,
            emotion: voice.emotion,
            mode: voice.mode,
            prompt_text: voice.prompt_text || '',
            selection_policy: voice.selection_policy || 'random_per_text',
            ref_asset_ids: refAssetIds,
            color: voice.color,
        })
        await fetchVoices()
    }

    async function updateVoice(originalName: string, payload: VoiceCreatePayload) {
        isLoading.value = true
        error.value = ''
        try {
            const saved = await getVoiceClient().updateVoice(originalName, payload)
            await fetchVoices()
            selectedVoiceId.value = saved.name
            return saved
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    async function bulkRenameCharacterVoices(payload: {
        character: string
        nextCharacter: string
        items: Array<{
            originalName: string
            nextEmotion: string
        }>
    }) {
        isLoading.value = true
        error.value = ''
        const successes: Array<{ originalName: string; nextName: string }> = []
        const failures: Array<{ originalName: string; nextName: string; message: string }> = []
        const nextCharacter = payload.nextCharacter.trim()
        const selectedBefore = selectedVoiceId.value
        try {
            for (const item of payload.items) {
                const voice = getVoiceOrThrow(item.originalName)
                const nextEmotion = item.nextEmotion.trim()
                const nextName = `${nextCharacter}#${nextEmotion}`
                try {
                    await getVoiceClient().updateVoice(item.originalName, {
                        name: nextName,
                        character: nextCharacter,
                        emotion: nextEmotion,
                        mode: voice.mode,
                        prompt_text: voice.prompt_text || '',
                        selection_policy: voice.selection_policy || 'random_per_text',
                        ref_asset_ids: [...(voice.ref_asset_ids || [])],
                        color: voice.color,
                    })
                    successes.push({ originalName: item.originalName, nextName })
                } catch (e: unknown) {
                    failures.push({
                        originalName: item.originalName,
                        nextName,
                        message: (e as Error).message,
                    })
                }
            }
            await fetchVoices()
            await fetchAssets({ kind: 'ref' })
            const selectedRenamed = successes.find(item => item.originalName === selectedBefore)
            if (selectedRenamed) {
                selectedVoiceId.value = selectedRenamed.nextName
            }
            return { successes, failures }
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    async function bindAssetToVoice(voiceName: string, assetId: string) {
        const voice = getVoiceOrThrow(voiceName)
        const nextRefs = Array.from(new Set([...(voice.ref_asset_ids || []), assetId]))
        await updateVoiceRefs(voiceName, nextRefs)
    }

    async function unbindAssetFromVoice(voiceName: string, assetId: string) {
        const voice = getVoiceOrThrow(voiceName)
        const nextRefs = (voice.ref_asset_ids || []).filter(id => id !== assetId)
        await updateVoiceRefs(voiceName, nextRefs)
    }

    async function uploadAssetForVoice(voiceName: string, file: File, note = '') {
        isLoading.value = true
        error.value = ''
        try {
            const voice = getVoiceOrThrow(voiceName)
            const asset = await getVoiceClient().uploadAsset(file, {
                character: voice.character,
                emotion: voice.emotion || 'default',
                note,
            })
            await bindAssetToVoice(voiceName, asset.asset_id)
            await fetchAssets({ character: voice.character, kind: 'ref' })
            return asset
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    async function uploadAsset(file: File, meta: { character?: string; emotion?: string; note?: string } = {}) {
        isLoading.value = true
        error.value = ''
        try {
            const asset = await getVoiceClient().uploadAsset(file, meta)
            await fetchAssets({ kind: 'ref' })
            return asset
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    async function updateAsset(assetId: string, payload: {
        note?: string
        transcript_text?: string
        prompt_text?: string
        character?: string
        emotion?: string
        language?: string
        linked?: boolean
    }) {
        isLoading.value = true
        error.value = ''
        try {
            const asset = await getVoiceClient().updateAsset(assetId, payload)
            assets.value = assets.value.map(item => item.asset_id === assetId ? asset : item)
            return asset
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    async function getAssetContent(assetId: string) {
        error.value = ''
        try {
            return await getVoiceClient().getAssetContent(assetId)
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        }
    }

    async function deleteAsset(assetId: string) {
        isLoading.value = true
        error.value = ''
        try {
            await getVoiceClient().deleteAsset(assetId)
            assets.value = assets.value.filter(asset => asset.asset_id !== assetId)
            await fetchVoices()
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    async function deleteAssetFromVoice(voiceName: string, assetId: string) {
        await unbindAssetFromVoice(voiceName, assetId)
        await deleteAsset(assetId)
    }

    async function compileVoice(voiceName: string, compileAll = false) {
        isLoading.value = true
        error.value = ''
        try {
            return await getVoiceClient().compileVoice(voiceName, compileAll)
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    async function previewLegacyImport(
        file: File,
        options: LegacyImportOptions = {},
    ): Promise<LegacyImportPreviewResult> {
        isLoading.value = true
        error.value = ''
        try {
            return await getVoiceClient().importLegacyVoices(file, {
                ...options,
                dryRun: true,
            }) as LegacyImportPreviewResult
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    async function executeLegacyImport(
        file: File,
        options: LegacyImportOptions = {},
    ): Promise<LegacyImportExecuteResult> {
        isLoading.value = true
        error.value = ''
        try {
            const result = await getVoiceClient().importLegacyVoices(file, {
                ...options,
                dryRun: false,
            }) as LegacyImportExecuteResult
            await fetchVoices()
            await fetchAssets({ kind: 'ref' })
            return result
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    /** 创建一个音色（真实后端 CRUD） */
    async function createVoice(payload: VoiceCreatePayload) {
        isLoading.value = true
        error.value = ''
        try {
            const saved = await getVoiceClient().createVoice(payload)
            await fetchVoices()
            selectedVoiceId.value = saved.name
            return saved
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    /** 删除一个音色（真实后端 CRUD） */
    async function deleteVoice(voiceName: string) {
        isLoading.value = true
        error.value = ''
        try {
            await getVoiceClient().deleteVoice(voiceName)
            await fetchVoices()
            if (selectedVoiceId.value === voiceName) {
                selectedVoiceId.value = ''
            }
        } catch (e: unknown) {
            error.value = (e as Error).message
            throw e
        } finally {
            isLoading.value = false
        }
    }

    return {
        voices,
        assets,
        selectedVoiceId,
        isLoading,
        error,
        searchKeyword,
        characters,
        filteredVoices,
        selectedVoice,
        fetchVoices,
        fetchAssets,
        createVoice,
        updateVoice,
        bulkRenameCharacterVoices,
        selectVoice,
        deleteVoice,
        bindAssetToVoice,
        unbindAssetFromVoice,
        uploadAsset,
        uploadAssetForVoice,
        updateAsset,
        getAssetContent,
        deleteAsset,
        deleteAssetFromVoice,
        compileVoice,
        previewLegacyImport,
        executeLegacyImport,
        getAssetTranscriptStatus,
    }
})
