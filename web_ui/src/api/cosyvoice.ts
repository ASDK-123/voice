// CosyVoice v2 API 客户端
// 唯一的 TTS 后端集成层，仅支持 CosyVoice v2 协议

import type {
    Voice,
    Asset,
    LegacyImportExecuteResult,
    LegacyImportOptions,
    LegacyImportPreviewResult,
    ProBatchPayload,
    ProBatchStatus,
    ProHealthStatus,
    VoiceCreatePayload,
    AssetUploadMeta,
    SynthesizePayload,
} from '@/types'

/** 规范化 baseUrl：移除尾部斜杠 */
function normalizeUrl(url: string): string {
    return url.trim().replace(/\/+$/, '')
}

/** URL 拼接 */
function urlJoin(base: string, path: string): string {
    return `${normalizeUrl(base)}${path.startsWith('/') ? path : `/${path}`}`
}

/** 统一的 API 错误 */
export class ApiError extends Error {
    readonly status: number
    readonly code: string

    constructor(status: number, code: string, message: string) {
        super(message)
        this.name = 'ApiError'
        this.status = status
        this.code = code
    }
}

/** 解析 JSON 响应，统一错误处理 */
async function parseJsonResponse<T>(res: Response, path: string): Promise<T> {
    if (!res.ok) {
        const errText = await res.text().catch(() => '')
        throw new ApiError(
            res.status,
            `http_${res.status}`,
            `${path} 请求失败: HTTP ${res.status}${errText ? ` - ${errText}` : ''}`,
        )
    }
    return (await res.json()) as T
}

/**
 * CosyVoice v2 API 客户端
 *
 * 已移除 Legacy IndexTTS 兼容逻辑，仅保留 /api/v2/* 端点。
 */
export class CosyVoiceClient {
    private baseUrl: string
    private apiKey: string

    constructor(baseUrl: string, apiKey = '') {
        this.baseUrl = normalizeUrl(baseUrl)
        this.apiKey = apiKey
    }

    /** 构建通用请求头 */
    private headers(extra: Record<string, string> = {}): Record<string, string> {
        const h: Record<string, string> = { ...extra }
        if (this.apiKey) h['X-API-Key'] = this.apiKey
        return h
    }

    private async requestJson<T>(path: string, init?: RequestInit): Promise<T> {
        const res = await fetch(urlJoin(this.baseUrl, path), {
            ...init,
            headers: this.headers(init?.headers as Record<string, string> || {}),
        })
        return parseJsonResponse<T>(res, path)
    }

    // ───────── 健康检查 ─────────

    /** 检查后端是否就绪 */
    async health(): Promise<ProHealthStatus> {
        return this.requestJson<ProHealthStatus>('/api/v2/health')
    }

    // ───────── Voices CRUD ─────────

    /** 获取所有 Voice */
    async listVoices(): Promise<Voice[]> {
        const res = await fetch(urlJoin(this.baseUrl, '/api/v2/voices'), {
            headers: this.headers(),
        })
        const data = await parseJsonResponse<{ items: Voice[] }>(res, '/api/v2/voices')
        return data.items || []
    }

