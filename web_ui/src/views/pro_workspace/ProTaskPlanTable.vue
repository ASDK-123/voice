<script setup lang="ts">
// Pro 批量合成核心任务表格
// 内联编辑、音色选择、语速滑块、状态动画

import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useProTaskStore } from '@/stores/pro_task'
import { useProVoiceStore } from '@/stores/pro_voice'
import { useSystemStore } from '@/stores/system'
import { useExportStore } from '@/stores/export'
import StatusBadge from '@/components/shared/StatusBadge.vue'
import { 
    ClipboardDocumentListIcon,
    ClockIcon,
    XCircleIcon,
    DocumentTextIcon,
    PlusIcon,
    TrashIcon,
    StopCircleIcon,
    RocketLaunchIcon,
    ArrowLeftIcon,
    PlayIcon,
    ArrowDownTrayIcon,
    FolderOpenIcon,
    ArchiveBoxArrowDownIcon,
    ArrowPathIcon
} from '@heroicons/vue/24/outline'

const taskStore = useProTaskStore()
const voiceStore = useProVoiceStore()
const systemStore = useSystemStore()
const exportStore = useExportStore()

// 当前正在编辑的行 ID
const editingRowId = ref<string | null>(null)
const playbackUrls = ref<Record<string, string>>({})
const resolvedAudioPaths = new Map<string, string>()
const loadingRows = new Set<string>()
const fileInput = ref<HTMLInputElement | null>(null)
const rowStatusFilter = ref<'all' | 'idle' | 'pending' | 'processing' | 'done' | 'failed'>('all')

const visibleRows = computed(() => {
    if (rowStatusFilter.value === 'all') return taskStore.taskRows
    return taskStore.taskRows.filter(row => row.status === rowStatusFilter.value)
})

const latestSnapshotStatusText = computed(() => {
    const status = taskStore.latestResultSnapshot?.status || ''
    const map: Record<string, string> = {
        done: '最近批次已完成',
        completed: '最近批次已完成',
        cancelled: '最近批次已取消',
        processing: '最近批次处理中',
    }
    return map[status] || '最近批次已结束'
})

/** 开始编辑某行文本 */
function startEdit(rowId: string) {
    editingRowId.value = rowId
}

/** 结束编辑 */
function finishEdit() {
    editingRowId.value = null
}

/** 格式化时长 */
function formatDuration(ms: number | null): string {
    if (!ms) return '--'
    const sec = (ms / 1000).toFixed(1)
    return `${sec}s`
}

/** 状态对应的样式类 */
function statusClass(status: string): string {
    const map: Record<string, string> = {
        idle: 'st-idle',
        pending: 'st-pending',
        processing: 'st-processing',
        done: 'st-done',
        failed: 'st-failed',
    }
    return map[status] || 'st-idle'
}

/** 状态对应的文字 */
function statusText(status: string): string {
    const map: Record<string, string> = {
        idle: '待定',
        pending: '排队中',
        processing: '合成中',
        done: '完成',
        failed: '失败',
    }
    return map[status] || status
}

/** 为行自动分配选中的音色 */
function applySelectedVoice(rowId: string) {
    if (voiceStore.selectedVoiceId) {
        taskStore.updateRowVoice(rowId, voiceStore.selectedVoiceId)
    }
}

// 监听音色选择变化，自动填充到当前编辑行
watch(() => voiceStore.selectedVoiceId, (newId) => {
    if (newId && editingRowId.value) {
        taskStore.updateRowVoice(editingRowId.value, newId)
    }
})

function releasePlaybackUrl(rowId: string) {
    const currentUrl = playbackUrls.value[rowId]
    if (currentUrl?.startsWith('blob:')) {
        URL.revokeObjectURL(currentUrl)
    }
    delete playbackUrls.value[rowId]
    resolvedAudioPaths.delete(rowId)
    loadingRows.delete(rowId)
}

function statusTone(status: string): 'neutral' | 'processing' | 'success' | 'warning' | 'danger' {
    const map: Record<string, 'neutral' | 'processing' | 'success' | 'warning' | 'danger'> = {
        idle: 'neutral',
        pending: 'warning',
        processing: 'processing',
        done: 'success',
        failed: 'danger',
    }
    return map[status] || 'neutral'
}

