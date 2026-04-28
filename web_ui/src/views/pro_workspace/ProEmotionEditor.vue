<script setup lang="ts">
// Pro 情感资产编辑器
// 管理单个角色的多套情感（default, happy, sad 等）参考音频资产
// 对应原 PyQt emotion_voices.py 的功能

import { computed, nextTick, ref, watch } from 'vue'
import { useProVoiceStore } from '@/stores/pro_voice'
import { buildEmotionCatalog, normalizeEmotionTag } from '@/utils/emotion'
import {
    ArrowUpTrayIcon,
    CheckCircleIcon,
    ExclamationTriangleIcon,
    LinkIcon,
    MusicalNoteIcon,
    PlusIcon,
    SparklesIcon,
    TrashIcon,
    XMarkIcon,
} from '@heroicons/vue/24/outline'

const props = defineProps<{
    /** 当前选中的角色名 */
    characterName: string
}>()

const emit = defineEmits<{
    close: []
}>()

const voiceStore = useProVoiceStore()

const characterVoices = computed(() => {
    return voiceStore.voices.filter(v => v.character === props.characterName)
})

const selectedEmotion = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const uploadCardRef = ref<HTMLElement | null>(null)
const uploadError = ref('')
const addInfo = ref('')
const isUploading = ref(false)
const isCreatingEmotion = ref(false)
const pendingBindAssetId = ref('')
const pendingUnbindAssetId = ref('')
const pendingDeleteAssetId = ref('')
const pendingDeleteVoiceName = ref('')
const showAddForm = ref(false)
const newEmotionName = ref('')
const addError = ref('')

watch(() => characterVoices.value, list => {
    if (list.length === 0) {
        selectedEmotion.value = ''
        return
    }

    const exists = list.some(v => v.emotion === selectedEmotion.value)
    if (!selectedEmotion.value || !exists) {
        const defaultVoice = list.find(v => normalizeEmotionTag(v.emotion) === 'default')
        selectedEmotion.value = defaultVoice?.emotion || list[0]!.emotion
    }
}, { immediate: true })

watch(
    () => props.characterName,
    char => {
        selectedEmotion.value = ''
        addInfo.value = ''
        uploadError.value = ''
        addError.value = ''
        showAddForm.value = false
        if (char) {
            void voiceStore.fetchAssets({ character: char, kind: 'ref' })
        }
    },
    { immediate: true },
)

const selectedVoice = computed(() => {
    return characterVoices.value.find(v => v.emotion === selectedEmotion.value) || null
})

const boundAssets = computed(() => {
    const voice = selectedVoice.value
    const assetIds = new Set(voice?.ref_asset_ids || [])
    return voiceStore.assets.filter(asset => assetIds.has(asset.asset_id))
})

const availableAssets = computed(() => {
    const voice = selectedVoice.value
    const assetIds = new Set(voice?.ref_asset_ids || [])
    return voiceStore.assets.filter(asset =>
        asset.character === props.characterName &&
        normalizeEmotionTag(asset.emotion || 'default') === normalizeEmotionTag(selectedEmotion.value || 'default') &&
        !assetIds.has(asset.asset_id),
    )
})

const normalizedExistingEmotions = computed(() => {
    return new Set(characterVoices.value.map(voice => normalizeEmotionTag(voice.emotion)))
})

const projectEmotionCatalog = computed(() => {
    const runtimeEmotions = [
        ...voiceStore.voices.map(voice => voice.emotion),
        ...voiceStore.assets.map(asset => asset.emotion || 'default'),
    ]
    return buildEmotionCatalog(runtimeEmotions)
})

const suggestedEmotionOptions = computed(() => {
    return projectEmotionCatalog.value.map(emotion => ({
        value: emotion,
        exists: normalizedExistingEmotions.value.has(emotion),
    }))
})

const selectedVoiceModeLabel = computed(() => {
    const modeMap: Record<string, string> = {
        zero_shot: '零样本复制',
        instruct: '指令模式',
        cross_lingual: '跨语言',
    }
    return selectedVoice.value ? (modeMap[selectedVoice.value.mode] || selectedVoice.value.mode) : ''
})

