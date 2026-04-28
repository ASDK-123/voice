<script setup lang="ts">
// Pro 资产面板
// 提供正式的参考音频资产列表、过滤、试听、绑定、备注编辑

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useProVoiceStore } from '@/stores/pro_voice'
import type { Asset } from '@/types'

const props = withDefaults(defineProps<{
    inline?: boolean
}>(), {
    inline: false,
})

const emit = defineEmits<{
    close: []
}>()

const voiceStore = useProVoiceStore()

const keyword = ref('')
const characterFilter = ref('')
const emotionFilter = ref('')
const linkFilter = ref<'all' | 'linked' | 'unused'>('all')
const transcriptFilter = ref<'all' | 'complete' | 'legacy_only' | 'missing'>('all')
const selectedVoiceScope = ref<'all' | 'selected'>('all')
const actionError = ref('')
const actionMessage = ref('')

const uploadFile = ref<File | null>(null)
const isUploading = ref(false)
const bindToSelected = ref(true)
const uploadMeta = ref({
    character: '',
    emotion: 'default',
    note: '',
})

const noteDrafts = ref<Record<string, string>>({})
const transcriptDrafts = ref<Record<string, string>>({})
const audioUrls = ref<Record<string, string>>({})

const selectedVoice = computed(() => voiceStore.selectedVoice)

const characters = computed(() => {
    return Array.from(new Set(
        voiceStore.assets
            .map(asset => asset.character || '')
            .filter(Boolean),
    )).sort()
})

const emotions = computed(() => {
    const list = voiceStore.assets
        .filter(asset => !characterFilter.value || asset.character === characterFilter.value)
        .map(asset => asset.emotion || 'default')
    return Array.from(new Set(list)).sort()
})

const filteredAssets = computed(() => {
    const kw = keyword.value.trim().toLowerCase()
    return voiceStore.assets.filter(asset => {
        if (characterFilter.value && asset.character !== characterFilter.value) return false
        if (emotionFilter.value && (asset.emotion || 'default') !== emotionFilter.value) return false
        if (linkFilter.value === 'linked' && !asset.linked) return false
        if (linkFilter.value === 'unused' && asset.linked) return false
        if (transcriptFilter.value !== 'all' && voiceStore.getAssetTranscriptStatus(asset) !== transcriptFilter.value) return false
        if (selectedVoiceScope.value === 'selected' && !isBoundToSelected(asset.asset_id)) return false
        if (!kw) return true
        return [
            asset.asset_id,
            asset.note || '',
            asset.character || '',
            asset.emotion || '',
            asset.transcript_text || '',
            asset.prompt_text || '',
        ].some(value => value.toLowerCase().includes(kw))
    })
})

watch(
    () => voiceStore.assets,
    assets => {
        const nextNotes: Record<string, string> = {}
        const nextTranscripts: Record<string, string> = {}
        assets.forEach(asset => {
            nextNotes[asset.asset_id] = noteDrafts.value[asset.asset_id] ?? asset.note ?? ''
            nextTranscripts[asset.asset_id] = transcriptDrafts.value[asset.asset_id] ?? asset.transcript_text ?? asset.prompt_text ?? ''
        })
        noteDrafts.value = nextNotes
        transcriptDrafts.value = nextTranscripts
    },
    { immediate: true },
)

watch(
    selectedVoice,
    voice => {
        uploadMeta.value.character = voice?.character || characterFilter.value || ''
        uploadMeta.value.emotion = voice?.emotion || emotionFilter.value || 'default'
        if (!voice) {
            selectedVoiceScope.value = 'all'
        }
    },
    { immediate: true },
)

function isBoundToSelected(assetId: string): boolean {
    return !!selectedVoice.value?.ref_asset_ids?.includes(assetId)
}

function globalBindingText(asset: { linked: boolean; ref_count: number }): string {
    if (!asset.linked || asset.ref_count <= 0) return '未被任何音色引用'
    if (asset.ref_count === 1) return '已被 1 个音色引用'
    return `已被 ${asset.ref_count} 个音色引用`
}

