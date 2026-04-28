<script setup lang="ts">
// Pro 缓存清理弹窗
// 调用 POST /api/v2/assets/audio/cleanup 端点

import { computed, onMounted, ref } from 'vue'
import { useSystemStore } from '@/stores/system'
import type { Asset } from '@/types'

const emit = defineEmits<{
    close: []
}>()

// 状态
const isCleaning = ref(false)
const isLoadingAssets = ref(false)
const unusedAssets = ref<Asset[]>([])
const result = ref<{
    requested: number
    deleted_count: number
    freed_mb: number
    skipped: Array<Record<string, unknown>>
} | null>(null)
const error = ref('')
const assetIds = computed(() => unusedAssets.value.map(asset => asset.asset_id))

async function loadUnusedAssets() {
    isLoadingAssets.value = true
    error.value = ''
    try {
        const systemStore = useSystemStore()
        const client = systemStore.getClient()
        unusedAssets.value = await client.listUnusedAssets()
    } catch (e: unknown) {
        error.value = (e as Error).message
    } finally {
        isLoadingAssets.value = false
    }
}

/** 执行清理 */
async function handleCleanup() {
    if (assetIds.value.length === 0) return
    isCleaning.value = true
    error.value = ''
    result.value = null

    try {
        const systemStore = useSystemStore()
        const client = systemStore.getClient()
        const res = await client.cleanupStorage(assetIds.value)
        result.value = res
        unusedAssets.value = []
    } catch (e: unknown) {
        error.value = (e as Error).message
    } finally {
        isCleaning.value = false
    }
}

onMounted(() => {
    void loadUnusedAssets()
})
</script>

<template>
    <Teleport to="body">
        <div class="cleanup-overlay" @click.self="emit('close')">
            <div class="cleanup-modal">
                <!-- 头部 -->
                <div class="cleanup-header">
                    <h3 class="cleanup-title">缓存清理</h3>
                    <button class="close-btn" @click="emit('close')">✕</button>
                </div>

                <!-- 内容 -->
                <div class="cleanup-body">
                    <template v-if="!result">
                        <p class="cleanup-desc">
                            将清理当前未被任何音色引用的参考音频资产，释放磁盘空间。此操作不可撤回。
                        </p>

                        <div v-if="isLoadingAssets" class="cleanup-loading">
                            正在扫描未引用资产...
                        </div>

                        <div v-else-if="unusedAssets.length === 0" class="cleanup-empty">
                            当前没有可清理的未引用资产。
                        </div>

                        <div v-else class="cleanup-preview">
                            <div class="preview-head">
                                <span>待清理 {{ unusedAssets.length }} 项</span>
                                <button class="refresh-link" @click="loadUnusedAssets">重新扫描</button>
                            </div>
                            <div class="preview-list">
                                <div v-for="asset in unusedAssets.slice(0, 8)" :key="asset.asset_id" class="preview-item">
                                    <code>{{ asset.asset_id }}</code>
                                    <span>{{ asset.note || `${asset.character || '未分类'} / ${asset.emotion || 'default'}` }}</span>
                                </div>
                            </div>
                            <div v-if="unusedAssets.length > 8" class="preview-more">
                                还有 {{ unusedAssets.length - 8 }} 项未展示
                            </div>
                        </div>

                        <!-- 错误提示 -->
                        <div v-if="error" class="cleanup-error">
                            {{ error }}
                        </div>
                    </template>

                    <!-- 清理结果 -->
                    <template v-else>
                        <div class="cleanup-result">
                            <div class="result-icon">完成</div>
                            <div class="result-stats">
                                <div class="result-item">
                                    <span class="result-label">已删除文件</span>
                                    <span class="result-value">{{ result.deleted_count }} 个</span>
                                </div>
                                <div class="result-item">
                                    <span class="result-label">请求项</span>
                                    <span class="result-value">{{ result.requested }} 个</span>
                                </div>
                                <div class="result-item">
                                    <span class="result-label">释放空间</span>
                                    <span class="result-value">{{ result.freed_mb }} MB</span>
                                </div>
                            </div>
                            <div v-if="result.skipped.length > 0" class="cleanup-skipped">
                                跳过 {{ result.skipped.length }} 项，请刷新后重试。
                            </div>
                        </div>
                    </template>
                </div>

                <!-- 底部 -->
                <div class="cleanup-footer">
                    <template v-if="!result">
                        <button class="cl-btn cl-btn-cancel" @click="emit('close')">取消</button>
                        <button
                            class="cl-btn cl-btn-confirm"
                            :disabled="isCleaning || isLoadingAssets || assetIds.length === 0"
                            @click="handleCleanup"
                        >
                            {{ isCleaning ? '清理中...' : '确认清理' }}
                        </button>
                    </template>
                    <template v-else>
                        <button class="cl-btn cl-btn-done" @click="emit('close')">完成</button>
                    </template>
                </div>
            </div>
        </div>
    </Teleport>
