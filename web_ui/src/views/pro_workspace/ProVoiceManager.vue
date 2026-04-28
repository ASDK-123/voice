<script setup lang="ts">
// Pro 音色管理面板
// 搜索 + 按角色分组列表 + 选择

import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useProVoiceStore, type ProVoiceItem } from '@/stores/pro_voice'
import ProVoiceWizardModal from './ProVoiceWizardModal.vue'
import ProEmotionEditor from './ProEmotionEditor.vue'
import ProAssetsPanel from './ProAssetsPanel.vue'
import type { LegacyImportExecuteResult, LegacyImportPreviewResult } from '@/types'
import { 
    UsersIcon, 
    MagnifyingGlassIcon, 
    MicrophoneIcon, 
    PlusIcon, 
    ChevronRightIcon,
    TrashIcon,
    Cog6ToothIcon,
    PencilSquareIcon,
    ArchiveBoxArrowDownIcon,
    SparklesIcon,
    ArrowUpTrayIcon,
    PencilIcon
} from '@heroicons/vue/24/outline'

const voiceStore = useProVoiceStore()
const listRef = ref<HTMLElement | null>(null)

// 新建音色弹窗
const showWizard = ref(false)
const editingVoice = ref<ProVoiceItem | null>(null)
const showAssetsPanel = ref(false)
const actionMessage = ref('')
const showLegacyImport = ref(false)
const legacyFile = ref<File | null>(null)
const legacyImportPreview = ref<LegacyImportPreviewResult | LegacyImportExecuteResult | null>(null)
const legacyImportError = ref('')
const legacyImportBusy = ref(false)

// 情感编辑弹窗
const editingEmotionCharacter = ref<string | null>(null)
const showBulkRename = ref(false)
const bulkRenameCharacter = ref('')
const bulkRenameNextCharacter = ref('')
const bulkRenameEmotionDrafts = ref<Record<string, string>>({})
const bulkRenameError = ref('')
const bulkRenameSubmitting = ref(false)
const bulkRenameFailures = ref<Array<{ originalName: string; nextName: string; message: string }>>([])

// 展开/折叠的角色分组
const expandedGroups = ref<Set<string>>(new Set())
const knownGroups = new Set<string>()

function discoverGroups(chars: string[]) {
    if (chars.length === 0) return
    let changed = false
    const next = new Set(expandedGroups.value)
    chars.forEach(char => {
        if (!knownGroups.has(char)) {
            knownGroups.add(char)
            next.add(char)
            changed = true
        }
    })
    if (changed) {
        expandedGroups.value = next
    }
}

/** 切换分组展开 */
function toggleGroup(char: string) {
    if (expandedGroups.value.has(char)) {
        expandedGroups.value.delete(char)
    } else {
        expandedGroups.value.add(char)
    }
}

/** 检查分组是否展开 */
function isGroupExpanded(char: string): boolean {
    return expandedGroups.value.has(char)
}

onMounted(() => {
    discoverGroups(Array.from(voiceStore.characters.keys()))
})

function escapeSelector(value: string): string {
    return typeof CSS !== 'undefined' ? CSS.escape(value) : value
}

async function revealSelectedVoice() {
    const selected = voiceStore.selectedVoice
    if (!selected) return

    if (voiceStore.searchKeyword && !voiceStore.filteredVoices.some(voice => voice.name === selected.name)) {
        voiceStore.searchKeyword = ''
    }

    if (!expandedGroups.value.has(selected.character)) {
        expandedGroups.value = new Set([...expandedGroups.value, selected.character])
    }

    await nextTick()
    const selector = `[data-voice-id="${escapeSelector(selected.name)}"]`
    const card = listRef.value?.querySelector(selector) as HTMLElement | null
    card?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}

/** 确认并删除音色 */
async function confirmDelete(voiceName: string) {
    if (confirm(`确定删除音色「${voiceName}」吗？`)) {
        await voiceStore.deleteVoice(voiceName)
    }
}

function openCreateVoice() {
    editingVoice.value = null
    showWizard.value = true
}