const addGuideText = computed(() => {
    if (!selectedVoice.value) {
        return '新增情绪后，建议先上传一条参考音频，系统会自动绑定到当前情绪。'
    }
    if (boundAssets.value.length === 0) {
        return '当前情绪还没有参考音频，建议先上传一条示例音频，或绑定已有资产。'
    }
    return '当前情绪已经具备参考音频，可以继续补充更多资产，提升随机选取效果。'
})

const canDeleteSelectedEmotion = computed(() => {
    return normalizeEmotionTag(selectedEmotion.value) !== 'default'
})

function clearTransientFeedback() {
    uploadError.value = ''
    addError.value = ''
}

function applySuggestedEmotion(emotion: string) {
    if (normalizedExistingEmotions.value.has(emotion)) return
    newEmotionName.value = emotion
    addError.value = ''
}

async function addEmotion() {
    const emotion = normalizeEmotionTag(newEmotionName.value)
    if (!emotion) {
        addError.value = '请输入情感标签'
        return
    }

    const exists = characterVoices.value.some(v => normalizeEmotionTag(v.emotion) === emotion)
    if (exists) {
        addError.value = `情感「${emotion}」已存在`
        return
    }

    isCreatingEmotion.value = true
    clearTransientFeedback()

    try {
        const voiceId = `${props.characterName}#${emotion}`
        await voiceStore.createVoice({
            name: voiceId,
            character: props.characterName,
            emotion,
            mode: 'zero_shot',
            prompt_text: '',
            selection_policy: 'random_per_text',
            ref_asset_ids: [],
            color: '#6366F1',
        })

        newEmotionName.value = ''
        addInfo.value = `已新增情绪「${emotion}」，下一步可以上传参考音频或绑定已有资产。`
        showAddForm.value = false
        selectedEmotion.value = emotion
        await nextTick()
        uploadCardRef.value?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    } catch (e: unknown) {
        addError.value = (e as Error).message
        addInfo.value = ''
    } finally {
        isCreatingEmotion.value = false
    }
}

async function deleteEmotion(voiceName: string) {
    if (!canDeleteSelectedEmotion.value) return
    if (!confirm('确定删除此情绪吗？删除后，该情绪下的绑定关系将一并移除。')) return

    pendingDeleteVoiceName.value = voiceName
    clearTransientFeedback()
    try {
        await voiceStore.deleteVoice(voiceName)
        addInfo.value = '已删除该情绪。'
        if (characterVoices.value.length > 0) {
            const defaultVoice = characterVoices.value.find(v => normalizeEmotionTag(v.emotion) === 'default')
            selectedEmotion.value = defaultVoice?.emotion || characterVoices.value[0]!.emotion
        } else {
            selectedEmotion.value = ''
        }
    } catch {
        // 错误由 store 统一持有
    } finally {
        pendingDeleteVoiceName.value = ''
    }
}

function triggerFilePicker() {
    if (!selectedVoice.value || isUploading.value) return
    fileInput.value?.click()
}

async function handleFileSelected(event: Event) {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    const voice = selectedVoice.value
    if (!file || !voice) return

    isUploading.value = true
    clearTransientFeedback()
    try {
        await voiceStore.uploadAssetForVoice(
            voice.name,
            file,
            `${props.characterName} ${voice.emotion} 参考音频`,
        )
        addInfo.value = '参考音频上传成功，已自动绑定到当前情绪。'
    } catch (e: unknown) {
        uploadError.value = (e as Error).message
        addInfo.value = ''
    } finally {
        isUploading.value = false
        input.value = ''
    }
}

async function bindAsset(assetId: string) {
    const voice = selectedVoice.value
    if (!voice) return
    clearTransientFeedback()
    pendingBindAssetId.value = assetId
    try {
        await voiceStore.bindAssetToVoice(voice.name, assetId)
        addInfo.value = '已绑定参考资产。'
    } catch (e: unknown) {
        uploadError.value = (e as Error).message
    } finally {
        pendingBindAssetId.value = ''
    }
}

async function unbindAsset(assetId: string) {
    const voice = selectedVoice.value
    if (!voice) return
    clearTransientFeedback()
    pendingUnbindAssetId.value = assetId
    try {
        await voiceStore.unbindAssetFromVoice(voice.name, assetId)
        addInfo.value = '已解绑参考资产。'
    } catch (e: unknown) {
        uploadError.value = (e as Error).message
    } finally {
        pendingUnbindAssetId.value = ''
    }
}