</template>

<style scoped>
.cleanup-overlay {
    position: fixed;
    inset: 0;
    background-color: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    backdrop-filter: blur(4px);
}

.cleanup-modal {
    background-color: #ffffff;
    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 16px;
    max-width: 400px;
    width: 90%;
    font-family: 'Be Vietnam Pro', 'Noto Sans SC', sans-serif;
    color: #1d1d1f;
    overflow: hidden;
    box-shadow: 0 20px 48px rgba(15, 23, 42, 0.18);
}

.cleanup-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.cleanup-title {
    font-size: 1.05rem;
    font-weight: 700;
    margin: 0;
}

.close-btn {
    background: none;
    border: none;
    color: #6e6e73;
    font-size: 1.1rem;
    cursor: pointer;
    padding: 4px;
    border-radius: 4px;
}

.close-btn:hover {
    color: #1d1d1f;
}

.cleanup-body {
    padding: 20px;
}

.cleanup-desc {
    font-size: 0.9rem;
    color: #4b5563;
    line-height: 1.6;
    margin: 0 0 14px;
}

.cleanup-loading,
.cleanup-empty {
    font-size: 0.85rem;
    color: #6e6e73;
    padding: 12px;
    border-radius: 8px;
    background-color: #f5f5f7;
}

.cleanup-preview {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.preview-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.82rem;
    color: #1d1d1f;
}

.refresh-link {
    border: none;
    background: none;
    color: #0071e3;
    cursor: pointer;
    font-size: 0.78rem;
}

.preview-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.preview-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 12px;
    border-radius: 8px;
    background-color: #f8fafc;
    font-size: 0.78rem;
    color: #334155;
}

.preview-item code {
    color: #1d1d1f;
}

.preview-more {
    font-size: 0.78rem;
    color: #6e6e73;
}

.cleanup-error {
    margin-top: 12px;
    font-size: 0.82rem;
    color: #EF4444;
    padding: 8px 12px;
    background-color: rgba(239, 68, 68, 0.1);
    border-radius: 6px;
}

/* 结果 */
.cleanup-result {
    text-align: center;
}

.result-icon {
    font-size: 2.5rem;
    margin-bottom: 16px;
}

.result-stats {
    display: flex;
    gap: 24px;
    justify-content: center;
    flex-wrap: wrap;
}

.result-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.result-label {
    font-size: 0.78rem;
    color: #6e6e73;
}

.result-value {
    font-size: 1.2rem;
    font-weight: 700;
    color: #22C55E;
}

.cleanup-skipped {
    margin-top: 14px;
    font-size: 0.78rem;
    color: #FBBF24;
}

/* 底部 */
.cleanup-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 16px 20px;
    border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.cl-btn {
    padding: 8px 18px;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    border: none;
    transition: all 0.2s;
    font-family: inherit;
}

.cl-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.cl-btn-cancel {
    background-color: #f3f4f6;
    color: #374151;
}

.cl-btn-cancel:hover {
    background-color: #e5e7eb;
}

.cl-btn-confirm {
    background-color: #ef4444;
    color: white;
}

.cl-btn-confirm:hover:not(:disabled) {
    background-color: #DC2626;
}

.cl-btn-done {
    background-color: rgba(34, 197, 94, 0.2);
    color: #22C55E;
    border: 1px solid rgba(34, 197, 94, 0.3);
}

.cl-btn-done:hover {
    background-color: rgba(34, 197, 94, 0.3);
}
</style>