function openEditVoice(voice: ProVoiceItem) {
    editingVoice.value = voice
    showWizard.value = true
}

function pushActionMessage(message: string) {
    actionMessage.value = message
    setTimeout(() => {
        if (actionMessage.value === message) {
            actionMessage.value = ''
        }
    }, 3200)
}

function handleWizardClose() {
    showWizard.value = false
    editingVoice.value = null
    void revealSelectedVoice()
}

async function handleCompile(voiceName: string) {
    actionMessage.value = ''
    try {
        const result = await voiceStore.compileVoice(voiceName)
        pushActionMessage(`已编译 ${result.compiled.length} 个 speaker`)
    } catch {
        actionMessage.value = ''
    }
}

const bulkRenameVoices = computed(() =>
    voiceStore.voices
        .filter(voice => voice.character === bulkRenameCharacter.value)
        .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN')),
)

const bulkRenamePreviewRows = computed(() => {
    const nextCharacter = bulkRenameNextCharacter.value.trim()
    return bulkRenameVoices.value.map(voice => {
        const nextEmotion = (bulkRenameEmotionDrafts.value[voice.name] || '').trim()
        return {
            originalName: voice.name,
            originalEmotion: voice.emotion || 'default',
            nextEmotion,
            nextName: nextCharacter && nextEmotion ? `${nextCharacter}#${nextEmotion}` : '',
        }
    })
})

const bulkRenameConflictMessage = computed(() => {
    if (!showBulkRename.value) return ''
    if (!bulkRenameNextCharacter.value.trim()) return '角色名不能为空'
    if (bulkRenamePreviewRows.value.some(item => !item.nextEmotion)) return '情绪名不能为空'

    const seen = new Set<string>()
    const originals = new Set(bulkRenamePreviewRows.value.map(item => item.originalName))
    for (const item of bulkRenamePreviewRows.value) {
        if (!item.nextName) return '预览名称不能为空'
        if (seen.has(item.nextName)) {
            return `预览名称重复：${item.nextName}`
        }
        seen.add(item.nextName)
        const conflict = voiceStore.voices.some(voice => voice.name === item.nextName && !originals.has(voice.name))
        if (conflict) {
            return `已存在同名音色：${item.nextName}`
        }
    }
    return ''
})

function openBulkRename(character: string) {
    bulkRenameCharacter.value = character
    bulkRenameNextCharacter.value = character
    bulkRenameEmotionDrafts.value = Object.fromEntries(
        voiceStore.voices
            .filter(voice => voice.character === character)
            .map(voice => [voice.name, voice.emotion || 'default']),
    )
    bulkRenameError.value = ''
    bulkRenameFailures.value = []
    showBulkRename.value = true
}

function closeBulkRename() {
    showBulkRename.value = false
    bulkRenameCharacter.value = ''
    bulkRenameNextCharacter.value = ''
    bulkRenameEmotionDrafts.value = {}
    bulkRenameError.value = ''
    bulkRenameFailures.value = []
}

async function handleBulkRenameSubmit() {
    if (bulkRenameConflictMessage.value) {
        bulkRenameError.value = bulkRenameConflictMessage.value
        return
    }
    bulkRenameSubmitting.value = true
    bulkRenameError.value = ''
    bulkRenameFailures.value = []
    try {
        const result = await voiceStore.bulkRenameCharacterVoices({
            character: bulkRenameCharacter.value,
            nextCharacter: bulkRenameNextCharacter.value.trim(),
            items: bulkRenamePreviewRows.value.map(item => ({
                originalName: item.originalName,
                nextEmotion: item.nextEmotion,
            })),
        })
        bulkRenameFailures.value = result.failures
        if (result.failures.length > 0) {
            bulkRenameError.value = `已成功 ${result.successes.length} 条，失败 ${result.failures.length} 条`
            return
        }
        closeBulkRename()
        pushActionMessage(`已更新 ${result.successes.length} 条音色命名`)
    } catch (e: unknown) {
        bulkRenameError.value = (e as Error).message
    } finally {
        bulkRenameSubmitting.value = false
    }
}