async function ensurePlaybackUrl(rowId: string, audioPath: string) {
    if (!audioPath || loadingRows.has(rowId)) return
    if (resolvedAudioPaths.get(rowId) === audioPath && playbackUrls.value[rowId]) return

    loadingRows.add(rowId)
    try {
        const url = await systemStore.getClient().getAuthedAudioUrl(audioPath)
        const prevUrl = playbackUrls.value[rowId]
        if (prevUrl?.startsWith('blob:') && prevUrl !== url) {
            URL.revokeObjectURL(prevUrl)
        }
        playbackUrls.value[rowId] = url
        resolvedAudioPaths.set(rowId, audioPath)
    } catch {
        playbackUrls.value[rowId] = audioPath
        resolvedAudioPaths.set(rowId, audioPath)
    } finally {
        loadingRows.delete(rowId)
    }
}

watch(
    () => taskStore.taskRows.map(row => ({
        rowId: row.row_id,
        status: row.status,
        audioUrl: row.audio_url || '',
    })),
    rows => {
        const activeRowIds = new Set(
            rows
                .filter(row => row.status === 'done' && row.audioUrl)
                .map(row => row.rowId),
        )

        for (const rowId of Object.keys(playbackUrls.value)) {
            if (!activeRowIds.has(rowId)) {
                releasePlaybackUrl(rowId)
            }
        }

        rows.forEach(row => {
            if (row.status === 'done' && row.audioUrl) {
                void ensurePlaybackUrl(row.rowId, row.audioUrl)
            } else {
                releasePlaybackUrl(row.rowId)
            }
        })
    },
    { deep: true, immediate: true },
)

onBeforeUnmount(() => {
    Object.keys(playbackUrls.value).forEach(releasePlaybackUrl)
})

function triggerImportPlan() {
    fileInput.value?.click()
}

async function handleImportPlan(event: Event) {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return

    try {
        await exportStore.importTaskPlanFile(file)
    } finally {
        input.value = ''
    }
}

async function exportMergedResult() {
    await exportStore.exportMergedTaskAudio()
}

async function retryRow(rowId: string) {
    await taskStore.retryFailedRows([rowId])
}

async function retryAllFailedRows() {
    await taskStore.retryFailedRows()
}
</script>