function selectedBindingText(assetId: string): string {
    if (!selectedVoice.value) return '未选择音色'
    return isBoundToSelected(assetId) ? '已绑定到当前音色' : '未绑定到当前音色'
}

function transcriptStatusLabel(asset: Asset): string {
    const status = voiceStore.getAssetTranscriptStatus(asset)
    if (status === 'complete') return 'Transcript 已完成'
    if (status === 'legacy_only') return '仅 legacy 文本'
    return '缺少 transcript'
}

function bindingActionLabel(assetId: string): string {
    if (!selectedVoice.value) return '先选音色'
    return isBoundToSelected(assetId) ? '从当前音色解绑' : '绑定到当前音色'
}

function revokeAudioUrl(assetId: string) {
    const url = audioUrls.value[assetId]
    if (url) {
        URL.revokeObjectURL(url)
        delete audioUrls.value[assetId]
    }
}

async function refreshAssets() {
    actionError.value = ''
    await voiceStore.fetchAssets({ kind: 'ref' })
}

async function loadAudio(assetId: string) {
    actionError.value = ''
    if (audioUrls.value[assetId]) return
    try {
        const blob = await voiceStore.getAssetContent(assetId)
        audioUrls.value[assetId] = URL.createObjectURL(blob)
    } catch (e: unknown) {
        actionError.value = (e as Error).message
    }
}

async function saveAsset(assetId: string) {
    actionError.value = ''
    actionMessage.value = ''
    try {
        await voiceStore.updateAsset(assetId, {
            note: noteDrafts.value[assetId] || '',
            transcript_text: transcriptDrafts.value[assetId] || '',
            prompt_text: transcriptDrafts.value[assetId] || '',
        })
        actionMessage.value = `已保存 ${assetId}`
    } catch (e: unknown) {
        actionError.value = (e as Error).message
    }
}

async function toggleBinding(assetId: string) {
    if (!selectedVoice.value) {
        actionError.value = '请先在左侧选择一个音色，再进行绑定/解绑'
        return
    }

    actionError.value = ''
    actionMessage.value = ''
    try {
        if (isBoundToSelected(assetId)) {
            await voiceStore.unbindAssetFromVoice(selectedVoice.value.name, assetId)
            actionMessage.value = `已从 ${selectedVoice.value.name} 解绑`
        } else {
            await voiceStore.bindAssetToVoice(selectedVoice.value.name, assetId)
            actionMessage.value = `已绑定到 ${selectedVoice.value.name}`
        }
        await refreshAssets()
    } catch (e: unknown) {
        actionError.value = (e as Error).message
    }
}

async function handleDelete(assetId: string) {
    if (!confirm(`确定删除资产 ${assetId} 吗？`)) return
    actionError.value = ''
    actionMessage.value = ''
    try {
        await voiceStore.deleteAsset(assetId)
        revokeAudioUrl(assetId)
        actionMessage.value = `已删除 ${assetId}`
        await refreshAssets()
    } catch (e: unknown) {
        actionError.value = (e as Error).message
    }
}

function onFileChange(event: Event) {
    const input = event.target as HTMLInputElement
    uploadFile.value = input.files?.[0] || null
}

async function handleUpload() {
    if (!uploadFile.value) {
        actionError.value = '请选择要上传的音频文件'
        return
    }
    isUploading.value = true
    actionError.value = ''
    actionMessage.value = ''
    try {
        const asset = await voiceStore.uploadAsset(uploadFile.value, {
            character: uploadMeta.value.character.trim() || undefined,
            emotion: uploadMeta.value.emotion.trim() || 'default',
            note: uploadMeta.value.note.trim() || undefined,
        })
        if (bindToSelected.value && selectedVoice.value) {
            await voiceStore.bindAssetToVoice(selectedVoice.value.name, asset.asset_id)
        }
        actionMessage.value = `已上传 ${asset.asset_id}`
        uploadFile.value = null
        uploadMeta.value.note = ''
        await refreshAssets()
    } catch (e: unknown) {
        actionError.value = (e as Error).message
    } finally {
        isUploading.value = false
    }
}

onMounted(() => {
    void refreshAssets()
})