function onLegacyFileChange(event: Event) {
    const input = event.target as HTMLInputElement
    legacyFile.value = input.files?.[0] || null
    legacyImportPreview.value = null
    legacyImportError.value = ''
}

function closeLegacyImport() {
    showLegacyImport.value = false
    legacyFile.value = null
    legacyImportPreview.value = null
    legacyImportError.value = ''
}

async function handleLegacyPreview() {
    if (!legacyFile.value) {
        legacyImportError.value = '请选择 legacy JSON 文件'
        return
    }
    legacyImportBusy.value = true
    legacyImportError.value = ''
    try {
        legacyImportPreview.value = await voiceStore.previewLegacyImport(legacyFile.value)
    } catch (e: unknown) {
        legacyImportError.value = (e as Error).message
    } finally {
        legacyImportBusy.value = false
    }
}

async function handleLegacyExecute() {
    if (!legacyFile.value) {
        legacyImportError.value = '请选择 legacy JSON 文件'
        return
    }
    legacyImportBusy.value = true
    legacyImportError.value = ''
    try {
        const result = await voiceStore.executeLegacyImport(legacyFile.value)
        legacyImportPreview.value = result
        pushActionMessage(`legacy 导入完成：${result.imported_voices} 个音色，${result.imported_assets} 个资产`)
    } catch (e: unknown) {
        legacyImportError.value = (e as Error).message
    } finally {
        legacyImportBusy.value = false
    }
}

watch(
    () => Array.from(voiceStore.characters.keys()),
    chars => {
        discoverGroups(chars)
    },
    { immediate: true },
)

watch(
    () => voiceStore.selectedVoice,
    voice => {
        if (voice) {
            void revealSelectedVoice()
        }
    },
)
</script>