<template>
    <div class="task-table">
        <input
            ref="fileInput"
            type="file"
            accept=".json"
            class="hidden-file-input"
            @change="handleImportPlan"
        />
        <!-- 头部 -->
        <div class="tt-header">
            <h3 class="tt-title">
                <ClipboardDocumentListIcon class="w-5 h-5 text-indigo-400" />
                <span>批量合成任务</span>
            </h3>
            <div class="tt-stats">
                <span v-if="taskStore.isBatchRunning" class="stats-running flex items-center gap-1">
                    <ClockIcon class="w-4 h-4" /> 已完成 {{ taskStore.completedCount }}/{{ taskStore.totalCount }}
                </span>
                <span v-if="taskStore.failedCount > 0" class="stats-failed flex items-center gap-1">
                    <XCircleIcon class="w-4 h-4" /> {{ taskStore.failedCount }} 失败
                </span>
            </div>
        </div>

        <div v-if="taskStore.importSummary" class="result-card import-card">
            <div>
                <p class="result-title">剧本导入摘要</p>
                <p class="result-meta">
                    已导入 {{ taskStore.importSummary.imported }} 行，
                    跳过 BGM {{ taskStore.importSummary.skippedBgm }} 行，
                    未解析 {{ taskStore.importSummary.unresolved }} 行。
                </p>
            </div>
            <button class="action-btn clear-btn" @click="taskStore.clearImportSummary()">关闭</button>
        </div>

        <div v-if="taskStore.latestResultSnapshot" class="result-card">
            <div>
                <p class="result-title">{{ latestSnapshotStatusText }}</p>
                <p class="result-meta">
                    保存于 {{ taskStore.latestResultSnapshot.saved_at }}，
                    完成 {{ taskStore.latestResultSnapshot.completed }} 行，
                    失败 {{ taskStore.latestResultSnapshot.failed }} 行。
                </p>
            </div>
            <div class="result-actions">
                <button class="action-btn load-btn" @click="taskStore.restoreLatestResult('all')">恢复最近结果到表格</button>
                <button
                    class="action-btn merge-btn"
                    :disabled="taskStore.latestResultSnapshot.failed === 0"
                    @click="taskStore.restoreLatestResult('failed')"
                >
                    仅恢复失败行
                </button>
                <button class="action-btn clear-btn" @click="taskStore.clearLatestResultSnapshot()">清除最近结果</button>
            </div>
        </div>

        <div class="summary-strip">
            <div class="summary-pill">
                <span class="summary-label">总行数</span>
                <strong>{{ taskStore.totalCount }}</strong>
            </div>
            <div class="summary-pill">
                <span class="summary-label">已完成</span>
                <strong>{{ taskStore.completedCount }}</strong>
            </div>
            <div class="summary-pill">
                <span class="summary-label">失败</span>
                <strong>{{ taskStore.failedCount }}</strong>
            </div>
            <div class="summary-pill">
                <span class="summary-label">最近状态</span>
                <strong>{{ latestSnapshotStatusText }}</strong>
            </div>
        </div>

        <div class="table-toolbar">
            <select v-model="rowStatusFilter" class="voice-select toolbar-select">
                <option value="all">全部</option>
                <option value="idle">待处理</option>
                <option value="pending">排队中</option>
                <option value="processing">处理中</option>
                <option value="done">已完成</option>
                <option value="failed">失败</option>
            </select>
            <button
                class="action-btn load-btn flex items-center gap-1.5"
                :disabled="taskStore.isBatchRunning || taskStore.failedCount === 0"
                @click="retryAllFailedRows"
            >
                <ArrowPathIcon class="w-4 h-4" />
                <span>重试全部失败行</span>
            </button>
        </div>

        <!-- 表格头 -->
        <div class="table-head">
            <span class="col-idx">#</span>
            <span class="col-text">文本内容</span>
            <span class="col-voice">音色</span>
            <span class="col-speed">语速</span>
            <span class="col-mode">模式</span>
            <span class="col-instruct">指令</span>
            <span class="col-seed">Seed</span>
            <span class="col-status">状态</span>
            <span class="col-action">操作</span>
        </div>

        <!-- 任务行列表 -->
        <div class="table-body">
            <div
                v-for="(row, idx) in visibleRows"
                :key="row.row_id"
                class="task-row"
                :class="statusClass(row.status)"
            >
                <!-- 序号 -->
                <span class="col-idx row-idx">{{ idx + 1 }}</span>

                <!-- 文本编辑 -->
                <div class="col-text">
                    <textarea
                        v-if="editingRowId === row.row_id || row.status === 'idle'"
                        :value="row.text"
                        @input="(e) => taskStore.updateRowText(row.row_id, (e.target as HTMLTextAreaElement).value)"
                        @focus="startEdit(row.row_id)"
                        @blur="finishEdit()"
                        placeholder="输入要合成的文本..."
                        class="text-edit"
                        rows="2"
                    ></textarea>
                    <div v-else class="text-display" @click="startEdit(row.row_id)">
                        {{ row.text || '(空)' }}
                    </div>
                </div>

                <!-- 音色选择 -->
                <div class="col-voice">
                    <select
                        :value="row.voice_id"
                        @change="(e) => taskStore.updateRowVoice(row.row_id, (e.target as HTMLSelectElement).value)"
                        class="voice-select"
                        :disabled="row.status === 'processing'"
                    >
                        <option value="">选择音色</option>
                        <option
                            v-for="v in voiceStore.voices"
                            :key="v.name"
                            :value="v.name"
                        >
                            {{ v.character }}#{{ v.emotion }}
                        </option>
                    </select>
                    <!-- 快捷填充按钮 -->
                    <button
                        v-if="voiceStore.selectedVoiceId && row.voice_id !== voiceStore.selectedVoiceId"
                        class="quick-fill"
                        @click="applySelectedVoice(row.row_id)"
                        title="使用左侧选中的音色"
                    >
                        <ArrowLeftIcon class="w-3 h-3 stroke-2" />
                    </button>
                </div>

                <!-- 语速滑块 -->
                <div class="col-speed">
                    <input
                        type="range"
                        :value="row.speed"
                        @input="(e) => taskStore.updateRowSpeed(row.row_id, parseFloat((e.target as HTMLInputElement).value))"
                        min="0.5"
                        max="2.0"
                        step="0.1"
                        class="speed-slider"
                        :disabled="row.status === 'processing'"
                    />
                    <span class="speed-value">{{ row.speed.toFixed(1) }}x</span>
                </div>

                <div class="col-mode">
                    <select
                        :value="row.mode"
                        @change="(e) => taskStore.updateRowMode(row.row_id, (e.target as HTMLSelectElement).value as any)"
                        class="mode-select"
                        :disabled="row.status === 'processing'"
                    >
                        <option value="zero_shot">zero_shot</option>
                        <option value="instruct">instruct</option>
                        <option value="cross_lingual">cross_lingual</option>
                    </select>
                </div>

                <div class="col-instruct">
                    <input
                        :value="row.instruct_text"
                        @input="(e) => taskStore.updateRowInstructText(row.row_id, (e.target as HTMLInputElement).value)"
                        class="instruct-input"
                        :disabled="row.status === 'processing' || row.mode !== 'instruct'"
                        placeholder="instruct_text"
                    />
                </div>

                <div class="col-seed">
                    <input
                        type="number"
                        :value="row.seed"
                        @input="(e) => taskStore.updateRowSeed(row.row_id, parseInt((e.target as HTMLInputElement).value || '42', 10))"
                        class="seed-input"
                        :disabled="row.status === 'processing'"
                        min="0"
                        step="1"
                    />
                </div>

                <!-- 状态指示 -->
                <div class="col-status">
                    <StatusBadge :label="statusText(row.status)" :tone="statusTone(row.status)" />

                    <!-- 完成后显示时长 -->
                    <span v-if="row.status === 'done' && row.duration_ms" class="duration">
                        {{ formatDuration(row.duration_ms) }}
                    </span>

                    <!-- 完成后显示播放器 -->
                    <audio
                        v-if="row.status === 'done' && row.audio_url"
                        :src="playbackUrls[row.row_id] || row.audio_url"
                        controls
                        class="audio-player"
                    ></audio>

                    <!-- 错误信息 -->
                    <span v-if="row.status === 'failed' && row.error" class="error-msg" :title="row.error">
                        {{ row.error }}
                    </span>
                </div>

                <!-- 操作 -->
                <div class="col-action">
                    <button
                        class="row-run-btn"
                        @click="taskStore.submitSingleRow(row.row_id)"
                        :disabled="row.status === 'processing' || taskStore.isBatchRunning || !row.text.trim() || !row.voice_id"
                        title="单行运行"
                    >
                        <PlayIcon class="w-4 h-4" />
                    </button>
                    <button
                        v-if="row.status === 'failed'"
                        class="row-run-btn retry-btn"
                        @click="retryRow(row.row_id)"
                        :disabled="taskStore.isBatchRunning"
                        title="重试失败行"
                    >
                        <ArrowPathIcon class="w-4 h-4" />
                    </button>
                    <button
                        class="del-btn"
                        @click="taskStore.removeRow(row.row_id)"
                        :disabled="row.status === 'processing'"
                        title="删除"
                    >
                        <TrashIcon class="w-4 h-4" />
                    </button>
                </div>
            </div>

            <!-- 空状态 -->
            <div v-if="visibleRows.length === 0" class="empty-state">
                <DocumentTextIcon class="w-12 h-12 text-indigo-900 mb-2 opacity-50" />
                <span>{{ taskStore.taskRows.length === 0 ? '点击下方按钮添加合成任务行' : '当前筛选下没有任务行' }}</span>
            </div>
        </div>

        <!-- 底部操作栏 -->
        <div class="tt-footer">
            <div class="footer-left">
                <button class="action-btn add-btn flex items-center gap-1.5" @click="taskStore.addRow()">
                    <PlusIcon class="w-4 h-4 stroke-2" />
                    <span>新增行</span>
                </button>
                <button
                    class="action-btn save-btn flex items-center gap-1.5"
                    @click="exportStore.exportTaskPlanFile()"
                    :disabled="taskStore.taskRows.length === 0"
                >
                    <ArrowDownTrayIcon class="w-4 h-4" />
                    <span>保存计划</span>
                </button>
                <button class="action-btn load-btn flex items-center gap-1.5" @click="exportStore.restoreTaskDraft()">
                    <ArchiveBoxArrowDownIcon class="w-4 h-4" />
                    <span>恢复草稿</span>
                </button>
                <button class="action-btn load-btn flex items-center gap-1.5" @click="triggerImportPlan">
                    <FolderOpenIcon class="w-4 h-4" />
                    <span>导入计划</span>
                </button>
                <button
                    v-if="taskStore.taskRows.length > 0"
                    class="action-btn clear-btn flex items-center gap-1.5"
                    @click="taskStore.clearAll()"
                    :disabled="taskStore.isBatchRunning"
                >
                    <TrashIcon class="w-4 h-4" />
                    <span>清空</span>
                </button>
            </div>

            <div class="footer-right">
                <!-- 错误消息 -->
                <span v-if="taskStore.error" class="footer-error">{{ taskStore.error }}</span>
                <span v-else-if="exportStore.progressMessage" class="footer-message">{{ exportStore.progressMessage }}</span>

                <!-- 进度信息 -->
                <span v-if="taskStore.isBatchRunning" class="progress-text">
                    已完成 {{ taskStore.completedCount }} / {{ taskStore.totalCount }}
                </span>

                <!-- 取消按钮 -->
                <button
                    v-if="taskStore.isBatchRunning"
                    class="action-btn cancel-btn flex items-center gap-1.5"
                    @click="taskStore.cancelBatch()"
                >
                    <StopCircleIcon class="w-4 h-4" />
                    <span>取消</span>
                </button>

                <!-- 合成按钮 -->
                <button
                    v-else
                    class="action-btn merge-btn flex items-center gap-1.5"
                    :disabled="taskStore.taskRows.filter(r => r.status === 'done' && r.audio_url).length === 0"
                    @click="exportMergedResult"
                >
                    <ArchiveBoxArrowDownIcon class="w-4 h-4" />
                    <span>合并导出</span>
                </button>

                <button
                    v-if="!taskStore.isBatchRunning"
                    class="submit-btn"
                    :disabled="taskStore.validRows.length === 0"
                    @click="taskStore.submitBatch()"
                >
                    <RocketLaunchIcon class="w-5 h-5" />
                    <span>全部合成</span>
                    <span v-if="taskStore.validRows.length > 0" class="submit-count">
                        ({{ taskStore.validRows.length }} 行)
                    </span>
                </button>
            </div>
        </div>
    </div>