async function removeAsset(assetId: string) {
    const voice = selectedVoice.value
    if (!voice) return
    if (!confirm('确定删除这条参考音频资产吗？删除后无法恢复。')) return

    clearTransientFeedback()
    pendingDeleteAssetId.value = assetId
    try {
        await voiceStore.deleteAssetFromVoice(voice.name, assetId)
        addInfo.value = '参考音频已删除。'
    } catch (e: unknown) {
        uploadError.value = (e as Error).message
    } finally {
        pendingDeleteAssetId.value = ''
    }
}
</script>

<template>
    <div class="emotion-editor">
        <div class="ee-header">
            <div class="ee-header-copy">
                <p class="ee-eyebrow">角色单独设置</p>
                <h3 class="ee-title">{{ characterName }} 的情感管理</h3>
                <p class="ee-subtitle">统一管理该角色的常用情绪、参考音频和快速绑定入口。</p>
            </div>
            <button class="close-btn" aria-label="关闭情感管理" @click="emit('close')">
                <XMarkIcon class="w-5 h-5" />
            </button>
        </div>

        <div class="ee-tabs-wrap">
            <div class="ee-tabs-head">
                <div class="ee-tabs-label">
                    <SparklesIcon class="w-4 h-4" />
                    <span>情绪标签</span>
                </div>
                <button class="ee-add-toggle" @click="showAddForm = !showAddForm">
                    <PlusIcon class="w-4 h-4" />
                    <span>{{ showAddForm ? '收起新增' : '新增情绪' }}</span>
                </button>
            </div>

            <div class="ee-tabs">
                <button
                    v-for="voice in characterVoices"
                    :key="voice.name"
                    class="emotion-tab"
                    :class="{ active: selectedEmotion === voice.emotion }"
                    @click="selectedEmotion = voice.emotion"
                >
                    <span class="tab-label">{{ voice.emotion || 'default' }}</span>
                    <span class="tab-meta">{{ voice.ref_asset_ids?.length || 0 }} 条参考</span>
                </button>
            </div>
        </div>

        <div v-if="showAddForm" class="add-panel">
            <div class="add-panel-header">
                <div>
                    <h4 class="panel-title">新增情绪标签</h4>
                    <p class="panel-desc">可以直接选择常见情绪，也可以手动输入自定义标签。</p>
                </div>
                <span class="panel-badge">预设 + 自定义</span>
            </div>

            <div class="preset-list" role="list" aria-label="常见情绪标签">
                <button
                    v-for="item in suggestedEmotionOptions"
                    :key="item.value"
                    class="preset-chip"
                    :class="{ disabled: item.exists, active: newEmotionName.trim() === item.value }"
                    :disabled="item.exists"
                    @click="applySuggestedEmotion(item.value)"
                >
                    <span>{{ item.value }}</span>
                    <span class="preset-chip-meta">{{ item.exists ? '已存在' : '快捷填入' }}</span>
                </button>
            </div>

            <div class="add-form">
                <label class="sr-only" for="emotion-name-input">情感标签</label>
                <input
                    id="emotion-name-input"
                    v-model="newEmotionName"
                    type="text"
                    placeholder="输入情感标签，例如：开心、angry、紧张"
                    class="add-input"
                    @keyup.enter="addEmotion"
                />
                <button class="add-confirm-btn" :disabled="isCreatingEmotion" @click="addEmotion">
                    {{ isCreatingEmotion ? '添加中...' : '添加情绪' }}
                </button>
            </div>

            <p class="add-hint">{{ addGuideText }}</p>
            <span v-if="addError" class="feedback feedback-error">
                <ExclamationTriangleIcon class="w-4 h-4" />
                <span>{{ addError }}</span>
            </span>
        </div>

        <div class="ee-body">
            <template v-if="characterVoices.length === 0">
                <div class="ee-empty">
                    <SparklesIcon class="w-10 h-10" />
                    <p class="empty-title">此角色还没有情绪配置</p>
                    <p class="empty-desc">先新增一个情绪标签，再上传参考音频，后续才能在任务页中稳定复用。</p>
                </div>
            </template>

            <template v-else>
                <div
                    v-for="voice in characterVoices"
                    :key="voice.name"
                    v-show="voice.emotion === selectedEmotion"
                    class="emotion-detail"
                >
                    <div class="emotion-summary">
                        <div class="summary-copy">
                            <p class="summary-eyebrow">当前情绪</p>
                            <h4 class="summary-title">{{ voice.emotion || 'default' }}</h4>
                            <p class="summary-desc">{{ addGuideText }}</p>
                        </div>
                        <div class="summary-stats">
                            <div class="summary-stat">
                                <span class="summary-label">音色 ID</span>
                                <code class="summary-value">{{ voice.name }}</code>
                            </div>
                            <div class="summary-stat">
                                <span class="summary-label">合成模式</span>
                                <span class="summary-value">{{ selectedVoiceModeLabel }}</span>
                            </div>
                            <div class="summary-stat">
                                <span class="summary-label">已绑定资产</span>
                                <span class="summary-value">{{ voice.ref_asset_ids?.length || 0 }} 条</span>
                            </div>
                        </div>
                    </div>

                    <div v-if="addInfo" class="feedback feedback-success">
                        <CheckCircleIcon class="w-4 h-4" />
                        <span>{{ addInfo }}</span>
                    </div>
                    <div v-if="uploadError || voiceStore.error" class="feedback feedback-error">
                        <ExclamationTriangleIcon class="w-4 h-4" />
                        <span>{{ uploadError || voiceStore.error }}</span>
                    </div>

                    <input
                        ref="fileInput"
                        type="file"
                        accept=".wav,.mp3,audio/wav,audio/mpeg"
                        class="hidden-file-input"
                        @change="handleFileSelected"
                    />

                    <div class="detail-grid">
                        <section ref="uploadCardRef" class="detail-card detail-card-primary">
                            <div class="detail-card-head">
                                <div>
                                    <h5 class="detail-card-title">上传参考音频</h5>
                                    <p class="detail-card-desc">上传后会自动绑定到当前情绪，支持 wav / mp3。</p>
                                </div>
                                <ArrowUpTrayIcon class="w-5 h-5" />
                            </div>
                            <button
                                class="upload-placeholder"
                                :disabled="isUploading"
                                @click="triggerFilePicker"
                            >
                                <MusicalNoteIcon class="w-8 h-8" />
                                <span class="upload-title">{{ isUploading ? '参考音频上传中...' : '点击上传参考音频' }}</span>
                                <span class="upload-hint">适合刚新增情绪时快速补齐第一条样本。</span>
                            </button>
                        </section>

                        <section class="detail-card">
                            <div class="detail-card-head">
                                <div>
                                    <h5 class="detail-card-title">候选资产概览</h5>
                                    <p class="detail-card-desc">已绑定资产和同情绪可绑定资产都会显示在这里。</p>
                                </div>
                                <LinkIcon class="w-5 h-5" />
                            </div>
                            <div class="summary-mini">
                                <div class="summary-mini-item">
                                    <span class="summary-mini-label">已绑定</span>
                                    <strong>{{ boundAssets.length }}</strong>
                                </div>
                                <div class="summary-mini-item">
                                    <span class="summary-mini-label">可绑定</span>
                                    <strong>{{ availableAssets.length }}</strong>
                                </div>
                            </div>
                        </section>
                    </div>

                    <div class="asset-section">
                        <div class="section-head">
                            <div>
                                <span class="section-title">已绑定参考音频</span>
                                <p class="section-desc">这些音频会作为当前情绪的直接参考样本参与合成。</p>
                            </div>
                            <span class="section-count">{{ boundAssets.length }}</span>
                        </div>

                        <div v-if="boundAssets.length === 0" class="asset-empty">
                            <p class="asset-empty-title">还没有已绑定参考音频</p>
                            <p class="asset-empty-desc">建议先上传一条音频，或者从下方候选资产里直接绑定。</p>
                        </div>
                        <div v-else class="asset-list">
                            <div v-for="asset in boundAssets" :key="asset.asset_id" class="asset-card">
                                <div class="asset-meta">
                                    <code class="asset-id">{{ asset.asset_id }}</code>
                                    <span class="asset-note">{{ asset.note || '未填写备注' }}</span>
                                    <span v-if="asset.transcript_text" class="asset-extra">{{ asset.transcript_text }}</span>
                                </div>
                                <div class="asset-actions">
                                    <button
                                        class="asset-btn asset-btn-ghost"
                                        :disabled="pendingUnbindAssetId === asset.asset_id"
                                        @click="unbindAsset(asset.asset_id)"
                                    >
                                        {{ pendingUnbindAssetId === asset.asset_id ? '解绑中...' : '解绑' }}
                                    </button>
                                    <button
                                        class="asset-btn asset-btn-danger"
                                        :disabled="pendingDeleteAssetId === asset.asset_id"
                                        @click="removeAsset(asset.asset_id)"
                                    >
                                        {{ pendingDeleteAssetId === asset.asset_id ? '删除中...' : '删除' }}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="asset-section">
                        <div class="section-head">
                            <div>
                                <span class="section-title">可绑定同情绪资产</span>
                                <p class="section-desc">只显示当前角色下、情绪一致且尚未绑定的参考资产。</p>
                            </div>
                            <span class="section-count">{{ availableAssets.length }}</span>
                        </div>

                        <div v-if="availableAssets.length === 0" class="asset-empty">
                            <p class="asset-empty-title">当前没有可直接绑定的候选资产</p>
                            <p class="asset-empty-desc">可以先上传一条参考音频，或到资产页把现有资产的情绪修正为 {{ voice.emotion || 'default' }} 后再回来绑定。</p>
                        </div>
                        <div v-else class="asset-list">
                            <div v-for="asset in availableAssets" :key="asset.asset_id" class="asset-card">
                                <div class="asset-meta">
                                    <code class="asset-id">{{ asset.asset_id }}</code>
                                    <span class="asset-note">{{ asset.note || '未填写备注' }}</span>
                                    <span v-if="asset.transcript_text" class="asset-extra">{{ asset.transcript_text }}</span>
                                </div>
                                <div class="asset-actions">
                                    <button
                                        class="asset-btn asset-btn-primary"
                                        :disabled="pendingBindAssetId === asset.asset_id"
                                        @click="bindAsset(asset.asset_id)"
                                    >
                                        {{ pendingBindAssetId === asset.asset_id ? '绑定中...' : '绑定' }}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="detail-footer">
                        <button
                            v-if="canDeleteSelectedEmotion"
                            class="del-emotion-btn"
                            :disabled="pendingDeleteVoiceName === voice.name"
                            @click="deleteEmotion(voice.name)"
                        >
                            <TrashIcon class="w-4 h-4" />
                            <span>{{ pendingDeleteVoiceName === voice.name ? '删除中...' : '删除此情绪' }}</span>
                        </button>
                        <span v-else class="default-lock-note">默认情绪作为基础音色保留，不支持删除。</span>
                    </div>
                </div>
            </template>
        </div>
    </div>