onBeforeUnmount(() => {
    Object.keys(audioUrls.value).forEach(revokeAudioUrl)
})
</script>

<template>
    <Teleport to="body" :disabled="props.inline">
        <div :class="props.inline ? 'assets-inline-shell' : 'assets-overlay'" @click.self="!props.inline && emit('close')">
            <div :class="props.inline ? 'assets-inline-panel' : 'assets-modal'">
                <div class="assets-header">
                    <div>
                        <h3 class="assets-title">参考音频资产</h3>
                        <p class="assets-subtitle">
                            当前共 {{ voiceStore.assets.length }} 项
                            <span v-if="selectedVoice">，当前绑定目标：{{ selectedVoice.name }}</span>
                        </p>
                    </div>
                    <button v-if="!props.inline" class="close-btn" @click="emit('close')">✕</button>
                </div>

                <div class="assets-toolbar">
                    <input
                        v-model="keyword"
                        type="text"
                        class="toolbar-input"
                        placeholder="搜索 asset_id / note / transcript"
                    />
                    <select v-model="characterFilter" class="toolbar-select">
                        <option value="">全部角色</option>
                        <option v-for="char in characters" :key="char" :value="char">{{ char }}</option>
                    </select>
                    <select v-model="emotionFilter" class="toolbar-select">
                        <option value="">全部情感</option>
                        <option v-for="emotion in emotions" :key="emotion" :value="emotion">{{ emotion }}</option>
                    </select>
                    <select v-model="linkFilter" class="toolbar-select">
                        <option value="all">全部</option>
                        <option value="linked">已绑定</option>
                        <option value="unused">未绑定</option>
                    </select>
                    <select v-model="transcriptFilter" class="toolbar-select">
                        <option value="all">全部 transcript</option>
                        <option value="complete">已完成 transcript</option>
                        <option value="legacy_only">仅 legacy 文本</option>
                        <option value="missing">缺少 transcript</option>
                    </select>
                    <select v-model="selectedVoiceScope" class="toolbar-select" :disabled="!selectedVoice">
                        <option value="all">全部资产</option>
                        <option value="selected">当前音色相关</option>
                    </select>
                    <button class="toolbar-btn" @click="refreshAssets">刷新</button>
                </div>

                <div class="upload-box">
                    <div class="upload-grid">
                        <input type="file" accept=".wav,.mp3,audio/wav,audio/mpeg" @change="onFileChange" />
                        <input v-model="uploadMeta.character" type="text" class="toolbar-input" placeholder="角色名" />
                        <input v-model="uploadMeta.emotion" type="text" class="toolbar-input" placeholder="情感标签" />
                        <input v-model="uploadMeta.note" type="text" class="toolbar-input" placeholder="备注" />
                    </div>
                    <label class="upload-bind">
                        <input v-model="bindToSelected" type="checkbox" :disabled="!selectedVoice" />
                        上传后自动绑定到当前选中音色
                    </label>
                    <button class="upload-btn" :disabled="isUploading" @click="handleUpload">
                        {{ isUploading ? '上传中...' : '上传资产' }}
                    </button>
                </div>

                <div v-if="actionError || voiceStore.error" class="assets-error">
                    {{ actionError || voiceStore.error }}
                </div>
                <div v-else-if="actionMessage" class="assets-message">
                    {{ actionMessage }}
                </div>

                <div class="assets-list">
                    <div v-if="filteredAssets.length === 0" class="assets-empty">
                        当前筛选条件下没有资产
                    </div>

                    <div v-for="asset in filteredAssets" :key="asset.asset_id" class="asset-row">
                        <div class="asset-main">
                            <div class="asset-topline">
                                <code class="asset-id">{{ asset.asset_id }}</code>
                                <span class="asset-badge" :class="asset.linked ? 'is-linked' : 'is-unused'">
                                    {{ asset.linked ? `已绑定 ${asset.ref_count}` : '未绑定' }}
                                </span>
                                <span
                                    class="asset-badge"
                                    :class="voiceStore.getAssetTranscriptStatus(asset) === 'complete'
                                        ? 'is-transcript-complete'
                                        : voiceStore.getAssetTranscriptStatus(asset) === 'legacy_only'
                                            ? 'is-transcript-legacy'
                                            : 'is-transcript-missing'"
                                >
                                    {{ transcriptStatusLabel(asset) }}
                                </span>
                                <span class="asset-meta-pill">{{ asset.character || '未分类' }}</span>
                                <span class="asset-meta-pill">{{ asset.emotion || 'default' }}</span>
                            </div>

                            <div class="asset-status-copy">
                                <p class="asset-status-line">
                                    <span class="asset-status-label">全局绑定状态</span>
                                    <span>{{ globalBindingText(asset) }}</span>
                                </p>
                                <p class="asset-status-line">
                                    <span class="asset-status-label">当前音色关系</span>
                                    <span>{{ selectedBindingText(asset.asset_id) }}</span>
                                </p>
                            </div>

                            <div class="asset-fields">
                                <input
                                    v-model="noteDrafts[asset.asset_id]"
                                    type="text"
                                    class="field-input"
                                    placeholder="备注"
                                />
                                <textarea
                                    v-model="transcriptDrafts[asset.asset_id]"
                                    class="field-textarea"
                                    rows="2"
                                    placeholder="Transcript / prompt_text"
                                ></textarea>
                            </div>

                            <audio
                                v-if="audioUrls[asset.asset_id]"
                                :src="audioUrls[asset.asset_id]"
                                controls
                                class="asset-audio"
                            ></audio>
                        </div>

                        <div class="asset-actions">
                            <button class="asset-btn" @click="loadAudio(asset.asset_id)">
                                {{ audioUrls[asset.asset_id] ? '已加载试听' : '试听' }}
                            </button>
                            <button class="asset-btn" @click="saveAsset(asset.asset_id)">保存备注</button>
                            <button
                                class="asset-btn"
                                :disabled="!selectedVoice"
                                @click="toggleBinding(asset.asset_id)"
                            >
                                {{ bindingActionLabel(asset.asset_id) }}
                            </button>
                            <button class="asset-btn danger" @click="handleDelete(asset.asset_id)">删除</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </Teleport>