<template>
    <div class="voice-manager">
        <!-- 头部 -->
        <div class="vm-header">
            <h3 class="vm-title">
                <UsersIcon class="w-5 h-5 text-indigo-400" />
                <span>音色管理</span>
            </h3>
            <div class="vm-header-right">
                <span class="vm-count">{{ voiceStore.voices.length }} 个音色</span>
                <button class="header-text-btn" @click="showLegacyImport = true">
                    <ArrowUpTrayIcon class="w-4 h-4" />
                    <span>legacy 导入</span>
                </button>
                <button class="header-action-btn" aria-label="打开资产面板" @click="showAssetsPanel = true" title="打开资产面板">
                    <ArchiveBoxArrowDownIcon class="w-4 h-4" />
                </button>
            </div>
        </div>

        <div v-if="actionMessage" class="vm-message">
            {{ actionMessage }}
        </div>

        <!-- 搜索栏 -->
        <div class="vm-search">
            <div class="search-input-wrapper">
                <MagnifyingGlassIcon class="search-icon w-4 h-4" />
                <input
                    v-model="voiceStore.searchKeyword"
                    type="text"
                    placeholder="搜索角色或情绪..."
                    class="search-input"
                />
            </div>
        </div>

        <!-- 音色列表 -->
        <div ref="listRef" class="vm-list">
            <!-- 加载中 -->
            <div v-if="voiceStore.isLoading" class="vm-loading">
                <div class="spinner-ring"></div>
                <span>加载音色中...</span>
            </div>

            <!-- 错误提示 -->
            <div v-else-if="voiceStore.error" class="vm-error">
                <span>{{ voiceStore.error }}</span>
                <button class="retry-btn" @click="voiceStore.fetchVoices()">重试</button>
            </div>

            <!-- 空状态 -->
            <div v-else-if="voiceStore.filteredVoices.length === 0" class="vm-empty">
                <MicrophoneIcon class="w-12 h-12 text-indigo-900 mb-2 opacity-50" />
                <span>{{ voiceStore.searchKeyword ? '未找到匹配的音色' : '暂无音色' }}</span>
            </div>

            <!-- 按角色分组显示 -->
            <template v-else>
                <div
                    v-for="[character, voices] of voiceStore.characters"
                    :key="character"
                    class="voice-group"
                >
                    <!-- 分组头 -->
                    <div class="group-header">
                        <div class="group-header-left" @click="toggleGroup(character)">
                            <ChevronRightIcon 
                                class="group-arrow w-3 h-3" 
                                :class="{ expanded: isGroupExpanded(character) }" 
                            />
                            <span class="group-name">{{ character }}</span>
                            <span class="group-count">{{ voices.length }}</span>
                        </div>
                        
                        <div class="group-actions">
                            <button
                                class="group-action-btn"
                                aria-label="按角色批量改名"
                                @click="openBulkRename(character)"
                                title="按角色批量改名"
                            >
                                <PencilIcon class="w-3.5 h-3.5" />
                            </button>

                            <!-- 编辑该角色情感按钮 -->
                            <button 
                                class="edit-emotion-btn" 
                                aria-label="管理情感发音资产"
                                @click="editingEmotionCharacter = character"
                                title="管理情感发音资产"
                            >
                                <Cog6ToothIcon class="w-3.5 h-3.5" />
                            </button>
                        </div>
                    </div>

                    <!-- 音色卡片列表 -->
                    <div v-if="isGroupExpanded(character)" class="group-items">
                        <div
                            v-for="voice in voices"
                            :key="voice.name"
                            class="voice-card"
                            :class="{ 'voice-selected': voiceStore.selectedVoiceId === voice.name }"
                            :data-voice-id="voice.name"
                            @click="voiceStore.selectVoice(voice.name)"
                        >
                            <!-- 颜色标记 -->
                            <span
                                class="color-dot"
                                :style="{ backgroundColor: voice.color || '#6366F1' }"
                            ></span>

                            <!-- 信息 -->
                            <div class="voice-info">
                                <span class="voice-name">{{ voice.character }}</span>
                                <span class="voice-emotion">
                                    {{ voice.emotion || 'default' }}
                                </span>
                            </div>

                            <!-- 模式标签 -->
                            <span class="voice-mode">{{ voice.mode }}</span>

                            <div class="voice-actions">
                                <button
                                    class="voice-action-btn"
                                    @click.stop="openEditVoice(voice)"
                                    title="编辑此音色"
                                >
                                    <PencilSquareIcon class="w-3.5 h-3.5" />
                                </button>
                                <button
                                    class="voice-action-btn"
                                    @click.stop="handleCompile(voice.name)"
                                    title="编译此音色"
                                >
                                    <SparklesIcon class="w-3.5 h-3.5" />
                                </button>
                                <button
                                    class="voice-del-btn"
                                    @click.stop="confirmDelete(voice.name)"
                                    title="删除此音色"
                                >
                                    <TrashIcon class="w-3.5 h-3.5" />
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </template>
        </div>

        <!-- 底部操作 -->
        <div class="vm-footer">
            <button class="add-voice-btn" @click="openCreateVoice">
                <PlusIcon class="w-4 h-4 stroke-2" />
                <span>新建音色</span>
            </button>
        </div>
    </div>

    <!-- 新建音色弹窗 -->
    <ProVoiceWizardModal
        v-if="showWizard"
        :initial-voice="editingVoice"
        @close="handleWizardClose"
    />

    <!-- 情感资产配置弹窗 (全屏遮罩) -->
    <div v-if="editingEmotionCharacter" class="emotion-editor-overlay" @click.self="editingEmotionCharacter = null">
        <div class="emotion-editor-modal">
            <ProEmotionEditor 
                :character-name="editingEmotionCharacter" 
                @close="editingEmotionCharacter = null" 
            />
        </div>
    </div>

    <div v-if="showBulkRename" class="utility-overlay" @click.self="closeBulkRename">
        <div class="utility-modal">
            <div class="utility-header">
                <div>
                    <h3 class="utility-title">按角色批量改名</h3>
                    <p class="utility-desc">当前分组：{{ bulkRenameCharacter }}。统一修改角色名，并逐条调整情绪标签。</p>
                </div>
                <button class="close-btn-inline" @click="closeBulkRename">关闭</button>
            </div>

            <label class="utility-field">
                <span>角色名</span>
                <input v-model="bulkRenameNextCharacter" type="text" class="search-input" placeholder="新的角色名" />
            </label>

            <div class="rename-table">
                <div class="rename-row rename-head">
                    <span>旧名称</span>
                    <span>新情绪</span>
                    <span>预览名称</span>
                </div>
                <div v-for="row in bulkRenamePreviewRows" :key="row.originalName" class="rename-row">
                    <span>{{ row.originalName }}</span>
                    <input
                        v-model="bulkRenameEmotionDrafts[row.originalName]"
                        type="text"
                        class="rename-input"
                        placeholder="新情绪"
                    />
                    <code>{{ row.nextName || '待填写' }}</code>
                </div>
            </div>

            <p v-if="bulkRenameConflictMessage" class="utility-error">{{ bulkRenameConflictMessage }}</p>
            <p v-else-if="bulkRenameError" class="utility-error">{{ bulkRenameError }}</p>
            <div v-if="bulkRenameFailures.length" class="failure-box">
                <p class="failure-title">失败项</p>
                <p v-for="item in bulkRenameFailures" :key="item.originalName" class="failure-item">
                    {{ item.originalName }} → {{ item.nextName }}：{{ item.message }}
                </p>
            </div>

            <div class="utility-actions">
                <button class="header-text-btn" @click="closeBulkRename">取消</button>
                <button
                    class="utility-primary-btn"
                    :disabled="bulkRenameSubmitting || !!bulkRenameConflictMessage"
                    @click="handleBulkRenameSubmit"
                >
                    {{ bulkRenameSubmitting ? '提交中...' : '提交批量改名' }}
                </button>
            </div>
        </div>
    </div>

    <div v-if="showLegacyImport" class="utility-overlay" @click.self="closeLegacyImport">
        <div class="utility-modal">
            <div class="utility-header">
                <div>
                    <h3 class="utility-title">legacy 配置导入</h3>
                    <p class="utility-desc">上传旧版 JSON 配置，先执行预检，再确认导入到 v2 音色与资产域。</p>
                </div>
                <button class="close-btn-inline" @click="closeLegacyImport">关闭</button>
            </div>

            <div class="utility-field">
                <span>配置文件</span>
                <input type="file" accept=".json,application/json" @change="onLegacyFileChange" />
            </div>

            <p v-if="legacyImportError" class="utility-error">{{ legacyImportError }}</p>

            <div v-if="legacyImportPreview" class="preview-box">
                <p class="preview-title">{{ legacyImportPreview.dry_run ? '预检摘要' : '导入结果' }}</p>
                <div class="preview-grid">
                    <div class="preview-item">
                        <span>音色</span>
                        <strong>{{ legacyImportPreview.imported_voices }}</strong>
                    </div>
                    <div class="preview-item">
                        <span>资产</span>
                        <strong>{{ legacyImportPreview.imported_assets }}</strong>
                    </div>
                    <div class="preview-item">
                        <span>跳过资产</span>
                        <strong>{{ legacyImportPreview.skipped_assets }}</strong>
                    </div>
                </div>
                <div v-if="legacyImportPreview.errors.length" class="failure-box">
                    <p class="failure-title">错误与跳过明细</p>
                    <p v-for="item in legacyImportPreview.errors" :key="item" class="failure-item">{{ item }}</p>
                </div>
            </div>

            <div class="utility-actions">
                <button class="header-text-btn" :disabled="legacyImportBusy" @click="handleLegacyPreview">
                    {{ legacyImportBusy ? '预检中...' : '先预检' }}
                </button>
                <button
                    class="utility-primary-btn"
                    :disabled="legacyImportBusy || !legacyFile || !legacyImportPreview"
                    @click="handleLegacyExecute"
                >
                    {{ legacyImportBusy ? '导入中...' : '确认导入' }}
                </button>
            </div>
        </div>
    </div>

    <ProAssetsPanel v-if="showAssetsPanel" @close="showAssetsPanel = false" />
