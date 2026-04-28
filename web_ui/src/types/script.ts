// 脚本数据模型

/** 音效挂载 */
export interface SfxAttachment {
    /** 音效库中的名称 */
    name: string
    /** 0~1 占音频总时长的比例位置 */
    position: number
}

/** 台词行（核心数据单元） */
export interface ScriptLine {
    id: string
    type: 'dialogue'
    /** 角色名（默认 "旁白"） */
    role: string
    /** 情绪标签 */
    emotion: string
    /** 台词文本 */
    text: string
    /** 绑定的滤波器名称（空串=无） */
    filter: string

    /** 音效挂载列表 */
    sfx: SfxAttachment[]

    /** 音频剪辑起始比例 0~1 */
    trimStart: number
    /** 音频剪辑结束比例 0~1 */
    trimEnd: number

    /** 台词音量（默认 1.0） */
    dialogueVolume: number
    /** 音效音量（默认 0.5） */
    sfxVolume: number

    /** 行后停顿时长（秒） */
    break_duration: number

    // ── 运行时状态（不序列化到 DB） ──
    /** 音频 ObjectURL */
    // P7.2: Audio Resource Management
    audioId?: string // UUID pointing to AudioStore (IDB/LRU)
    audioUrl?: string // Blob URL (Transient, managed by ScriptRow)
    /** 是否正在生成中 */
    isGenerating: boolean
}

/** BGM 控制块 */
export interface BgmBlock {
    id: string
    type: 'bgm'
    action: 'play' | 'stop'
    /** BGM 库中的名称 */
    bgmName: string
    /** 播放音量（默认 0.4） */
    volume: number
}

/** 联合类型：脚本中的任意一行 */
export type ScriptEntry = ScriptLine | BgmBlock

export type ScriptTaskExportMode = 'replace' | 'append'

export interface ScriptTaskExportRow {
    line_id: string
    line_index: number
    role: string
    emotion: string
    text: string
    voice_id: string
}

export interface ScriptTaskExportIssue {
    line_id: string
    line_index: number
    role: string
    emotion: string
    text: string
    reason: string
}

export interface ScriptTaskExportPreview {
    mode: ScriptTaskExportMode
    dialogue_count: number
    skipped_bgm_count: number
    resolved_count: number
    unresolved_count: number
    can_export: boolean
    rows: ScriptTaskExportRow[]
    unresolved: ScriptTaskExportIssue[]
}

/** 类型守卫：是否为台词行 */
export function isDialogue(entry: ScriptEntry): entry is ScriptLine {
    return entry.type === 'dialogue'
}

/** 类型守卫：是否为 BGM 控制块 */
export function isBgm(entry: ScriptEntry): entry is BgmBlock {
    return entry.type === 'bgm'
}

/** 创建一个默认台词行 */
export function createDefaultScriptLine(overrides: Partial<ScriptLine> = {}): ScriptLine {
    return {
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        type: 'dialogue',
        role: '旁白',
        emotion: 'default',
        text: '',
        filter: '',
        sfx: [],
        trimStart: 0,
        trimEnd: 1,
        dialogueVolume: 1.0,
        sfxVolume: 0.5,
        break_duration: 0.5,
        audioUrl: '',
        isGenerating: false,
        ...overrides,
    }
}

/** 创建一个默认 BGM 控制块 */
export function createDefaultBgmBlock(overrides: Partial<BgmBlock> = {}): BgmBlock {
    return {
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        type: 'bgm',
        action: 'play',
        bgmName: '',
        volume: 0.4,
        ...overrides,
    }
}