</template>

<style scoped>
.emotion-editor {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(247, 250, 252, 0.98) 100%);
    color: var(--color-text);
}

.ee-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 24px 24px 18px;
    border-bottom: 1px solid var(--color-divider);
}

.ee-header-copy {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.ee-eyebrow {
    margin: 0;
    color: var(--color-text-tertiary);
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.03em;
}

.ee-title {
    margin: 0;
    color: var(--color-text);
    font-size: 1.3rem;
    font-weight: 700;
}

.ee-subtitle {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: 0.92rem;
    line-height: 1.6;
}

.close-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    margin-top: 2px;
    border: 1px solid var(--color-border);
    border-radius: 999px;
    background: var(--color-surface);
    color: var(--color-text-secondary);
    transition: all 0.2s ease;
}

.close-btn:hover {
    background: var(--color-surface-soft);
    color: var(--color-text);
    border-color: var(--color-border-strong);
}

.ee-tabs-wrap {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px 24px;
    border-bottom: 1px solid var(--color-divider);
    background: rgba(248, 250, 252, 0.92);
}

.ee-tabs-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.ee-tabs-label {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--color-text-secondary);
    font-size: 0.88rem;
    font-weight: 700;
}

.ee-add-toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 40px;
    padding: 0 14px;
    border: 1px solid rgba(10, 132, 255, 0.18);
    border-radius: 999px;
    background: rgba(10, 132, 255, 0.08);
    color: var(--color-primary);
    font-size: 0.85rem;
    font-weight: 700;
    transition: all 0.2s ease;
}