</template>

<style scoped>
.voice-manager {
    display: flex;
    flex-direction: column;
    height: 100%;
    color: var(--pro-text);
}

.vm-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px 14px;
    border-bottom: 1px solid var(--color-divider);
}

.vm-title {
    font-size: 1rem;
    font-weight: 700;
    margin: 0;
    color: var(--pro-text);
    display: flex;
    align-items: center;
    gap: 8px;
}

.vm-header-right {
    display: flex;
    align-items: center;
    gap: 8px;
}

.vm-count {
    font-size: 0.76rem;
    color: var(--color-text-secondary);
    background-color: var(--color-surface-soft);
    border: 1px solid var(--color-border);
    padding: 4px 10px;
    border-radius: 999px;
    font-weight: 700;
}

.header-action-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: 10px;
    border: 1px solid rgba(10, 132, 255, 0.18);
    background: #eef4ff;
    color: var(--color-primary);
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;
}

.header-text-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 12px;
    border-radius: 10px;
    border: 1px solid rgba(10, 132, 255, 0.18);
    background: #eef4ff;
    color: var(--color-primary);
    cursor: pointer;
    font-size: 0.78rem;
    font-weight: 700;
    transition: background-color 0.2s ease, border-color 0.2s ease;
}

.header-action-btn:hover,
.header-text-btn:hover {
    background: #e4efff;
    border-color: rgba(10, 132, 255, 0.24);
}