</template>

<style scoped>
.hidden-file-input { display: none; }

.task-table {
    display: flex;
    flex-direction: column;
    height: 100%;
    color: var(--pro-text);
}

.tt-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px 14px;
    border-bottom: 1px solid var(--color-divider);
}

.tt-title {
    font-size: 1rem;
    font-weight: 700;
    margin: 0;
    color: var(--pro-text);
    display: flex;
    align-items: center;
    gap: 8px;
}

.tt-stats {
    display: flex;
    gap: 10px;
    font-size: 0.8rem;
}

.result-card {
    margin: 12px 16px 0;
    padding: 14px 16px;
    border: 1px solid var(--color-border);
    border-radius: 16px;
    background: var(--color-surface);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
}

.import-card {
    background: #f8fbff;
}

.result-title {
    margin: 0;
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--pro-text);
}

.result-meta {
    margin: 4px 0 0;
    font-size: 0.76rem;
    color: var(--color-text-secondary);
}

.result-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.summary-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
    padding: 12px 16px 0;
}

.summary-pill {
    padding: 12px 14px;
    border: 1px solid var(--color-border);
    border-radius: 14px;
    background: var(--color-surface);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
}

.summary-label {
    font-size: 0.74rem;
    color: var(--color-text-secondary);
}

.table-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 16px 0;
    flex-wrap: wrap;
}