.ee-add-toggle:hover {
    background: rgba(10, 132, 255, 0.12);
}

.ee-tabs {
    display: flex;
    gap: 10px;
    overflow-x: auto;
    padding-bottom: 2px;
}

.emotion-tab {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    min-width: 132px;
    padding: 12px 14px;
    border-radius: 16px;
    border: 1px solid var(--color-border);
    background: var(--color-surface);
    color: var(--color-text-secondary);
    font-size: 0.84rem;
    transition: all 0.2s ease;
    white-space: nowrap;
}

.emotion-tab:hover {
    border-color: rgba(10, 132, 255, 0.32);
    background: #f8fbff;
    transform: translateY(-1px);
}

.emotion-tab.active {
    background: linear-gradient(180deg, rgba(10, 132, 255, 0.1) 0%, rgba(255, 255, 255, 1) 100%);
    border-color: rgba(10, 132, 255, 0.38);
    box-shadow: 0 10px 24px rgba(10, 132, 255, 0.12);
}

.tab-label {
    color: var(--color-text);
    font-size: 0.9rem;
    font-weight: 700;
}

.tab-meta {
    color: var(--color-text-tertiary);
    font-size: 0.76rem;
}

.add-panel {
    display: flex;
    flex-direction: column;
    gap: 14px;
    margin: 18px 24px 0;
    padding: 18px;
    border: 1px solid var(--color-border);
    border-radius: 20px;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(246, 249, 253, 0.98) 100%);
    box-shadow: 0 16px 36px rgba(15, 23, 42, 0.06);
}