.vm-message {
    margin: 0 16px 8px;
    padding: 10px 12px;
    border-radius: 10px;
    background: #edf9f0;
    border: 1px solid rgba(21, 128, 61, 0.18);
    color: var(--pro-success);
    font-size: 0.8rem;
    font-weight: 600;
}

.vm-search {
    padding: 10px 16px;
}

.search-input-wrapper {
    position: relative;
    display: flex;
    align-items: center;
}

.search-icon {
    position: absolute;
    left: 12px;
    color: var(--color-text-tertiary);
    pointer-events: none;
}

.search-input {
    width: 100%;
    padding: 10px 12px 10px 36px;
    border-radius: 12px;
    border: 1px solid var(--color-border);
    background-color: var(--color-input-bg);
    color: var(--color-text);
    font-size: 0.85rem;
    outline: none;
    transition: all 0.2s ease;
    font-family: inherit;
    box-sizing: border-box;
}

.search-input::placeholder {
    color: var(--color-text-quaternary);
}

.search-input:focus {
    border-color: rgba(10, 132, 255, 0.35);
    box-shadow: 0 0 0 3px var(--color-focus-ring);
}

.vm-list {
    flex: 1;
    overflow-y: auto;
    padding: 10px 12px 12px;
    background: var(--color-surface-muted);
    border-radius: 18px;
}

.vm-loading,
.vm-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 32px 0;
    color: var(--pro-text-muted);
    font-size: 0.85rem;
    flex-direction: column;
}

.spinner-ring {
    width: 20px;
    height: 20px;
    border: 2px solid rgba(148, 163, 184, 0.18);
    border-top-color: var(--color-primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.vm-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 24px 0;
    color: var(--pro-danger);
    font-size: 0.85rem;
}

.retry-btn {
    padding: 6px 12px;
    border-radius: 8px;
    background-color: #fff1f2;
    color: var(--pro-danger);
    border: 1px solid rgba(220, 38, 38, 0.2);
    cursor: pointer;
    font-size: 0.8rem;
    font-family: inherit;
}

.voice-group {
    margin-bottom: 10px;
}

.group-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 10px;
    border-radius: 12px;
    transition: background-color 0.15s, border-color 0.15s;
    user-select: none;
    border: 1px solid transparent;
}

.group-header:hover {
    background-color: #f8fafc;
    border-color: var(--color-border);
}

.group-header-left {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    flex: 1;
}

.group-arrow {
    color: var(--color-text-tertiary);
    transition: transform 0.2s ease;
}

.group-arrow.expanded {
    transform: rotate(90deg);
}

.group-name {
    font-weight: 700;
    font-size: 0.9rem;
    color: var(--pro-text);
}

.group-count {
    font-size: 0.72rem;
    color: var(--color-text-secondary);
    background-color: var(--color-surface-soft);
    border: 1px solid var(--color-border);
    padding: 2px 7px;
    border-radius: 999px;
    font-weight: 700;
}

