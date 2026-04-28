// 项目核心 Store
// 剧本创作兼容域：负责原文、角色、AI 分析、单行生成与试听
// 不再承担正式批量任务流，批量提交、轮询与结果导出统一交由 pro_task / export 域

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Character, ScriptEntry, ScriptLine, ScriptTaskExportMode, ScriptTaskExportPreview } from '@/types'
import { createDefaultScriptLine, createDefaultBgmBlock, createDefaultCharacter, isDialogue } from '@/types'
import { getActiveTtsConnection, createCosyVoiceClientFromActiveConfig } from '@/api/client_factory'
import { useProVoiceStore } from './pro_voice'
import { useLlmStore } from './llm'
import { useAudioStore } from './audio'
import { useLibrariesStore } from './libraries'
import { buildAnalysisPrompt } from '@/utils/prompt'
import { useIndexedDB } from '@/composables/useIndexedDB'
import { useHistory } from '@/composables/useHistory'
import { watch } from 'vue'

// Undo/Redo 快照类型定义
interface ProjectSnapshot {
    rawScript: string
    rawAnalysisResult: string
    characters: Character[]
    scriptLines: ScriptEntry[]
}

export const useProjectStore = defineStore('project', () => {
    // ── 核心状态 ──
    const idb = useIndexedDB()
    const history = useHistory<ProjectSnapshot>({ capacity: 50 })

    /** 原始小说文本 */
    const rawScript = ref('')
    /** LLM 分析原始输出 */
    const rawAnalysisResult = ref('')
    /** 角色列表 */
    const characters = ref<Character[]>([])
    /** 脚本行列表（台词 + BGM） */
    const scriptLines = ref<ScriptEntry[]>([])
    /** 当前选中行索引 */
    const selectedLineIndex = ref(-1)

    // ── AI 分析状态 ──
    const isAnalyzing = ref(false)
    const analysisError = ref('')

    // ── TTS 生成状态 ──
    const isGeneratingAll = ref(false)
    const generateProgress = ref('')

    // ── 顺序播放状态 ──
    const isSequencePlaying = ref(false)
    const currentSequenceIndex = ref(-1)
    /** 当前正在试听的行 id */
    const auditioningId = ref('')

    // ── 计算属性 ──

    /** 从脚本行中提取所有可用角色名 */
    const availableRoles = computed(() => {
        const roles = new Set<string>()
        characters.value.forEach(c => roles.add(c.name))
        scriptLines.value.forEach(line => {
            if (isDialogue(line) && line.role) roles.add(line.role)
        })
        if (!roles.has('旁白')) roles.add('旁白')
        return Array.from(roles)
    })

    // ── 角色管理 ──

    /** 添加角色（去重） */
    function addCharacter(name: string) {
        if (!name.trim()) return
        const exists = characters.value.some(c => c.name === name.trim())
        if (exists) return
        characters.value.push(createDefaultCharacter(name.trim()))
    }

    /** 删除角色 */
    function deleteCharacter(id: string) {
        characters.value = characters.value.filter(c => c.id !== id)
    }

    // ── 脚本操作 ──

    /** 原文按行拆分为台词行 */
    function splitScript() {
        if (!rawScript.value.trim()) return
        const lines = rawScript.value.split('\n').filter(l => l.trim())
        scriptLines.value = lines.map(text =>
            createDefaultScriptLine({ text: text.trim() }),
        )
    }

    /** 添加一行台词 */
    function addDialogueBlock() {
        scriptLines.value.push(createDefaultScriptLine())
    }

    /** 添加 BGM 控制块 */
    function addBgmBlock() {
        scriptLines.value.push(createDefaultBgmBlock())
    }

    /** 移除脚本行 */
    function removeScriptLine(id: string) {
        scriptLines.value = scriptLines.value.filter(l => l.id !== id)
    }

    function moveLineUp(index: number) {
        if (index <= 0) return
        const arr = scriptLines.value
        const temp = arr[index]!
        arr[index] = arr[index - 1]!
        arr[index - 1] = temp
    }

    function moveLineDown(index: number) {
        const arr = scriptLines.value
        if (index >= arr.length - 1) return
        const temp = arr[index]!
        arr[index] = arr[index + 1]!
        arr[index + 1] = temp
    }

    function resolveTaskVoiceId(role: string, emotion: string): string | null {
        const proVoices = useProVoiceStore()
        const normalizedEmotion = (emotion || 'default').trim() || 'default'
        const normalizedRole = role.trim()
        if (!normalizedRole) return null

        const boundIdentity = characters.value.find(c => c.name === normalizedRole)?.voiceId?.trim() || ''
        const exactCandidates = [
            boundIdentity ? `${boundIdentity}#${normalizedEmotion}` : '',
            `${normalizedRole}#${normalizedEmotion}`,
        ].filter(Boolean)

        for (const candidate of exactCandidates) {
            if (proVoices.voices.some(voice => voice.name === candidate)) {
                return candidate
            }
        }

        const defaultCandidates = [
            boundIdentity ? `${boundIdentity}#default` : '',
            `${normalizedRole}#default`,
        ].filter(Boolean)

        for (const candidate of defaultCandidates) {
            if (proVoices.voices.some(voice => voice.name === candidate)) {
                return candidate
            }
        }

        if (boundIdentity) {
            const byBoundCharacter = proVoices.voices.find(voice => voice.character === boundIdentity)
            if (byBoundCharacter) return byBoundCharacter.name
        }

        const byCharacter = proVoices.voices.find(voice => voice.character === normalizedRole)
        if (byCharacter) return byCharacter.name

        return null
    }

    function buildTaskExportPreview(mode: ScriptTaskExportMode = 'replace'): ScriptTaskExportPreview {
        const rows: ScriptTaskExportPreview['rows'] = []
        const unresolved: ScriptTaskExportPreview['unresolved'] = []
        let dialogueCount = 0
        let skippedBgmCount = 0

        scriptLines.value.forEach((entry, index) => {
            if (!isDialogue(entry)) {
                skippedBgmCount += 1
                return
            }

            if (!entry.text.trim()) {
                return
            }

            dialogueCount += 1
            const voiceId = resolveTaskVoiceId(entry.role, entry.emotion)
            if (!voiceId) {
                unresolved.push({
                    line_id: entry.id,
                    line_index: index + 1,
                    role: entry.role,
                    emotion: entry.emotion,
                    text: entry.text.trim(),
                    reason: '未找到匹配音色，请先绑定角色音色或补齐正式音色配置。',
                })
                return
            }

            rows.push({
                line_id: entry.id,
                line_index: index + 1,
                role: entry.role,
                emotion: entry.emotion,
                text: entry.text.trim(),
                voice_id: voiceId,
            })
        })

        return {
            mode,
            dialogue_count: dialogueCount,
            skipped_bgm_count: skippedBgmCount,
            resolved_count: rows.length,
            unresolved_count: unresolved.length,
            can_export: rows.length > 0 && unresolved.length === 0,
            rows,
            unresolved,
        }
    }

    // ── P0-1: AI 分析结果 → 脚本解析 ──

    /**
     * 解析 AI 输出的 JSON，转换为 scriptLines 并自动提取角色
     * 兼容原项目 JSON 格式（dialogue / bgm）
     */
    function parseAnalysisResult(rawJson: string): boolean {
        try {
            // 提取 JSON 数组（兼容代码块包裹）
            const jsonMatch = rawJson.match(/\[\s*\{[\s\S]*\}\s*\]/)
            const jsonStr = jsonMatch
                ? jsonMatch[0]
                : rawJson.replace(/```json/g, '').replace(/```/g, '').trim()

            const parsed = JSON.parse(jsonStr)
            if (!Array.isArray(parsed)) {
                analysisError.value = '解析结果不是有效的 JSON 数组'
                return false
            }

            // 转换为 scriptLines
            const newLines: ScriptEntry[] = []
            const newRoles = new Set<string>()

            for (const item of parsed) {
                if (item.type === 'bgm') {
                    // BGM 控制块
                    newLines.push(createDefaultBgmBlock({
                        action: item.action || 'play',
                        bgmName: item.name || '',
                        volume: item.volume ?? 0.4,
                    }))
                } else {
                    // 台词行（兼容 role_name / role 两种字段名）
                    const role = item.role_name || item.role || '旁白'
                    const text = item.text_content || item.text || ''
                    if (role && role !== '旁白') newRoles.add(role)

                    newLines.push(createDefaultScriptLine({
                        role,
                        text,
                        emotion: item.emotion || 'default',
                        break_duration: item.break_duration ?? 0,
                        filter: item.filter || '',
                        sfx: Array.isArray(item.sfx) ? item.sfx : [],
                    }))
                }
            }

            // 更新脚本行
            scriptLines.value = newLines

            // 自动添加新角色
            newRoles.forEach(name => addCharacter(name))
            // 确保"旁白"存在
            addCharacter('旁白')

            analysisError.value = ''
            return true
        } catch (e: unknown) {
            const err = e as Error
            analysisError.value = `JSON 解析失败: ${err.message}`
            return false
        }
    }

    /**
     * 一键 AI 分析脚本
     * 自动构建 Prompt → 调用 LLM → 解析结果为 scriptLines
     */
    async function analyzeScript(): Promise<boolean> {
        const llm = useLlmStore()
        const libs = useLibrariesStore()

        if (!rawScript.value.trim()) {
            analysisError.value = '请先输入小说原文'
            return false
        }
        if (!llm.currentConfig) {
            analysisError.value = '请先在 LLM 配置中选择一个配置'
            return false
        }

        isAnalyzing.value = true
        analysisError.value = ''

        try {
            // 构建 Prompt
            const template = llm.useCustomPrompt && llm.customPromptTemplate.trim()
                ? llm.customPromptTemplate
                : undefined

            // P6: 从 VoicesStore 动态收集情绪标签
            const voices = useProVoiceStore()
            const uniqueEmotions = [...new Set(
                voices.voices.map(v => v.emotion).filter(Boolean)
            )]

            llm.prompt = buildAnalysisPrompt({
                rawScript: rawScript.value,
                sfxLibrary: libs.sfxLibrary,
                bgmLibrary: libs.bgmLibrary,
                filterLibrary: libs.filterLibrary,
                emotionCatalog: uniqueEmotions.length > 0 ? uniqueEmotions : undefined,
                customTemplate: template,
            })

            // 发送给 LLM
            await llm.send()

            // 保存原始输出
            rawAnalysisResult.value = llm.result

            // 解析结果
            if (llm.result) {
                return parseAnalysisResult(llm.result)
            } else if (llm.error) {
                analysisError.value = llm.error
                return false
            }
            return false
        } finally {
            isAnalyzing.value = false
        }
    }

    // ── P0-2: 单行 TTS 音频生成 ──

    /**
     * 为单行台词生成 TTS 音频
     * 根据角色的 Voice 绑定自动选择音色
     */
    async function generateLineAudio(line: ScriptLine): Promise<boolean> {
        const voices = useProVoiceStore()
        const audioStore = useAudioStore()

        if (!line.text.trim()) return false

        line.isGenerating = true

        try {
            getActiveTtsConnection()
            const client = createCosyVoiceClientFromActiveConfig()

            // 查找角色绑定的 voiceId (可能只是 Identity 如 "胡桃"，也可能是具体 ID "胡桃#default")
            const char = characters.value.find(c => c.name === line.role)
            const boundIdentity = char?.voiceId || ''

            // 无论绑定的是什么，都尝试结合当前情绪查找最佳匹配
            // 如果 boundIdentity 是 "胡桃"，pickVoiceId("胡桃", "happy") 会返回 "胡桃#happy"
            // 如果 boundIdentity 是空，pickVoiceId(line.role, "happy") 会尝试用角色名查找
            let voiceId = resolveTaskVoiceId(boundIdentity || line.role, line.emotion)
            if (!voiceId && boundIdentity && voices.voices.some(voice => voice.name === boundIdentity)) {
                voiceId = boundIdentity
            }

            // 构建合成请求
            const blob = await client.synthesize({
                text: line.text,
                voice_id: voiceId || undefined,
            })

            // P7.2: Use AudioStore logic
            const audioId = line.audioId || crypto.randomUUID()
            await audioStore.registerAudio(audioId, blob)

            line.audioId = audioId
            // line.audioUrl is no longer the source of truth, but we can set it for legacy compatibility if needed.
            // But better to rely on ScriptRow watching audioId.
            return true
        } catch (e: unknown) {
            const err = e as Error
            console.error('TTS 生成失败:', err.message)
            analysisError.value = `TTS 生成失败 [${line.role}]: ${err.message}`
            return false
        } finally {
            line.isGenerating = false
        }
    }

    /** 批量生成所有台词音频 */
    async function generateAllAudio() {
        isGeneratingAll.value = true
        const dialogueLines = scriptLines.value.filter(isDialogue)
        let done = 0

        try {
            for (const line of dialogueLines) {
                if (!line.text.trim()) {
                    done++
                    continue
                }
                generateProgress.value = `生成中 ${done + 1}/${dialogueLines.length}`
                await generateLineAudio(line)
                done++
            }
            generateProgress.value = `完成 ${done}/${dialogueLines.length}`
        } finally {
            isGeneratingAll.value = false
        }
    }

    // ── P0: 单行播放 ──

    let currentAudio: HTMLAudioElement | null = null

    /** 播放/停止单行音频 */
    function playLineAudio(line: ScriptLine) {
        // 如果正在播放同一行，停止
        if (auditioningId.value === line.id) {
            stopAudio()
            return
        }
        stopAudio()

        stopAudio()

        // P7.2: Resolve URL from AudioStore
        const audioStore = useAudioStore()
        // If line has no audioId, try legacy audioUrl or return
        if (!line.audioId && !line.audioUrl) return

        let url = line.audioUrl
        if (line.audioId) {
            // We need to await, but playLineAudio is synchronous in signature?
            // It's okay to make it async or handle promise.
            // But let's check if we can get it sync from cache.
            // Helper function should handle it.
            // For now, let's assume async is fine for play action.
            audioStore.getAudioUrl(line.audioId).then(res => {
                if (res) {
                    currentAudio = new Audio(res)
                    currentAudio.volume = line.dialogueVolume ?? 1.0
                    auditioningId.value = line.id

                    const trimStartRatio = line.trimStart || 0
                    const trimEndRatio = line.trimEnd || 1

                    currentAudio.onloadedmetadata = () => {
                        if (!currentAudio) return
                        if (isFinite(currentAudio.duration)) {
                            currentAudio.currentTime = currentAudio.duration * trimStartRatio
                        }
                    }

                    currentAudio.ontimeupdate = () => {
                        if (!currentAudio) return
                        const duration = currentAudio.duration
                        if (isFinite(duration)) {
                            const endTime = duration * trimEndRatio
                            if (currentAudio.currentTime >= endTime) {
                                stopAudio()
                            }
                        }
                    }

                    currentAudio.onended = () => {
                        auditioningId.value = ''
                        currentAudio = null
                    }
                    currentAudio.play()
                }
            })
            return
        }

        // Legacy fallback
        currentAudio = new Audio(url)
        currentAudio.volume = line.dialogueVolume ?? 1.0
        auditioningId.value = line.id

        // Apply trim settings
        const trimStartRatio = line.trimStart || 0
        const trimEndRatio = line.trimEnd || 1

        currentAudio.onloadedmetadata = () => {
            if (!currentAudio) return
            if (isFinite(currentAudio.duration)) {
                currentAudio.currentTime = currentAudio.duration * trimStartRatio
            }
        }

        currentAudio.ontimeupdate = () => {
            if (!currentAudio) return
            const duration = currentAudio.duration
            if (isFinite(duration)) {
                const endTime = duration * trimEndRatio
                if (currentAudio.currentTime >= endTime) {
                    stopAudio()
                }
            }
        }

        currentAudio.onended = () => {
            auditioningId.value = ''
            currentAudio = null
        }
        currentAudio.play()
    }

    /** 停止当前播放 */
    function stopAudio() {
        if (currentAudio) {
            currentAudio.pause()
            currentAudio.currentTime = 0
            currentAudio = null
        }
        auditioningId.value = ''
    }

    /** 顺序播放所有台词 */
    async function playSequentially(startIndex = 0) {
        isSequencePlaying.value = true

        try {
            for (let i = startIndex; i < scriptLines.value.length; i++) {
                if (!isSequencePlaying.value) break

                const line = scriptLines.value[i]!
                currentSequenceIndex.value = i
                selectedLineIndex.value = i

                if (isDialogue(line) && line.audioUrl) {
                    await new Promise<void>((resolve) => {
                        stopAudio()
                        currentAudio = new Audio(line.audioUrl)
                        currentAudio.volume = line.dialogueVolume ?? 1.0
                        auditioningId.value = line.id
                        currentAudio.onended = () => {
                            auditioningId.value = ''
                            currentAudio = null
                            // 停顿
                            const pause = line.break_duration || 0
                            if (pause > 0) {
                                setTimeout(resolve, pause * 1000)
                            } else {
                                resolve()
                            }
                        }
                        currentAudio.onerror = () => resolve()
                        currentAudio.play().catch(() => resolve())
                    })
                }
            }
        } finally {
            isSequencePlaying.value = false
            currentSequenceIndex.value = -1
        }
    }

    /** 停止顺序播放 */
    function stopSequentially() {
        isSequencePlaying.value = false
        stopAudio()
        currentSequenceIndex.value = -1
    }

    /** 序列化为可存储的快照（剥离运行时字段） */
    function toSerializable() {
        return {
            rawScript: rawScript.value,
            rawAnalysisResult: rawAnalysisResult.value,
            characters: characters.value,
            scriptLines: scriptLines.value.map(line => {
                if (isDialogue(line)) {
                    // 剥离运行时字段
                    const { audioUrl: _a, isGenerating: _g, ...rest } = line
                    return rest
                }
                return line
            }),
        }
    }

    // ── P5: Undo/Redo 集成 ──

    /** 防抖定时器 ID */
    let snapshotTimer: ReturnType<typeof setTimeout> | null = null
    const SNAPSHOT_DEBOUNCE_MS = 1000

    /** 手动提交快照（重大操作如删除行、批量处理时调用） */
    function commitSnapshot(): void {
        if (history.isUndoRedoing.value) return
        if (snapshotTimer) {
            clearTimeout(snapshotTimer)
            snapshotTimer = null
        }
        history.push(toSerializable() as ProjectSnapshot)
    }

    /** 撤销 */
    function undo(): void {
        const snapshot = history.undo()
        if (!snapshot) return
        restoreSnapshot(snapshot)
    }

    /** 重做 */
    function redo(): void {
        const snapshot = history.redo()
        if (!snapshot) return
        restoreSnapshot(snapshot)
    }

    /** 从快照恢复状态 */
    function restoreSnapshot(snapshot: ProjectSnapshot): void {
        rawScript.value = snapshot.rawScript
        rawAnalysisResult.value = snapshot.rawAnalysisResult
        characters.value = snapshot.characters
        scriptLines.value = snapshot.scriptLines
    }

    // ── 初始化：从 IndexedDB 恢复数据 ──

    /** 从 IndexedDB 恢复项目和库数据 */
    async function initFromDB() {
        try {
            await idb.openDB()

            // 1. 恢复项目快照（含库元数据）
            const snapshot = await idb.loadProject()
            if (snapshot) {
                rawScript.value = snapshot.rawScript || ''
                rawAnalysisResult.value = snapshot.rawAnalysisResult || ''
                characters.value = snapshot.characters || []
                scriptLines.value = snapshot.scriptLines || []

                // 恢复库元数据
                const libs = useLibrariesStore()
                const voices = useProVoiceStore()

                if ((snapshot as any).sfxLibrary) libs.sfxLibrary = (snapshot as any).sfxLibrary
                if ((snapshot as any).bgmLibrary) libs.bgmLibrary = (snapshot as any).bgmLibrary
                if ((snapshot as any).timbres) libs.timbres = (snapshot as any).timbres
                if ((snapshot as any).filterLibrary) libs.filterLibrary = (snapshot as any).filterLibrary
                if ((snapshot as any).v2Voices) {
                    voices.voices = (snapshot as any).v2Voices
                }
                if ((snapshot as any).v2Assets) {
                    voices.assets = (snapshot as any).v2Assets
                }

                // 2. 恢复素材文件 Blob 到 localFileMap
                await libs.restoreAssetsFromDB()

                console.log('[Project] 数据已从 IndexedDB 恢复')

                // 初始化历史快照
                history.init(toSerializable() as ProjectSnapshot)
            }
        } catch (e) {
            console.error('[Project] 初始化恢复失败:', e)
        }
    }

    // 立即执行初始化
    initFromDB()

    // ── 自动保存 + 历史快照监听 ──
    // 注意：必须监听所有需要持久化的状态，包括资源库数据
    const libs = useLibrariesStore()
    const voices = useProVoiceStore()

    watch(
        [
            rawScript,
            characters,
            scriptLines,
            // 资源库状态（之前缺失，导致 BGM/SFX 刷新后丢失）
            () => libs.sfxLibrary,
            () => libs.bgmLibrary,
            () => libs.timbres,
            () => libs.filterLibrary,
        ],
        () => {
            // 自动保存到 IndexedDB
            if (!idb.isReady) idb.openDB()

            const snapshot = JSON.parse(JSON.stringify({
                ...toSerializable(),
                sfxLibrary: libs.sfxLibrary,
                bgmLibrary: libs.bgmLibrary,
                timbres: libs.timbres,
                filterLibrary: libs.filterLibrary,
                v2Voices: voices.voices,
                v2Assets: voices.assets,
            }))
            idb.triggerAutoSave(snapshot)

            // 防抖记录历史快照（避免每次按键都记录）
            if (!history.isUndoRedoing.value) {
                if (snapshotTimer) clearTimeout(snapshotTimer)
                snapshotTimer = setTimeout(() => {
                    history.push(toSerializable() as ProjectSnapshot)
                }, SNAPSHOT_DEBOUNCE_MS)
            }
        },
        { deep: true },
    )


    return {
        // 核心状态
        rawScript,
        rawAnalysisResult,
        characters,
        scriptLines,
        selectedLineIndex,
        availableRoles,
        // AI 分析
        isAnalyzing,
        analysisError,
        // TTS 生成
        isGeneratingAll,
        generateProgress,
        // 播放
        isSequencePlaying,
        currentSequenceIndex,
        auditioningId,
        // 角色管理
        addCharacter,
        deleteCharacter,
        // 脚本操作
        splitScript,
        addDialogueBlock,
        addBgmBlock,
        removeScriptLine,
        moveLineUp,
        moveLineDown,
        buildTaskExportPreview,
        // P0 新增
        parseAnalysisResult,
        analyzeScript,
        generateLineAudio,
        generateAllAudio,
        playLineAudio,
        stopAudio,
        playSequentially,
        stopSequentially,
        toSerializable,
        // P5: Undo/Redo
        canUndo: history.canUndo,
        canRedo: history.canRedo,
        undo,
        redo,
        commitSnapshot,
    }
})