.add-panel-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
}

.panel-title {
    margin: 0;
    color: var(--color-text);
    font-size: 1rem;
}

.panel-desc {
    margin: 6px 0 0;
    color: var(--color-text-secondary);
    font-size: 0.86rem;
    line-height: 1.6;
}

.panel-badge {
    display: inline-flex;
    align-items: center;
    min-height: 30px;
    padding: 0 10px;
    border-radius: 999px;
    background: var(--color-surface-soft);
    color: var(--color-text-secondary);
    font-size: 0.76rem;
    font-weight: 700;
    border: 1px solid var(--color-border);
}

.preset-list {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

.preset-chip {
    display: inline-flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 3px;
    min-width: 112px;
    padding: 10px 12px;
    border-radius: 14px;
    border: 1px solid var(--color-border);
    background: var(--color-surface);
    color: var(--color-text);
    transition: all 0.2s ease;
}

.preset-chip:hover:not(:disabled) {
    border-color: rgba(10, 132, 255, 0.38);
    background: #f7fbff;
}

.preset-chip.active {
    border-color: rgba(249, 115, 22, 0.45);
    background: rgba(249, 115, 22, 0.08);
}

.preset-chip.disabled {
    background: var(--color-surface-soft);
    color: var(--color-text-quaternary);
}

.preset-chip-meta {
    color: var(--color-text-tertiary);
    font-size: 0.72rem;
}

.add-form {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.add-input {
    flex: 1;
    min-height: 48px;
    min-width: 240px;
    padding: 0 16px;
    border-radius: 14px;
    border: 1px solid var(--color-border);
    background: var(--color-input-bg);
    color: var(--color-text);
    font-size: 0.9rem;
    outline: none;
}

.add-input:focus {
    border-color: rgba(10, 132, 255, 0.5);
}

.add-input::placeholder {
    color: var(--color-text-tertiary);
}

.add-confirm-btn {
    min-height: 48px;
    padding: 0 18px;
    border-radius: 14px;
    background: var(--color-primary);
    color: white;
    font-size: 0.88rem;
    font-weight: 700;
    border: none;
    transition: all 0.2s ease;
}

.add-confirm-btn:hover:not(:disabled) {
    background: var(--color-primary-strong);
    transform: translateY(-1px);
}

.add-confirm-btn:disabled {
    opacity: 0.7;
    cursor: not-allowed;
}

.add-hint {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: 0.84rem;
    line-height: 1.6;
}

.ee-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 24px;
    overflow-y: auto;
}

.ee-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    min-height: 340px;
    border: 1px dashed var(--color-border-strong);
    border-radius: 20px;
    background: var(--color-surface-soft);
    color: var(--color-text-secondary);
    text-align: center;
    padding: 32px;
}