.group-actions {
    display: flex;
    align-items: center;
    gap: 8px;
}

.group-action-btn {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    color: var(--pro-text-muted);
    padding: 5px;
    border-radius: 8px;
    cursor: pointer;
    opacity: 0.72;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
}

.group-action-btn:hover {
    opacity: 1 !important;
    color: var(--color-primary);
    border-color: rgba(10, 132, 255, 0.22);
    background-color: #eef4ff;
}

.edit-emotion-btn {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    color: var(--pro-text-muted);
    padding: 5px;
    border-radius: 8px;
    cursor: pointer;
    opacity: 0.72;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
}

.edit-emotion-btn:hover {
    opacity: 1 !important;
    color: var(--color-primary);
    border-color: rgba(10, 132, 255, 0.22);
    background-color: #eef4ff;
}

.group-items {
    padding: 8px 0 0 12px;
}

.voice-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    border-radius: 14px;
    cursor: pointer;
    transition: all 0.2s ease;
    border: 1px solid var(--color-border);
    margin-bottom: 8px;
    background-color: var(--color-surface);
}

.voice-card:hover {
    background-color: #fcfdff;
    border-color: var(--color-border-strong);
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.voice-card.voice-selected {
    background-color: #f2f8ff;
    border-color: rgba(10, 132, 255, 0.3);
    box-shadow: 0 10px 24px rgba(10, 132, 255, 0.08);
}

.color-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}

.voice-info {
    display: flex;
    flex-direction: column;
    gap: 1px;
    flex: 1;
    min-width: 0;
}

.voice-name {
    font-size: 0.88rem;
    font-weight: 700;
    color: var(--pro-text);
}

.voice-emotion {
    font-size: 0.76rem;
    color: var(--color-text-secondary);
}

.voice-mode {
    font-size: 0.68rem;
    color: var(--color-text-tertiary);
    background-color: var(--color-surface-soft);
    border: 1px solid var(--color-border);
    padding: 4px 8px;
    border-radius: 999px;
    white-space: nowrap;
    font-weight: 700;
}

.voice-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
}

.voice-action-btn,
.voice-del-btn {
    background: var(--color-surface-soft);
    border: 1px solid var(--color-border);
    cursor: pointer;
    color: var(--pro-text-muted);
    opacity: 0.72;
    padding: 5px;
    border-radius: 8px;
    transition: all 0.15s;
}

.voice-del-btn { flex-shrink: 0; }

.voice-action-btn:hover {
    opacity: 1 !important;
    color: var(--color-primary);
    border-color: rgba(10, 132, 255, 0.22);
    background-color: #eef4ff;
}

.voice-del-btn:hover {
    opacity: 1 !important;
    color: var(--pro-danger);
    border-color: rgba(220, 38, 38, 0.2);
    background-color: #fff1f2;
}

.vm-footer {
    padding: 16px;
    border-top: 1px solid var(--color-divider);
    background-color: transparent;
}

.add-voice-btn {
    width: 100%;
    padding: 12px;
    border-radius: 12px;
    background-color: #f7faff;
    color: var(--color-primary);
    border: 1px dashed rgba(10, 132, 255, 0.28);
    font-size: 0.85rem;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.2s ease;
    font-family: inherit;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
}

.add-voice-btn:hover {
    background-color: #eef4ff;
    border-color: rgba(10, 132, 255, 0.38);
    transform: translateY(-1px);
}

.vm-list::-webkit-scrollbar {
    width: 5px;
}

.vm-list::-webkit-scrollbar-track {
    background: transparent;
}

.vm-list::-webkit-scrollbar-thumb {
    background: rgba(148, 163, 184, 0.3);
    border-radius: 3px;
}

.emotion-editor-overlay {
    position: fixed;
    inset: 0;
    background-color: rgba(15, 23, 42, 0.48);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    backdrop-filter: blur(4px);
}