</template>

<style scoped>
.assets-inline-shell {
    width: 100%;
}

.assets-inline-panel,
.assets-modal {
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(250, 251, 253, 0.98) 100%);
    border: 1px solid var(--color-border);
    border-radius: 20px;
    color: var(--color-text);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.assets-inline-panel {
    width: 100%;
    box-shadow: 0 20px 40px rgba(15, 23, 42, 0.08);
}

.assets-overlay {
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.48);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    backdrop-filter: blur(6px);
}

.assets-modal {
    width: min(1200px, 94vw);
    max-height: 88vh;
    box-shadow: 0 20px 40px rgba(15, 23, 42, 0.16);
}

.assets-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 18px 20px;
    border-bottom: 1px solid var(--color-divider);
}

.assets-title {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
}

.assets-subtitle {
    margin: 6px 0 0;
    font-size: 0.8rem;
    color: var(--color-text-tertiary);
}

.close-btn {
    border: 1px solid var(--color-border);
    background: var(--color-surface-soft);
    color: var(--color-text-secondary);
    font-size: 1rem;
    width: 32px;
    height: 32px;
    border-radius: 10px;
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;
}

.close-btn:hover {
    background: #e9eef5;
    border-color: var(--color-border-strong);
}

.assets-toolbar,
.upload-box {
    padding: 14px 20px;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--color-divider);
}

