<script setup lang="ts">
// Pro 系统状态栏
// 显示联机状态、GPU 信息、模型控制按钮

import { ref } from 'vue'
import { useSystemStore } from '@/stores/system'
import ProStorageCleanup from './ProStorageCleanup.vue'
import { 
    TrashIcon, 
    ArrowPathIcon, 
    ArchiveBoxXMarkIcon, 
    ComputerDesktopIcon,
    ExclamationTriangleIcon
} from '@heroicons/vue/24/outline'

const systemStore = useSystemStore()

// 卸载确认弹窗
const showUnloadConfirm = ref(false)
// 缓存清理弹窗
const showCleanup = ref(false)
// 操作中状态
const actionMessage = ref('')

/** 重载模型 */
async function handleReload() {
    actionMessage.value = systemStore.isOnline ? '正在处理模型...' : '正在启动服务并加载模型...'
    try {
        const result = await systemStore.ensureRuntime()
        if (result.started_service) {
            actionMessage.value = '本地服务已启动，模型已就绪'
        } else if (result.status === 'already_loaded') {
            actionMessage.value = '模型已经处于加载状态'
        } else {
            actionMessage.value = '模型已就绪'
        }
        setTimeout(() => { actionMessage.value = '' }, 3000)
    } catch (error) {
        actionMessage.value = error instanceof Error ? error.message : '模型处理失败'
        setTimeout(() => { actionMessage.value = '' }, 3000)
    }
}

/** 卸载模型（需确认） */
async function handleUnload() {
    showUnloadConfirm.value = false
    actionMessage.value = '正在卸载模型...'
    try {
        const result = await systemStore.unloadModel()
        actionMessage.value = `已释放 ${result.vram_freed_mb} MB 显存`
        setTimeout(() => { actionMessage.value = '' }, 3000)
    } catch {
        actionMessage.value = '卸载失败'
        setTimeout(() => { actionMessage.value = '' }, 3000)
    }
}

/** 格式化显存 */
function formatVram(mb: number): string {
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
    return `${mb} MB`
}
</script>

<template>
    <div class="system-bar">
        <!-- 左侧：状态指示 -->
        <div class="system-bar-left">
            <!-- 联机状态灯 -->
            <div class="status-indicator">
                <span
                    class="status-dot"
                    :class="systemStore.isOnline ? 'status-online' : 'status-offline'"
                ></span>
                <span class="status-label">
                    {{ systemStore.isOnline ? '在线' : '离线' }}
                </span>
            </div>

            <!-- GPU 信息 -->
            <template v-if="systemStore.healthInfo">
                <div class="gpu-info">
                    <ComputerDesktopIcon class="sys-icon" />
                    <span class="gpu-name">{{ systemStore.healthInfo.gpu_name }}</span>
                    <span class="vram-usage">
                        {{ formatVram(systemStore.healthInfo.vram_used_mb || 0) }}
                        /
                        {{ formatVram(systemStore.healthInfo.vram_total_mb || 0) }}
                    </span>
                </div>

                <!-- 模型加载状态 -->
                <div class="divider"></div>
                <div class="model-status">
                    <span
                        class="model-dot"
                        :class="systemStore.healthInfo.model_loaded ? 'model-loaded' : 'model-unloaded'"
                    ></span>
                    <span>{{ systemStore.healthInfo.model_loaded ? '模型已加载' : '模型未加载' }}</span>
                </div>
            </template>

            <!-- 操作消息 -->
            <div v-if="actionMessage" class="action-message">
                {{ actionMessage }}
            </div>
        </div>

        <!-- 右侧：控制按钮 -->
        <div class="system-bar-right">
            <button
                class="sys-btn sys-btn-clean"
                @click="showCleanup = true"
                title="清理缓存"
            >
                <TrashIcon class="sys-icon" />
                <span>清理</span>
            </button>

            <button
                class="sys-btn sys-btn-reload"
                @click="handleReload"
                :disabled="systemStore.isLoading || (!systemStore.isOnline && !systemStore.canUseLocalBridge)"
            >
                <ArrowPathIcon class="sys-icon" :class="{ 'animate-spin': systemStore.isLoading }" />
                <span>{{ systemStore.primaryRuntimeActionLabel }}</span>
            </button>

            <button
                class="sys-btn sys-btn-unload"
                @click="showUnloadConfirm = true"
                :disabled="systemStore.isLoading"
            >
                <ArchiveBoxXMarkIcon class="sys-icon" />
                <span>卸载显存</span>
            </button>
        </div>
    </div>

    <!-- 卸载确认弹窗 -->
    <Teleport to="body">
        <div v-if="showUnloadConfirm" class="modal-overlay" @click.self="showUnloadConfirm = false">
            <div class="modal-content">
                <h3 class="modal-title">
                    <ExclamationTriangleIcon class="w-5 h-5 inline-block mr-2 text-red-500" />
                    确认卸载模型
                </h3>
                <p class="modal-desc">
                    卸载后将释放 GPU 显存，但需要重载模型后才能继续合成。确定要卸载吗？
                </p>
                <div class="modal-actions">
                    <button class="sys-btn sys-btn-cancel" @click="showUnloadConfirm = false">取消</button>
                    <button class="sys-btn sys-btn-danger" @click="handleUnload">确认卸载</button>
                </div>
            </div>
        </div>
    </Teleport>

    <!-- 缓存清理弹窗 -->
    <ProStorageCleanup v-if="showCleanup" @close="showCleanup = false" />