.empty-title {
    margin: 0;
    color: var(--color-text);
    font-size: 1rem;
    font-weight: 700;
}

.empty-desc {
    margin: 0;
    max-width: 36ch;
    color: var(--color-text-secondary);
    font-size: 0.9rem;
    line-height: 1.6;
}

.emotion-detail {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.emotion-summary {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
    padding: 20px;
    border: 1px solid var(--color-border);
    border-radius: 20px;
    background: linear-gradient(180deg, rgba(255, 255, 255, 1) 0%, rgba(247, 250, 252, 1) 100%);
    box-shadow: 0 12px 30px rgba(15, 23, 42, 0.05);
}

.summary-copy {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.summary-eyebrow {
    margin: 0;
    color: var(--color-text-tertiary);
    font-size: 0.78rem;
    font-weight: 700;
}

.summary-title {
    margin: 0;
    color: var(--color-text);
    font-size: 1.2rem;
}

.summary-desc {
    margin: 0;
    max-width: 36ch;
    color: var(--color-text-secondary);
    font-size: 0.88rem;
    line-height: 1.6;
}

.summary-stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
    min-width: min(100%, 360px);
}

.summary-stat {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 14px;
    border: 1px solid var(--color-border);
    border-radius: 16px;
    background: var(--color-surface);
}

.summary-label {
    color: var(--color-text-tertiary);
    font-size: 0.75rem;
    font-weight: 700;
}

.summary-value {
    color: var(--color-text);
    font-size: 0.9rem;
    font-weight: 600;
    word-break: break-all;
}

.feedback {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 12px 14px;
    border-radius: 14px;
    font-size: 0.84rem;
    font-weight: 500;
}

.feedback-success {
    background: var(--color-success-soft);
    color: var(--color-success);
    border: 1px solid rgba(21, 128, 61, 0.16);
}

.feedback-error {
    background: var(--color-danger-soft);
    color: var(--color-danger);
    border: 1px solid rgba(220, 38, 38, 0.16);
}

.hidden-file-input {
    display: none;
}

.detail-grid {
    display: grid;
    grid-template-columns: 1.3fr 0.9fr;
    gap: 16px;
}

.detail-card {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px;
    border: 1px solid var(--color-border);
    border-radius: 20px;
    background: var(--color-surface);
}

.detail-card-primary {
    background: linear-gradient(180deg, rgba(10, 132, 255, 0.04) 0%, rgba(255, 255, 255, 1) 100%);
}

.detail-card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    color: var(--color-text-secondary);
}

.detail-card-title {
    margin: 0;
    color: var(--color-text);
    font-size: 0.96rem;
}

.detail-card-desc {
    margin: 6px 0 0;
    color: var(--color-text-secondary);
    font-size: 0.82rem;
    line-height: 1.6;
}

.upload-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    min-height: 172px;
    padding: 24px 18px;
    border: 1.5px dashed rgba(10, 132, 255, 0.28);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.92);
    color: var(--color-primary);
    text-align: center;
    transition: all 0.2s ease;
}

.upload-placeholder:hover:not(:disabled) {
    border-color: rgba(10, 132, 255, 0.48);
    background: #f6fbff;
    transform: translateY(-1px);
}

.upload-placeholder:disabled {
    opacity: 0.7;
    cursor: progress;
}

.upload-title {
    color: var(--color-text);
    font-size: 0.96rem;
    font-weight: 700;
}

.upload-hint {
    color: var(--color-text-secondary);
    font-size: 0.8rem;
    line-height: 1.6;
}

.summary-mini {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
}

.summary-mini-item {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px;
    border-radius: 16px;
    background: var(--color-surface-soft);
    border: 1px solid var(--color-border);
    color: var(--color-text);
}

.summary-mini-label {
    color: var(--color-text-tertiary);
    font-size: 0.76rem;
    font-weight: 700;
}