.toolbar-input,
.toolbar-select,
.field-input,
.field-textarea {
    border-radius: 10px;
    border: 1px solid var(--color-border);
    background: var(--color-input-bg);
    color: var(--color-text);
    font-size: 0.85rem;
    padding: 9px 12px;
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.toolbar-input::placeholder,
.field-input::placeholder,
.field-textarea::placeholder {
    color: var(--color-text-quaternary);
}

.toolbar-input:focus,
.toolbar-select:focus,
.field-input:focus,
.field-textarea:focus {
    border-color: rgba(10, 132, 255, 0.35);
    box-shadow: 0 0 0 3px var(--color-focus-ring);
}

.toolbar-input,
.field-input {
    min-width: 180px;
}

.toolbar-select {
    min-width: 130px;
}

.field-textarea {
    resize: vertical;
}

.toolbar-btn,
.upload-btn,
.asset-btn {
    border: 1px solid rgba(10, 132, 255, 0.18);
    background: #eef4ff;
    color: var(--color-primary);
    padding: 8px 12px;
    border-radius: 10px;
    cursor: pointer;
    font-size: 0.8rem;
    font-family: inherit;
    font-weight: 700;
    transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.toolbar-btn:hover,
.upload-btn:hover,
.asset-btn:hover:not(:disabled) {
    background: #e4efff;
    border-color: rgba(10, 132, 255, 0.24);
}

.asset-btn:disabled {
    opacity: 0.58;
    cursor: not-allowed;
}

.asset-btn.danger {
    background: #fff1f2;
    border-color: rgba(220, 38, 38, 0.2);
    color: var(--pro-danger);
}

.upload-grid {
    display: grid;
    grid-template-columns: minmax(220px, 1fr) repeat(3, minmax(120px, 1fr));
    gap: 10px;
    width: 100%;
}

.upload-bind {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.8rem;
    color: var(--color-text-secondary);
}

.assets-error,
.assets-message,
.assets-empty {
    margin: 12px 20px 0;
    padding: 10px 12px;
    border-radius: 10px;
    font-size: 0.82rem;
}

.assets-error {
    background: #fff1f2;
    border: 1px solid rgba(220, 38, 38, 0.16);
    color: var(--pro-danger);
}

.assets-message {
    background: #edf9f0;
    border: 1px solid rgba(21, 128, 61, 0.16);
    color: var(--pro-success);
}

.assets-empty {
    background: var(--color-surface-muted);
    color: var(--color-text-tertiary);
    border: 1px dashed var(--color-border);
}

.assets-list {
    padding: 16px 20px 20px;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.asset-row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 14px;
    border: 1px solid var(--color-border);
    border-radius: 14px;
    background: var(--color-surface);
    padding: 14px;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
}

.asset-main {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
}

.asset-topline {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.asset-id {
    color: var(--color-text);
    font-size: 0.78rem;
    font-weight: 700;
}

.asset-badge,
.asset-meta-pill {
    font-size: 0.72rem;
    padding: 3px 8px;
    border-radius: 999px;
}

.asset-badge.is-linked {
    background: #edf9f0;
    color: var(--pro-success);
    border: 1px solid rgba(21, 128, 61, 0.16);
}

.asset-badge.is-unused {
    background: #fff7ed;
    color: var(--pro-warning);
    border: 1px solid rgba(180, 83, 9, 0.16);
}

.asset-badge.is-transcript-complete {
    background: #edf9f0;
    color: var(--pro-success);
    border: 1px solid rgba(21, 128, 61, 0.16);
}

.asset-badge.is-transcript-legacy {
    background: #fff7ed;
    color: var(--pro-warning);
    border: 1px solid rgba(180, 83, 9, 0.16);
}

.asset-badge.is-transcript-missing {
    background: #fff1f2;
    color: var(--pro-danger);
    border: 1px solid rgba(190, 24, 93, 0.16);
}

.asset-meta-pill {
    background: var(--color-surface-soft);
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
}

.asset-status-copy {
    display: grid;
    gap: 6px;
}

.asset-status-line {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    color: var(--color-text-secondary);
    font-size: 0.8rem;
    line-height: 1.5;
}

.asset-status-label {
    color: var(--color-text-tertiary);
    font-weight: 700;
}

.asset-fields {
    display: grid;
    grid-template-columns: minmax(160px, 240px) 1fr;
    gap: 10px;
}

.asset-audio {
    width: min(420px, 100%);
    height: 34px;
}

.asset-actions {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 96px;
}

@media (max-width: 900px) {
    .upload-grid,
    .asset-fields,
    .asset-row {
        grid-template-columns: 1fr;
    }

    .asset-actions {
        flex-direction: row;
        flex-wrap: wrap;
    }
}
</style>