.stats-running {
    color: var(--pro-accent);
    font-weight: 600;
}

.stats-failed { color: var(--pro-danger); }

.table-head {
    display: grid;
    grid-template-columns: 40px minmax(240px, 1fr) 150px 110px 120px 160px 90px 150px 78px;
    min-width: 1120px;
    gap: 8px;
    padding: 12px 16px 10px;
    font-size: 0.74rem;
    font-weight: 700;
    color: var(--color-text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--color-divider);
}

.table-body {
    flex: 1;
    overflow: auto;
    padding: 14px 12px 8px;
    background: var(--color-surface-muted);
    border-radius: 18px;
}

.task-row {
    display: grid;
    grid-template-columns: 40px minmax(240px, 1fr) 150px 110px 120px 160px 90px 150px 78px;
    min-width: 1120px;
    gap: 8px;
    padding: 12px 10px;
    align-items: start;
    border: 1px solid var(--color-border);
    border-radius: 16px;
    margin-bottom: 12px;
    background: var(--color-surface);
    transition: background-color 0.15s, border-color 0.15s, box-shadow 0.15s;
}

.task-row:hover {
    background-color: #fcfdff;
    border-color: var(--color-border-strong);
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.task-row.st-processing {
    background-color: #fff8f2;
    border-color: rgba(249, 115, 22, 0.26);
}

.task-row.st-done {
    background-color: #f3fbf5;
    border-color: rgba(21, 128, 61, 0.2);
}

.task-row.st-failed {
    background-color: #fff5f5;
    border-color: rgba(220, 38, 38, 0.2);
}

.row-idx {
    font-size: 0.8rem;
    color: var(--pro-text-muted);
    font-weight: 600;
    text-align: center;
    padding-top: 6px;
}

.text-edit,
.voice-select,
.mode-select,
.instruct-input,
.seed-input {
    background-color: var(--pro-input-bg);
    color: var(--pro-text);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    outline: none;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
    font-family: inherit;
    box-sizing: border-box;
}

.text-edit:focus,
.voice-select:focus,
.mode-select:focus,
.instruct-input:focus,
.seed-input:focus {
    border-color: rgba(10, 132, 255, 0.35);
    box-shadow: 0 0 0 3px var(--color-focus-ring);
}

.text-edit {
    width: 100%;
    padding: 10px 12px;
    font-size: 0.85rem;
    resize: vertical;
    min-height: 48px;
    line-height: 1.6;
}

.text-edit::placeholder,
.instruct-input::placeholder {
    color: var(--color-text-quaternary);
}

.text-display {
    padding: 10px 12px;
    font-size: 0.85rem;
    cursor: text;
    color: var(--pro-text);
    min-height: 38px;
    border-radius: 10px;
    border: 1px solid transparent;
    transition: background-color 0.2s, border-color 0.2s;
    line-height: 1.6;
}

.text-display:hover {
    background-color: var(--color-surface-muted);
    border-color: var(--color-border);
}

.col-voice {
    display: flex;
    align-items: center;
    gap: 4px;
}

.voice-select {
    flex: 1;
    padding: 8px 10px;
    font-size: 0.78rem;
    cursor: pointer;
    min-width: 0;
}

.toolbar-select {
    max-width: 140px;
}

.voice-select:disabled,
.mode-select:disabled,
.instruct-input:disabled,
.seed-input:disabled {
    opacity: 0.72;
    color: var(--color-text-tertiary);
    background: var(--color-surface-soft);
}

.quick-fill {
    background: #fff4ea;
    border: 1px solid rgba(249, 115, 22, 0.24);
    color: var(--pro-accent);
    border-radius: 8px;
    padding: 5px 7px;
    cursor: pointer;
    font-size: 0.75rem;
    transition: background-color 0.15s, border-color 0.15s;
    flex-shrink: 0;
}

.quick-fill:hover {
    background: #ffe7d1;
    border-color: rgba(249, 115, 22, 0.32);
}

.col-speed {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding-top: 4px;
}

.speed-slider {
    width: 100%;
    height: 5px;
    cursor: pointer;
    accent-color: var(--color-primary);
}

.speed-value {
    font-size: 0.7rem;
    color: var(--pro-text-muted);
    font-weight: 600;
}

.mode-select,
.instruct-input,
.seed-input {
    width: 100%;
    padding: 8px 10px;
    font-size: 0.78rem;
}

.col-status {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-top: 4px;
}

.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.75rem;
    font-weight: 700;
    padding: 6px 10px;
    border-radius: 999px;
    border: 1px solid transparent;
    width: fit-content;
}

