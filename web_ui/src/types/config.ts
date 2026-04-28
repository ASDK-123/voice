// 配置数据模型

/** LLM 配置 */
export interface LlmConfig {
    id: string
    /** 配置名称 */
    name: string
    /** API 基础 URL（如 https://generativelanguage.googleapis.com/v1beta） */
    baseUrl: string
    /** 模型名称 */
    model: string
    /** API Key */
    key: string
    /** 额外 JSON 参数字符串 */
    params: string
}

/** TTS 配置 */
export interface TtsConfig {
    id: string
    /** 配置名称 */
    name: string
    /** CosyVoice v2 后端 URL（如 http://localhost:9880） */
    baseUrl: string
    /** 可选 API Key，用于受保护的 /api/v2/* 路由 */
    apiKey: string
}

/** 健康检查响应 */
export interface HealthResponse {
    status: string
    model_loaded?: boolean
}

/** 创建默认 LLM 配置 */
export function createDefaultLlmConfig(overrides: Partial<LlmConfig> = {}): LlmConfig {
    return {
        id: `llm_${Date.now()}`,
        name: '',
        baseUrl: '',
        model: '',
        key: '',
        params: '',
        ...overrides,
    }
}

/** 创建默认 TTS 配置 */
export function createDefaultTtsConfig(overrides: Partial<TtsConfig> = {}): TtsConfig {
    return {
        id: `tts_${Date.now()}`,
        name: '',
        baseUrl: 'http://localhost:9880',
        apiKey: '',
        ...overrides,
    }
}
