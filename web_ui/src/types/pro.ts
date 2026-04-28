// Pro Workspace 专属类型定义
// 已与后端 V2 路由响应契约严格对齐

// ─── 行级别状态 ───
// 后端在行失败时写入 'failed'（api_v2_routes.py:883），前端统一使用该枚举。
export type ProRowStatus = 'idle' | 'pending' | 'processing' | 'done' | 'failed'

// ─── 批次级别状态 ───
// 后端批次完成后返回 'done' / 'cancelled'，兼容计划文档曾定义的 'completed'。
export type ProBatchState = 'processing' | 'done' | 'completed' | 'cancelled'
export type ProTaskRowFilter = 'all' | 'idle' | 'pending' | 'processing' | 'done' | 'failed'

/** 批量合成单行数据 */
export interface ProTaskRow {
    /** 前端生成的 UUID */
    row_id: string
    /** 合成文本 */
    text: string
    /** 选择的音色 ID（格式: "角色#情绪"） */
    voice_id: string
    /** 语速 0.5~2.0 */
    speed: number
    /** 推理模式 */
    mode: 'zero_shot' | 'instruct' | 'cross_lingual'
    /** 指令文本 */
    instruct_text: string
    /** 变体种子 */
    seed: number
    /** 行状态 */
    status: ProRowStatus
    /** 后端返回的音频 URL */
    audio_url: string | null
    /** 音频时长（毫秒） */
    duration_ms: number | null
    /** 错误信息 */
    error: string | null
}

/** 批量合成请求载荷 */
export interface ProBatchPayload {
    items: {
        row_id: string
        text: string
        voice_id: string
        speed: number
        mode: 'zero_shot' | 'instruct' | 'cross_lingual'
        instruct_text: string
        variation_seed: number
    }[]
}

/** 批量合成状态响应 */
export interface ProBatchStatus {
    batch_id: string
    total: number
    completed: number
    failed: number
    status: ProBatchState
    items: {
        row_id: string
        status: ProRowStatus
        audio_url: string | null
        duration_ms: number | null
        error: string | null
    }[]
}

/** Pro 任务计划快照 */
export interface ProTaskPlanSnapshot {
    version: '1.0'
    saved_at: string
    rows: ProTaskRow[]
    current_batch_id: string | null
    is_batch_running: boolean
}

export interface ProTaskResultSnapshot {
    saved_at: string
    batch_id: string | null
    rows: ProTaskRow[]
    completed: number
    failed: number
    status: ProBatchState
}

/**
 * 系统健康状态（增强版，含 GPU 信息）
 * 后端 GPU 字段在无显卡或降级时可能为 null（routes_v2_misc.py:56-62）。
 * `status` 在模型未加载时为 'degraded'，服务在线时为 'ok'。
 */
export interface ProHealthStatus {
    status: string
    model_loaded: boolean
    gpu_name: string | null
    vram_used_mb: number | null
    vram_total_mb: number | null
}

// ─── 音色与情感资产定义（Phase 2 铺垫） ───

/** 情感引用资产 */
export interface EmotionAsset {
    /** 资产 ID */
    asset_id: string
    /** 情感标签，如 "default", "happy" 等 */
    emotion: string
    /** 参考音频的相对路径 */
    audio_path: string
    /** 参考文本（用于语义匹配） */
    prompt_text: string
}

/** 角色配置 */
export interface ProCharacter {
    /** 角色名称 */
    name: string
    /** 该角色绑定的所有情感资产 */
    emotions: EmotionAsset[]
}