@keyframes pulse-dot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(1.3); }
}

.duration {
    font-size: 0.72rem;
    color: var(--color-text-secondary);
    font-weight: 600;
}

.audio-player {
    width: 138px;
    height: 30px;
}

.error-msg {
    font-size: 0.72rem;
    color: var(--pro-danger);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 130px;
}

.col-action {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding-top: 4px;
}

.row-run-btn,
.del-btn {
    border: 1px solid transparent;
    cursor: pointer;
    padding: 6px;
    border-radius: 8px;
    transition: background-color 0.15s, border-color 0.15s, color 0.15s;
    display: inline-flex;
    align-items: center;
    justify-content: center;
}

.row-run-btn {
    background: #edf9f0;
    border-color: rgba(21, 128, 61, 0.18);
    color: var(--pro-success);
}

.row-run-btn:hover:not(:disabled) {
    background: #dcf5e4;
}

.retry-btn {
    background: #fff7ed;
    border-color: rgba(249, 115, 22, 0.2);
    color: var(--pro-accent);
}

.retry-btn:hover:not(:disabled) {
    background: #ffedd5;
}

.row-run-btn:disabled,
.del-btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
}

.row-run-btn:disabled {
    color: var(--color-text-tertiary);
    border-color: var(--color-border);
    background: var(--color-surface-soft);
}

