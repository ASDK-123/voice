// CosyVoice v2 Voice / Asset 数据模型

/** CosyVoice v2 Voice（来自后端 /api/v2/voices） */
export interface Voice {
    /** voice_id，格式通常为 "角色#情绪" */
    name: string
    /** 角色名 */
    character: string
    /** 情绪标签 */
    emotion: string
    /** 合成模式 */
    mode: 'zero_shot' | 'instruct' | 'cross_lingual'
    /** 提示文本 */
    prompt_text: string
    /** 提示音频路径 */
    prompt_audio: string
    /** 参考音频选择策略 */
    selection_policy: 'random_per_text' | 'round_robin' | 'first'
    /** 绑定的 Asset ID 列表 */
    ref_asset_ids: string[]
    /** 显示颜色 */
    color?: string
    /** 指令文本（instruct 模式用） */
    instruct_text?: string
}

/** CosyVoice v2 Audio Asset（来自后端 /api/v2/assets/audio） */
export interface Asset {
    /** 唯一 ID */
    asset_id: string
    /** 服务端文件路径 */
    path: string
    /** 类型：ref=参考音频, output=合成输出 */
    kind: 'ref' | 'output'
    character?: string
    emotion?: string
    language?: string
    note?: string
    transcript_text?: string
    prompt_text?: string
    /** 是否被 voice 引用 */
    linked: boolean
    /** 引用计数 */
    ref_count: number
    created_at?: string
}

export type AssetTranscriptStatus = 'complete' | 'legacy_only' | 'missing'

export interface LegacyImportOptions {
    default_language?: string
    create_emotion?: string
    selection_policy?: string
}

export interface LegacyImportResult {
    imported_voices: number
    imported_assets: number
    skipped_assets: number
    errors: string[]
    dry_run: boolean
}

export type LegacyImportPreviewResult = LegacyImportResult

export type LegacyImportExecuteResult = LegacyImportResult

/** 创建 Voice 的请求载荷 */
export interface VoiceCreatePayload {
    name: string
    character: string
    emotion: string
    mode: string
    prompt_text: string
    selection_policy: string
    ref_asset_ids: string[]
    color?: string
}

/** Asset 上传元数据 */
export interface AssetUploadMeta {
    character?: string
    emotion?: string
    note?: string
}

/** 合成请求载荷 */
export interface SynthesizePayload {
    text: string
    voice_id?: string
    character?: string
    emotion?: string
    mode?: string
    prompt_audio_asset_id?: string
    prompt_text?: string
    response_format?: 'audio' | 'json'
}

/** Voice 表单状态 */
export interface VoiceForm {
    name: string
    character: string
    emotion: string
    mode: string
    prompt_text: string
    selection_policy: string
    ref_asset_ids: string[]
    color: string
}

/** 创建默认 VoiceForm */
export function createDefaultVoiceForm(): VoiceForm {
    return {
        name: '',
        character: '',
        emotion: 'default',
        mode: 'zero_shot',
        prompt_text: '',
        selection_policy: 'random_per_text',
        ref_asset_ids: [],
        color: '#6366f1',
    }
}