</template>

<style scoped>
.sys-icon {
    width: 16px;
    height: 16px;
    stroke-width: 2px;
}

.system-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 250, 252, 0.98) 100%);
    border: 1px solid var(--color-border);
    border-radius: 18px;
    padding: 14px 18px;
    gap: 12px;
    flex-wrap: wrap;
    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
}

.system-bar-left,
.system-bar-right {
    display: flex;
    align-items: center;
    gap: 8px 12px;
    flex-wrap: wrap;
}

.status-indicator,
.gpu-info,
.model-status {
    display: flex;
    align-items: center;
    gap: 6px;
}

.status-dot,
.model-dot {
    border-radius: 50%;
    display: inline-block;
}

.status-dot {
    width: 10px;
    height: 10px;
}

.model-dot {
    width: 8px;
    height: 8px;
}

.status-online {
    background-color: var(--pro-success);
    box-shadow: 0 0 8px rgba(34, 197, 94, 0.6);
    animation: pulse-green 2s infinite;
}

.status-offline { background-color: var(--pro-danger); }
.model-loaded { background-color: var(--pro-success); }
.model-unloaded { background-color: var(--pro-warning); }

@keyframes pulse-green {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

.status-label,
.model-status {
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--color-text-secondary);
}

.divider {
    width: 1px;
    height: 20px;
    background-color: var(--color-border);
}

.gpu-info { font-size: 0.82rem; }

.gpu-name {
    color: var(--pro-text);
    font-weight: 700;
}

.vram-usage {
    color: var(--pro-accent);
    font-weight: 600;
    font-size: 0.8rem;
}

.action-message {
    font-size: 0.8rem;
    color: var(--color-text-secondary);
    font-weight: 600;
    animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.sys-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 8px 14px;
    border-radius: 10px;
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid var(--color-border);
    transition: all 0.2s ease;
    font-family: inherit;
    white-space: nowrap;
    background: var(--color-surface);
    color: var(--color-text-secondary);
}

.sys-btn:disabled {
    opacity: 0.58;
    cursor: not-allowed;
}

.sys-btn-reload {
    background-color: #eef4ff;
    color: var(--color-primary);
    border-color: rgba(10, 132, 255, 0.2);
}

.sys-btn-reload:hover:not(:disabled) {
    background-color: #e4efff;
}

.sys-btn-unload {
    background-color: #fff1f2;
    color: var(--pro-danger);
    border-color: rgba(220, 38, 38, 0.2);
}

.sys-btn-unload:hover:not(:disabled) {
    background-color: #ffe4e6;
}

.sys-btn-clean,
.sys-btn-cancel {
    background-color: var(--color-surface-soft);
    color: var(--color-text-secondary);
}

.sys-btn-clean:hover:not(:disabled),
.sys-btn-cancel:hover {
    background-color: #e9eef5;
}

.sys-btn-danger {
    background-color: var(--pro-danger);
    color: white;
    border-color: rgba(220, 38, 38, 0.2);
}

.sys-btn-danger:hover {
    background-color: #b91c1c;
}

.modal-overlay {
    position: fixed;
    inset: 0;
    background-color: rgba(15, 23, 42, 0.48);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    backdrop-filter: blur(4px);
}

.modal-content {
    background-color: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 20px;
    padding: 24px;
    max-width: 420px;
    width: 90%;
    color: var(--color-text);
    box-shadow: 0 20px 40px rgba(15, 23, 42, 0.16);
}

.modal-title {
    font-size: 1.1rem;
    font-weight: 700;
    margin: 0 0 12px 0;
}

.modal-desc {
    font-size: 0.9rem;
    color: var(--color-text-secondary);
    line-height: 1.6;
    margin: 0 0 20px 0;
}

.modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
}
</style>