    /** 创建 Voice */
    async createVoice(payload: VoiceCreatePayload): Promise<Voice> {
        const res = await fetch(urlJoin(this.baseUrl, '/api/v2/voices'), {
            method: 'POST',
            headers: this.headers({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(payload),
        })
        return parseJsonResponse<Voice>(res, '/api/v2/voices')
    }

    /** 更新 Voice */
    async updateVoice(id: string, payload: Partial<VoiceCreatePayload>): Promise<Voice> {
        const path = `/api/v2/voices/${encodeURIComponent(id)}`
        const res = await fetch(urlJoin(this.baseUrl, path), {
            method: 'PUT',
            headers: this.headers({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(payload),
        })
        return parseJsonResponse<Voice>(res, path)
    }

    /** 删除 Voice */
    async deleteVoice(id: string): Promise<void> {
        const path = `/api/v2/voices/${encodeURIComponent(id)}`
        const res = await fetch(urlJoin(this.baseUrl, path), {
            method: 'DELETE',
            headers: this.headers(),
        })
        if (!res.ok) {
            const errText = await res.text().catch(() => '')
            throw new ApiError(res.status, 'delete_failed', `删除 voice 失败: ${errText}`)
        }
    }

    // ───────── Assets CRUD ─────────

    /** 获取 Asset 列表 */
    async listAssets(filter?: {
        character?: string
        emotion?: string
        kind?: string
    }): Promise<Asset[]> {
        const params = new URLSearchParams()
        if (filter?.character) params.set('character', filter.character)
        if (filter?.emotion) params.set('emotion', filter.emotion)
        if (filter?.kind) params.set('kind', filter.kind)
        const qs = params.toString()
        const path = `/api/v2/assets/audio${qs ? `?${qs}` : ''}`
        const res = await fetch(urlJoin(this.baseUrl, path), {
            headers: this.headers(),
        })
        const data = await parseJsonResponse<{ items: Asset[] }>(res, path)
        return data.items || []
    }

    /** 上传参考音频 Asset */
    async uploadAsset(file: File | Blob, meta: AssetUploadMeta = {}): Promise<Asset> {
        const formData = new FormData()
        formData.append('audio', file, (file as File).name || 'upload.wav')
        if (meta.character) formData.append('character', meta.character)
        if (meta.emotion) formData.append('emotion', meta.emotion)
        if (meta.note) formData.append('note', meta.note)

        const res = await fetch(urlJoin(this.baseUrl, '/api/v2/assets/audio'), {
            method: 'POST',
            headers: this.headers(), // 不设 Content-Type，让 FormData 自动设置 boundary
            body: formData,
        })
        return parseJsonResponse<Asset>(res, '/api/v2/assets/audio')
    }

    /** 获取 Asset 二进制内容 */
    async getAssetContent(id: string): Promise<Blob> {
        const path = `/api/v2/assets/audio/${encodeURIComponent(id)}/content`
        const res = await fetch(urlJoin(this.baseUrl, path), {
            headers: this.headers(),
        })
        if (!res.ok) {
            throw new ApiError(res.status, 'asset_not_found', `获取 asset 内容失败`)
        }
        return await res.blob()
    }

    /** 更新 Asset 元数据 */
    async updateAsset(id: string, payload: {
        note?: string
        transcript_text?: string
        prompt_text?: string
        character?: string
        emotion?: string
        language?: string
        linked?: boolean
    }): Promise<Asset> {
        const path = `/api/v2/assets/audio/${encodeURIComponent(id)}`
        const res = await fetch(urlJoin(this.baseUrl, path), {
            method: 'PUT',
            headers: this.headers({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(payload),
        })
        return parseJsonResponse<Asset>(res, path)
    }

    /** 删除 Asset */
    async deleteAsset(id: string): Promise<void> {
        const path = `/api/v2/assets/audio/${encodeURIComponent(id)}`
        const res = await fetch(urlJoin(this.baseUrl, path), {
            method: 'DELETE',
            headers: this.headers(),
        })
        if (!res.ok) {
            const errText = await res.text().catch(() => '')
            throw new ApiError(res.status, 'delete_failed', `删除 asset 失败: ${errText}`)
        }
    }

    /** 编译指定 Voice */
    async compileVoice(id: string, compileAll = false): Promise<{ status: string; voice_id: string; compiled: string[] }> {
        const path = `/api/v2/voices/${encodeURIComponent(id)}/compile${compileAll ? '?all=1' : ''}`
        const res = await fetch(urlJoin(this.baseUrl, path), {
            method: 'POST',
            headers: this.headers(),
        })
        return parseJsonResponse<{ status: string; voice_id: string; compiled: string[] }>(res, path)
    }

    async submitBatch(payload: ProBatchPayload): Promise<{ batch_id: string }> {
        return this.requestJson<{ batch_id: string }>('/api/v2/pro/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
    }

    async getBatchStatus(batchId: string): Promise<ProBatchStatus> {
        const data = await this.requestJson<ProBatchStatus>(`/api/v2/pro/batch/${encodeURIComponent(batchId)}`)
        if (Array.isArray(data.items)) {
            data.items = data.items.map(item => ({
                ...item,
                audio_url: item.audio_url && item.audio_url.startsWith('/')
                    ? `${this.baseUrl}${item.audio_url}`
                    : item.audio_url,
            }))
        }
        return data
    }

    async cancelBatch(batchId: string): Promise<void> {
        await this.requestJson(`/api/v2/pro/batch/${encodeURIComponent(batchId)}`, {
            method: 'DELETE',
        })
    }

    async unloadModel(): Promise<{ status: string; vram_freed_mb: number }> {
        return this.requestJson('/api/v2/pro/system/unload', { method: 'POST' })
    }

    async reloadModel(): Promise<{ status: string; model_name: string }> {
        return this.requestJson('/api/v2/pro/system/reload', { method: 'POST' })
    }

    async listUnusedAssets(): Promise<Asset[]> {
        const data = await this.requestJson<{ items?: Asset[] }>('/api/v2/assets/audio/unused')
        return data.items || []
    }

    async cleanupStorage(assetIds: string[], dryRun = false): Promise<{
        dry_run: boolean
        requested: number
        deleted_count: number
        freed_mb: number
        deleted_ids: string[]
        skipped: Array<Record<string, unknown>>
    }> {
        const raw = await this.requestJson<{
            deleted?: number
            bytes_reclaimed?: number
            deleted_ids?: string[]
            skipped?: Array<Record<string, unknown>>
            requested?: number
            dry_run?: boolean
        }>('/api/v2/assets/audio/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ asset_ids: assetIds, dry_run: dryRun }),
        })
        return {
            dry_run: raw.dry_run ?? dryRun,
            requested: raw.requested ?? assetIds.length,
            deleted_count: raw.deleted ?? 0,
            freed_mb: Math.round((raw.bytes_reclaimed ?? 0) / (1024 * 1024) * 100) / 100,
            deleted_ids: raw.deleted_ids || [],
            skipped: raw.skipped || [],
        }
    }

    async importLegacyVoices(
        file: File | Blob,
        options: LegacyImportOptions & { dryRun: boolean } = { dryRun: true },
    ): Promise<LegacyImportPreviewResult | LegacyImportExecuteResult> {
        const formData = new FormData()
        formData.append('file', file, (file as File).name || 'legacy_voices.json')
        formData.append('dry_run', options.dryRun ? '1' : '0')
        formData.append('default_language', options.default_language || 'zh')
        formData.append('create_emotion', options.create_emotion || 'default')
        formData.append('selection_policy', options.selection_policy || 'random_per_text')

        const path = '/api/v2/voices/import-legacy'
        const res = await fetch(urlJoin(this.baseUrl, path), {
            method: 'POST',
            headers: this.headers(),
            body: formData,
        })
        return parseJsonResponse<LegacyImportPreviewResult | LegacyImportExecuteResult>(res, path)
    }

    // ───────── 语音合成 ─────────

    /** 语音合成（返回音频 Blob） */
    async synthesize(payload: SynthesizePayload, signal?: AbortSignal): Promise<Blob> {
        const res = await fetch(urlJoin(this.baseUrl, '/api/v2/synthesize'), {
            method: 'POST',
            headers: this.headers({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                ...payload,
                response_format: payload.response_format || 'audio',
            }),
            signal,
        })
        if (!res.ok) {
            const errText = await res.text().catch(() => '')
            throw new ApiError(res.status, 'synthesis_failed', `语音合成失败: ${errText}`)
        }
        return await res.blob()
    }

    // ───────── 音频合并 ─────────

    /** 合并多段音频 */
    async merge(assetIds: string[]): Promise<Blob> {
        const res = await fetch(urlJoin(this.baseUrl, '/api/v2/merge'), {
            method: 'POST',
            headers: this.headers({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ asset_ids: assetIds }),
        })
        if (!res.ok) {
            const errText = await res.text().catch(() => '')
            throw new ApiError(res.status, 'merge_failed', `音频合并失败: ${errText}`)
        }
        return await res.blob()
    }

    async getAuthedAudioBlob(audioPath: string): Promise<Blob> {
        const url = audioPath.startsWith('http')
            ? audioPath
            : `${this.baseUrl}${audioPath}`
        const audioRes = await fetch(url, { headers: this.headers() })
        if (!audioRes.ok) {
            throw new ApiError(audioRes.status, `http_${audioRes.status}`, `音频加载失败: HTTP ${audioRes.status}`)
        }
        return await audioRes.blob()
    }

    async getAuthedAudioUrl(audioPath: string): Promise<string> {
        const blob = await this.getAuthedAudioBlob(audioPath)
        return URL.createObjectURL(blob)
    }
}