.del-btn {
    background: var(--color-surface-soft);
    border-color: var(--color-border);
    color: var(--pro-text-muted);
}

.del-btn:hover:not(:disabled) {
    color: var(--pro-danger);
    border-color: rgba(220, 38, 38, 0.2);
    background-color: #fff1f2;
}

.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    padding: 48px 0;
    color: var(--pro-text-muted);
    font-size: 0.85rem;
}

.tt-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-top: 1px solid var(--color-divider);
    gap: 12px;
    flex-wrap: wrap;
}

.footer-left {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.footer-right {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.footer-message {
    font-size: 0.8rem;
    color: var(--pro-success);
    font-weight: 600;
}

.action-btn {
    padding: 8px 14px;
    border-radius: 10px;
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid var(--color-border);
    transition: all 0.2s;
    font-family: inherit;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--color-surface);
    color: var(--color-text-secondary);
}

.action-btn:disabled {
    opacity: 0.58;
    cursor: not-allowed;
}

.add-btn,
.save-btn,
.load-btn,
.merge-btn {
    background-color: #eef4ff;
    color: var(--color-primary);
    border-color: rgba(10, 132, 255, 0.18);
}

.add-btn:hover:not(:disabled),
.save-btn:hover:not(:disabled),
.load-btn:hover:not(:disabled),
.merge-btn:hover:not(:disabled) {
    background-color: #e4efff;
}

.clear-btn {
    background-color: var(--color-surface-soft);
    color: var(--color-text-secondary);
}

.clear-btn:hover:not(:disabled) {
    background-color: #e9eef5;
}

.cancel-btn {
    background-color: #fff1f2;
    color: var(--pro-danger);
    border-color: rgba(220, 38, 38, 0.2);
}

.cancel-btn:hover:not(:disabled) {
    background-color: #ffe4e6;
}

.submit-btn {
    padding: 10px 24px;
    border-radius: 12px;
    font-size: 0.95rem;
    font-weight: 700;
    cursor: pointer;
    border: none;
    background: linear-gradient(135deg, #f97316, #ea580c);
    color: white;
    box-shadow: 0 4px 12px rgba(249, 115, 22, 0.35);
    transition: all 0.2s;
    font-family: inherit;
    display: flex;
    align-items: center;
    gap: 6px;
}

.submit-btn:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(249, 115, 22, 0.45);
}

.submit-btn:disabled {
    opacity: 0.58;
    cursor: not-allowed;
    transform: none;
}

.submit-count {
    font-size: 0.8rem;
    opacity: 0.85;
}

.progress-text {
    font-size: 0.82rem;
    color: var(--pro-accent);
    font-weight: 600;
}

.footer-error {
    font-size: 0.8rem;
    color: var(--pro-danger);
}

.table-body::-webkit-scrollbar {
    width: 5px;
}

.table-body::-webkit-scrollbar-track {
    background: transparent;
}

.table-body::-webkit-scrollbar-thumb {
    background: rgba(148, 163, 184, 0.3);
    border-radius: 3px;
}

@media (max-width: 1180px) {
    .summary-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 820px) {
    .summary-strip {
        grid-template-columns: 1fr;
    }
}
</style>