.emotion-editor-modal {
    background-color: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 28px;
    width: 90%;
    max-width: 860px;
    height: min(84vh, 860px);
    overflow: hidden;
    box-shadow: 0 28px 72px rgba(15, 23, 42, 0.18);
}

.utility-overlay {
    position: fixed;
    inset: 0;
    background-color: rgba(15, 23, 42, 0.48);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    backdrop-filter: blur(4px);
}

.utility-modal {
    width: min(860px, 92vw);
    max-height: 84vh;
    overflow: auto;
    padding: 24px;
    border-radius: 24px;
    border: 1px solid var(--color-border);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(250, 251, 253, 0.98) 100%);
    box-shadow: 0 28px 72px rgba(15, 23, 42, 0.18);
    display: flex;
    flex-direction: column;
    gap: 18px;
}

.utility-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
}

.utility-title {
    margin: 0;
    color: var(--pro-text);
    font-size: 1.1rem;
}

.utility-desc {
    margin: 8px 0 0;
    color: var(--color-text-secondary);
    line-height: 1.55;
    font-size: 0.9rem;
}

.close-btn-inline {
    border: 1px solid var(--color-border);
    background: var(--color-surface);
    color: var(--color-text-secondary);
    border-radius: 10px;
    min-height: 32px;
    padding: 0 12px;
    cursor: pointer;
}

.utility-field {
    display: flex;
    flex-direction: column;
    gap: 8px;
    color: var(--color-text-secondary);
    font-size: 0.84rem;
    font-weight: 700;
}

.rename-table {
    display: grid;
    gap: 10px;
}

.rename-row {
    display: grid;
    grid-template-columns: minmax(0, 1.3fr) minmax(160px, 0.8fr) minmax(0, 1.3fr);
    gap: 12px;
    align-items: center;
    padding: 12px 14px;
    border-radius: 14px;
    border: 1px solid var(--color-border);
    background: var(--color-surface);
    font-size: 0.84rem;
}

.rename-head {
    background: var(--color-surface-soft);
    font-weight: 700;
    color: var(--color-text-secondary);
}

.rename-input {
    min-height: 40px;
    border-radius: 10px;
    border: 1px solid var(--color-border);
    background: var(--color-input-bg);
    padding: 0 12px;
    color: var(--color-text);
}

.utility-error {
    margin: 0;
    padding: 12px 14px;
    border-radius: 12px;
    background: #fff1f2;
    color: var(--pro-danger);
    border: 1px solid rgba(220, 38, 38, 0.16);
    font-size: 0.82rem;
    font-weight: 600;
}

.failure-box,
.preview-box {
    display: grid;
    gap: 12px;
    padding: 16px;
    border-radius: 16px;
    border: 1px solid var(--color-border);
    background: var(--color-surface-soft);
}

.failure-title,
.preview-title {
    margin: 0;
    color: var(--pro-text);
    font-size: 0.9rem;
    font-weight: 700;
}

.failure-item {
    margin: 0;
    color: var(--color-text-secondary);
    line-height: 1.5;
    font-size: 0.82rem;
}

.preview-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
}

.preview-item {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px;
    border-radius: 14px;
    border: 1px solid var(--color-border);
    background: var(--color-surface);
    color: var(--color-text-secondary);
    font-size: 0.8rem;
}

.preview-item strong {
    color: var(--pro-text);
    font-size: 1.15rem;
}

.utility-actions {
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 12px;
}

.utility-primary-btn {
    min-height: 40px;
    padding: 0 16px;
    border-radius: 12px;
    background-color: #f7faff;
    color: var(--color-primary);
    border: 1px dashed rgba(10, 132, 255, 0.28);
    font-size: 0.85rem;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.2s ease;
    font-family: inherit;
}

.utility-primary-btn:hover:not(:disabled) {
    background-color: #eef4ff;
    border-color: rgba(10, 132, 255, 0.38);
}

.utility-primary-btn:disabled {
    cursor: not-allowed;
    opacity: 0.6;
}

@media (max-width: 900px) {
    .rename-row,
    .preview-grid {
        grid-template-columns: 1fr;
    }

    .utility-header {
        flex-direction: column;
    }
}
</style>