.asset-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 18px;
    border: 1px solid var(--color-border);
    border-radius: 20px;
    background: var(--color-surface);
}

.section-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
}

.section-title {
    display: inline-block;
    color: var(--color-text);
    font-size: 0.95rem;
    font-weight: 700;
}

.section-desc {
    margin: 6px 0 0;
    color: var(--color-text-secondary);
    font-size: 0.82rem;
    line-height: 1.6;
}

.section-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 32px;
    height: 32px;
    padding: 0 10px;
    border-radius: 999px;
    background: var(--color-surface-soft);
    color: var(--color-text-secondary);
    font-size: 0.76rem;
    font-weight: 700;
    border: 1px solid var(--color-border);
}

.asset-empty {
    padding: 16px;
    border-radius: 16px;
    background: var(--color-surface-soft);
    border: 1px dashed var(--color-border-strong);
}

.asset-empty-title {
    margin: 0;
    color: var(--color-text);
    font-size: 0.88rem;
    font-weight: 700;
}

.asset-empty-desc {
    margin: 6px 0 0;
    color: var(--color-text-secondary);
    font-size: 0.82rem;
    line-height: 1.6;
}

.asset-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.asset-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 16px;
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(255, 255, 255, 1) 0%, rgba(248, 250, 252, 1) 100%);
    border: 1px solid var(--color-border);
}

.asset-meta {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
}

.asset-id {
    color: var(--color-text);
    font-size: 0.78rem;
    font-weight: 700;
}

.asset-note {
    color: var(--color-text-secondary);
    font-size: 0.8rem;
    word-break: break-all;
}

.asset-extra {
    color: var(--color-text-tertiary);
    font-size: 0.76rem;
    line-height: 1.5;
    word-break: break-word;
}

.asset-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
}

.asset-btn {
    min-height: 38px;
    padding: 0 12px;
    border-radius: 999px;
    border: 1px solid transparent;
    font-size: 0.8rem;
    font-weight: 700;
    transition: all 0.2s ease;
}

.asset-btn-primary {
    background: rgba(10, 132, 255, 0.12);
    color: var(--color-primary);
    border-color: rgba(10, 132, 255, 0.22);
}

.asset-btn-ghost {
    background: var(--color-surface-soft);
    color: var(--color-text-secondary);
    border-color: var(--color-border);
}

.asset-btn-danger {
    background: rgba(220, 38, 38, 0.08);
    color: var(--color-danger);
    border-color: rgba(220, 38, 38, 0.16);
}

.asset-btn:hover:not(:disabled) {
    transform: translateY(-1px);
}

.asset-btn:disabled {
    opacity: 0.72;
    cursor: progress;
}

.detail-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.del-emotion-btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 42px;
    padding: 0 14px;
    border-radius: 999px;
    background: rgba(220, 38, 38, 0.08);
    color: var(--color-danger);
    border: 1px solid rgba(220, 38, 38, 0.16);
    font-size: 0.84rem;
    font-weight: 700;
    transition: all 0.2s ease;
}

.del-emotion-btn:hover:not(:disabled) {
    background: rgba(220, 38, 38, 0.12);
}

.del-emotion-btn:disabled {
    opacity: 0.72;
    cursor: progress;
}

.default-lock-note {
    color: var(--color-text-tertiary);
    font-size: 0.82rem;
}

.sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    border: 0;
}

@media (max-width: 860px) {
    .ee-header,
    .ee-tabs-wrap,
    .ee-body {
        padding-left: 18px;
        padding-right: 18px;
    }

    .emotion-summary,
    .add-panel-header,
    .ee-tabs-head {
        flex-direction: column;
    }

    .detail-grid,
    .summary-stats {
        grid-template-columns: 1fr;
    }

    .asset-card,
    .detail-footer {
        flex-direction: column;
        align-items: stretch;
    }

    .asset-actions {
        width: 100%;
        justify-content: flex-end;
        flex-wrap: wrap;
    }
}

@media (max-width: 640px) {
    .emotion-tab,
    .preset-chip {
        min-width: 100px;
    }

    .add-form {
        flex-direction: column;
        align-items: stretch;
    }

    .add-confirm-btn {
        width: 100%;
    }
}
</style>
