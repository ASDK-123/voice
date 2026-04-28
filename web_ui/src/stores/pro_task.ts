// Pro Task Store
// WebUI 正式任务域：负责批量合成、单行运行、轮询与结果状态
// 不承担剧本创作与单行试听逻辑，统一走共享 Pro client 工厂

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type {
    ProBatchPayload,
    ProBatchState,
    ProRowStatus,
    ProTaskPlanSnapshot,
    ProTaskResultSnapshot,
    ProTaskRow,
    ScriptTaskExportRow,
} from '@/types'
import { createCosyVoiceClientFromActiveConfig } from '@/api/client_factory'
import { mergeAudioBlobs } from '@/utils/audio'

/** 生成简短 UUID */
function genRowId(): string {
    return `row_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

const TASK_PLAN_STORAGE_KEY = 'pro-task-plan-latest-v1'
const TASK_RESULT_STORAGE_KEY = 'pro-task-result-latest-v1'

export const useProTaskStore = defineStore('proTask', () => {
    // ── 状态 ──
    const taskRows = ref<ProTaskRow[]>([])
    const currentBatchId = ref<string | null>(null)
    const currentBatchStatus = ref<ProBatchState>('done')
    const isBatchRunning = ref(false)
    const error = ref('')
    const latestResultSnapshot = ref<ProTaskResultSnapshot | null>(null)
    const importSummary = ref<{
        mode: 'replace' | 'append'
        imported: number
        skippedBgm: number
        unresolved: number
    } | null>(null)

    // ── 轮询定时器 ──
    let pollTimer: ReturnType<typeof setInterval> | null = null

    /** 从 proSystem Store 获取带鉴权的 API 客户端 */
    function getClient() {
        return createCosyVoiceClientFromActiveConfig()
    }

    function normalizeRow(row: Partial<ProTaskRow>): ProTaskRow {
        return {
            row_id: row.row_id || genRowId(),
            text: row.text || '',
            voice_id: row.voice_id || '',
            speed: typeof row.speed === 'number' ? row.speed : 1.0,
            mode: row.mode || 'zero_shot',
            instruct_text: row.instruct_text || '',
            seed: typeof row.seed === 'number' ? row.seed : 42,
            status: row.status || 'idle',
            audio_url: row.audio_url || null,
            duration_ms: typeof row.duration_ms === 'number' ? row.duration_ms : null,
            error: row.error || null,
        }
    }

    function serializeTaskPlan(): ProTaskPlanSnapshot {
        return {
            version: '1.0',
            saved_at: new Date().toISOString(),
            rows: taskRows.value.map(row => ({ ...row })),
            current_batch_id: currentBatchId.value,
            is_batch_running: isBatchRunning.value,
        }
    }

    function restoreTaskPlan(snapshot: Partial<ProTaskPlanSnapshot>) {
        stopPolling()
        taskRows.value = Array.isArray(snapshot.rows) ? snapshot.rows.map(normalizeRow) : []
        currentBatchId.value = snapshot.current_batch_id || null
        isBatchRunning.value = !!snapshot.is_batch_running && !!snapshot.current_batch_id
        error.value = ''

        if (isBatchRunning.value && currentBatchId.value) {
            startPolling()
        }
    }

    function saveTaskPlanToStorage() {
        if (typeof window === 'undefined') return
        window.localStorage.setItem(TASK_PLAN_STORAGE_KEY, JSON.stringify(serializeTaskPlan()))
    }

    function loadTaskPlanFromStorage(): boolean {
        if (typeof window === 'undefined') return false
        const raw = window.localStorage.getItem(TASK_PLAN_STORAGE_KEY)
        if (!raw) return false
        try {
            restoreTaskPlan(JSON.parse(raw) as ProTaskPlanSnapshot)
            return true
        } catch {
            return false
        }
    }

    function saveLatestResultSnapshot(snapshot: ProTaskResultSnapshot) {
        latestResultSnapshot.value = snapshot
        if (typeof window !== 'undefined') {
            window.localStorage.setItem(TASK_RESULT_STORAGE_KEY, JSON.stringify(snapshot))
        }
    }

    function loadLatestResultSnapshot(): boolean {
        if (typeof window === 'undefined') return false
        const raw = window.localStorage.getItem(TASK_RESULT_STORAGE_KEY)
        if (!raw) return false
        try {
            latestResultSnapshot.value = JSON.parse(raw) as ProTaskResultSnapshot
            return true
        } catch {
            latestResultSnapshot.value = null
            return false
        }
    }

    function clearLatestResultSnapshot() {
        latestResultSnapshot.value = null
        if (typeof window !== 'undefined') {
            window.localStorage.removeItem(TASK_RESULT_STORAGE_KEY)
        }
    }

    function clearImportSummary() {
        importSummary.value = null
    }

    // ── 行操作 ──

    /** 新增一行 */
    function addRow() {
        taskRows.value.push({
            row_id: genRowId(),
            text: '',
            voice_id: '',
            speed: 1.0,
            mode: 'zero_shot',
            instruct_text: '',
            seed: 42,
            status: 'idle',
            audio_url: null,
            duration_ms: null,
            error: null,
        })
    }

    /** 删除一行 */
    function removeRow(rowId: string) {
        const idx = taskRows.value.findIndex(r => r.row_id === rowId)
        if (idx >= 0) taskRows.value.splice(idx, 1)
    }

    /** 更新行文本 */
    function updateRowText(rowId: string, text: string) {
        const row = taskRows.value.find(r => r.row_id === rowId)
        if (row) row.text = text
    }

    /** 更新行音色 */
    function updateRowVoice(rowId: string, voiceId: string) {
        const row = taskRows.value.find(r => r.row_id === rowId)
        if (row) row.voice_id = voiceId
    }

    /** 更新行语速 */
    function updateRowSpeed(rowId: string, speed: number) {
        const row = taskRows.value.find(r => r.row_id === rowId)
        if (row) row.speed = speed
    }

    function updateRowMode(rowId: string, mode: ProTaskRow['mode']) {
        const row = taskRows.value.find(r => r.row_id === rowId)
        if (row) row.mode = mode
    }

    function updateRowInstructText(rowId: string, instructText: string) {
        const row = taskRows.value.find(r => r.row_id === rowId)
        if (row) row.instruct_text = instructText
    }

    function updateRowSeed(rowId: string, seed: number) {
        const row = taskRows.value.find(r => r.row_id === rowId)
        if (row) row.seed = seed
    }

    function createTaskRowFromScript(row: ScriptTaskExportRow): ProTaskRow {
        return normalizeRow({
            text: row.text,
            voice_id: row.voice_id,
            speed: 1.0,
            mode: 'zero_shot',
            instruct_text: '',
            seed: 42,
        })
    }

    function replaceRowsFromScript(rows: ScriptTaskExportRow[]) {
        stopPolling()
        taskRows.value = rows.map(createTaskRowFromScript)
        currentBatchId.value = null
        currentBatchStatus.value = 'done'
        isBatchRunning.value = false
        error.value = ''
    }

    function appendRowsFromScript(rows: ScriptTaskExportRow[]) {
        taskRows.value.push(...rows.map(createTaskRowFromScript))
    }

    function setImportSummary(summary: {
        mode: 'replace' | 'append'
        imported: number
        skippedBgm: number
        unresolved: number
    }) {
        importSummary.value = summary
    }

    // ── 统计（已对齐后端的 'failed' 状态） ──

    const completedCount = computed(() =>
        taskRows.value.filter(r => r.status === 'done').length,
    )

    const failedCount = computed(() =>
        taskRows.value.filter(r => r.status === 'failed').length,
    )

    const totalCount = computed(() => taskRows.value.length)

    const validRows = computed(() =>
        taskRows.value.filter(r => r.text.trim() && r.voice_id),
    )

    // ── 批量提交 ──

    async function submitRows(rows: ProTaskRow[]) {
        if (rows.length === 0) {
            error.value = '没有可提交的有效行（需要文本和音色）'
            return
        }
        if (isBatchRunning.value) {
            error.value = '当前已有批次在运行，请等待完成后再提交'
            return
        }

        error.value = ''
        isBatchRunning.value = true
        currentBatchStatus.value = 'processing'

        // 标记所有有效行为 pending
        for (const row of rows) {
            row.status = 'pending'
            row.audio_url = null
            row.duration_ms = null
            row.error = null
        }

        try {
            const payload: ProBatchPayload = {
                items: rows.map(r => ({
                    row_id: r.row_id,
                    text: r.text,
                    voice_id: r.voice_id,
                    speed: r.speed,
                    mode: r.mode,
                    instruct_text: r.instruct_text,
                    variation_seed: r.seed,
                })),
            }

            const result = await getClient().submitBatch(payload)
            currentBatchId.value = result.batch_id

            // 开始轮询进度
            startPolling()
        } catch (e: unknown) {
            error.value = (e as Error).message
            isBatchRunning.value = false
            currentBatchStatus.value = 'done'
            // 回滚状态
            for (const row of rows) {
                row.status = 'idle'
            }
        }
    }

    /** 提交所有有效行进行合成 */
    async function submitBatch() {
        await submitRows(validRows.value)
    }

    async function submitSingleRow(rowId: string) {
        const row = taskRows.value.find(item => item.row_id === rowId)
        if (!row || !row.text.trim() || !row.voice_id) {
            error.value = '当前行缺少文本或音色，无法单行运行'
            return
        }
        await submitRows([row])
    }

    async function exportMergedAudio(): Promise<Blob> {
        const rows = taskRows.value.filter(row => row.status === 'done' && row.audio_url)
        if (rows.length === 0) {
            throw new Error('当前没有已完成的音频结果可导出')
        }

        const blobs = await Promise.all(
            rows.map(row => getClient().getAuthedAudioBlob(row.audio_url!)),
        )
        return await mergeAudioBlobs(blobs)
    }

    /** 轮询批量状态 */
    async function pollBatchStatus() {
        if (!currentBatchId.value) return

        try {
            const status = await getClient().getBatchStatus(currentBatchId.value)
            currentBatchStatus.value = status.status

            // 更新每行状态
            for (const item of status.items) {
                const row = taskRows.value.find(r => r.row_id === item.row_id)
                if (row) {
                    row.status = item.status as ProRowStatus
                    row.audio_url = item.audio_url
                    row.duration_ms = item.duration_ms
                    row.error = item.error
                }
            }

            // 批次完成，停止轮询
            // 兼容后端可能返回 'done' / 'completed' / 'cancelled'
            const terminalStates = ['done', 'completed', 'cancelled']
            if (terminalStates.includes(status.status)) {
                stopPolling()
                isBatchRunning.value = false
                saveLatestResultSnapshot({
                    saved_at: new Date().toISOString(),
                    batch_id: status.batch_id,
                    rows: taskRows.value.map(row => ({ ...row })),
                    completed: status.completed,
                    failed: status.failed,
                    status: status.status,
                })
                currentBatchId.value = null
            }
        } catch (e: unknown) {
            error.value = (e as Error).message
        }
    }

    /** 取消当前批次 */
    async function cancelBatch() {
        if (!currentBatchId.value) return

        try {
            const batchId = currentBatchId.value
            await getClient().cancelBatch(batchId)
            stopPolling()
            isBatchRunning.value = false
            currentBatchStatus.value = 'cancelled'

            // 将 pending/processing 行重置为 idle
            for (const row of taskRows.value) {
                if (row.status === 'pending' || row.status === 'processing') {
                    row.status = 'idle'
                }
            }

            saveLatestResultSnapshot({
                saved_at: new Date().toISOString(),
                batch_id: batchId,
                rows: taskRows.value.map(row => ({ ...row })),
                completed: completedCount.value,
                failed: failedCount.value,
                status: 'cancelled',
            })
            currentBatchId.value = null
        } catch (e: unknown) {
            error.value = (e as Error).message
        }
    }

    /** 启动轮询（每 1.5 秒） */
    function startPolling() {
        stopPolling()
        pollTimer = setInterval(pollBatchStatus, 1500)
    }

    /** 停止轮询 */
    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer)
            pollTimer = null
        }
    }

    /** 清空所有行 */
    function clearAll() {
        stopPolling()
        taskRows.value = []
        currentBatchId.value = null
        currentBatchStatus.value = 'done'
        isBatchRunning.value = false
        error.value = ''
    }

    /**
     * 从外部（如剧本页导出预检）批量导入分段行。
     * 发送到任务时由正式剧本页调用此方法填充任务表。
     */
    function importSegments(segments: { text: string; voice_id: string }[]) {
        for (const seg of segments) {
            taskRows.value.push({
                row_id: genRowId(),
                text: seg.text,
                voice_id: seg.voice_id,
                speed: 1.0,
                mode: 'zero_shot',
                instruct_text: '',
                seed: 42,
                status: 'idle',
                audio_url: null,
                duration_ms: null,
                error: null,
            })
        }
    }

    async function retryFailedRows(rowIds?: string[]) {
        if (isBatchRunning.value) {
            error.value = '当前批次仍在运行，无法重试失败行'
            return
        }
        const targetRows = taskRows.value.filter(row => {
            if (row.status !== 'failed') return false
            return !rowIds || rowIds.includes(row.row_id)
        })
        if (targetRows.length === 0) {
            error.value = '当前没有可重试的失败行'
            return
        }

        for (const row of targetRows) {
            row.status = 'idle'
            row.audio_url = null
            row.duration_ms = null
            row.error = null
        }

        await submitRows(targetRows)
    }

    function restoreLatestResult(mode: 'all' | 'failed') {
        const snapshot = latestResultSnapshot.value
        if (!snapshot) return false
        stopPolling()
        currentBatchId.value = null
        currentBatchStatus.value = snapshot.status
        isBatchRunning.value = false
        error.value = ''

        if (mode === 'all') {
            taskRows.value = snapshot.rows.map(row => normalizeRow(row))
            return true
        }

        taskRows.value = snapshot.rows
            .filter(row => row.status === 'failed')
            .map(row => normalizeRow({
                ...row,
                status: 'idle',
                audio_url: null,
                duration_ms: null,
                error: null,
            }))
        return true
    }

    watch(
        [taskRows, currentBatchId, isBatchRunning],
        () => {
            saveTaskPlanToStorage()
        },
        { deep: true },
    )

    loadLatestResultSnapshot()

    return {
        taskRows,
        currentBatchId,
        currentBatchStatus,
        isBatchRunning,
        error,
        latestResultSnapshot,
        importSummary,
        completedCount,
        failedCount,
        totalCount,
        validRows,
        serializeTaskPlan,
        restoreTaskPlan,
        saveTaskPlanToStorage,
        loadTaskPlanFromStorage,
        saveLatestResultSnapshot,
        loadLatestResultSnapshot,
        clearLatestResultSnapshot,
        restoreLatestResult,
        clearImportSummary,
        getClient,
        addRow,
        removeRow,
        updateRowText,
        updateRowVoice,
        updateRowSpeed,
        updateRowMode,
        updateRowInstructText,
        updateRowSeed,
        replaceRowsFromScript,
        appendRowsFromScript,
        setImportSummary,
        submitBatch,
        submitSingleRow,
        retryFailedRows,
        exportMergedAudio,
        pollBatchStatus,
        cancelBatch,
        startPolling,
        stopPolling,
        clearAll,
        importSegments,
    }
})
