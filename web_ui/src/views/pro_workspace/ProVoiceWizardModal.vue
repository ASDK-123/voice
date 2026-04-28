<script setup lang="ts">
// Pro 新建音色向导弹窗
// 简化版音色创建表单

import { ref, watch } from 'vue'
import { useProVoiceStore, type ProVoiceItem } from '@/stores/pro_voice'

const emit = defineEmits<{
    close: []
}>()

const props = defineProps<{
    initialVoice?: ProVoiceItem | null
}>()

const voiceStore = useProVoiceStore()

// 表单数据
const form = ref({
    character: '',
    emotion: 'default',
    mode: 'zero_shot',
    color: '#F97316',
    prompt_text: '',
})

// 预设颜色
const presetColors = [
    '#F97316', '#EAB308', '#22C55E', '#14B8A6',
    '#3B82F6', '#6366F1', '#A855F7', '#EC4899',
    '#EF4444', '#F59E0B',
]

// 状态
const isSubmitting = ref(false)
const errorMessage = ref('')

watch(
    () => props.initialVoice,
    voice => {
        form.value = {
            character: voice?.character || '',
            emotion: voice?.emotion || 'default',
            mode: voice?.mode || 'zero_shot',
            color: voice?.color || '#F97316',
            prompt_text: voice?.prompt_text || '',
        }
    },
    { immediate: true },
)

/** 提交创建（真实后端 CRUD） */
async function handleSubmit() {
    const character = form.value.character.trim()
    const emotion = form.value.emotion.trim() || 'default'

    if (!character) {
        errorMessage.value = '请输入角色名'
        return
    }

    isSubmitting.value = true
    errorMessage.value = ''

    try {
        const voiceId = `${character}#${emotion}`
        const payload = {
            name: voiceId,
            character,
            emotion,
            mode: form.value.mode,
            prompt_text: form.value.prompt_text.trim(),
            selection_policy: props.initialVoice?.selection_policy || 'random_per_text',
            ref_asset_ids: props.initialVoice?.ref_asset_ids || [],
            color: form.value.color,
        }

        if (props.initialVoice?.name) {
            await voiceStore.updateVoice(props.initialVoice.name, payload)
        } else {
            await voiceStore.createVoice(payload)
        }

        emit('close')
    } catch (e: unknown) {
        errorMessage.value = (e as Error).message
    } finally {
        isSubmitting.value = false
    }
}
</script>

<template>
    <Teleport to="body">
        <div class="wizard-overlay" @click.self="emit('close')">
            <div class="wizard-modal">
                <!-- 头部 -->
                <div class="wizard-header">
                    <h3 class="wizard-title">{{ props.initialVoice ? '编辑音色' : '新建音色' }}</h3>
                    <button class="close-btn" @click="emit('close')">✕</button>
                </div>

                <!-- 表单 -->
                <div class="wizard-body">
                    <!-- 角色名 -->
                    <div class="form-field">
                        <label class="field-label">角色名称</label>
                        <input
                            v-model="form.character"
                            type="text"
                            placeholder="例如：胡桃、钟离..."
                            class="field-input"
                        />
                    </div>

                    <!-- 情绪 -->
                    <div class="form-field">
                        <label class="field-label">情绪标签</label>
                        <input
                            v-model="form.emotion"
                            type="text"
                            placeholder="例如：开心、中立..."
                            class="field-input"
                        />
                    </div>

                    <!-- 合成模式 -->
                    <div class="form-field">
                        <label class="field-label">合成模式</label>
                        <select v-model="form.mode" class="field-select">
                            <option value="zero_shot">Zero Shot</option>
                            <option value="instruct">Instruct</option>
                            <option value="cross_lingual">Cross Lingual</option>
                        </select>
                    </div>

                    <div class="form-field">
                        <label class="field-label">Prompt 文本</label>
                        <textarea
                            v-model="form.prompt_text"
                            placeholder="用于零样本/参考音频匹配的提示文本"
                            class="field-textarea"
                            rows="3"
                        ></textarea>
                    </div>

                    <!-- 颜色选择 -->
                    <div class="form-field">
                        <label class="field-label">标记颜色</label>
                        <div class="color-picker">
                            <div
                                v-for="c in presetColors"
                                :key="c"
                                class="color-swatch"
                                :class="{ 'color-active': form.color === c }"
                                :style="{ backgroundColor: c }"
                                @click="form.color = c"
                            ></div>
                        </div>
                    </div>

                    <!-- 预览 -->
                    <div class="form-preview">
                        <span class="preview-label">生成 ID：</span>
                        <code class="preview-id">
                            {{ form.character || '角色' }}#{{ form.emotion.trim() || 'default' }}
                        </code>
                    </div>

                    <!-- 错误提示 -->
                    <div v-if="errorMessage" class="form-error">
                        {{ errorMessage }}
                    </div>
                </div>

                <!-- 底部操作 -->
                <div class="wizard-footer">
                    <button class="wiz-btn wiz-btn-cancel" @click="emit('close')">取消</button>
                    <button
                        class="wiz-btn wiz-btn-submit"
                        :disabled="isSubmitting"
                        @click="handleSubmit"
                    >
                        {{ isSubmitting ? (props.initialVoice ? '保存中...' : '创建中...') : (props.initialVoice ? '保存' : '创建') }}
                    </button>
                </div>
            </div>
        </div>
    </Teleport>
</template>

<style scoped>
.wizard-overlay {
    position: fixed;
    inset: 0;
    background-color: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    backdrop-filter: blur(4px);
}

.wizard-modal {
    background-color: #1E1B4B;
    border: 1px solid #312E81;
    border-radius: 16px;
    max-width: 460px;
    width: 90%;
    font-family: 'Be Vietnam Pro', 'Noto Sans SC', sans-serif;
    color: #E2E8F0;
    overflow: hidden;
}

.wizard-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid #312E81;
}

.wizard-title {
    font-size: 1.05rem;
    font-weight: 700;
    margin: 0;
}

.close-btn {
    background: none;
    border: none;
    color: #94A3B8;
    font-size: 1.1rem;
    cursor: pointer;
    padding: 4px;
    border-radius: 4px;
    transition: color 0.15s;
}

.close-btn:hover {
    color: #E2E8F0;
}

.wizard-body {
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

/* 表单字段 */
.form-field {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.field-label {
    font-size: 0.82rem;
    font-weight: 600;
    color: #94A3B8;
}

.field-input {
    padding: 9px 12px;
    border-radius: 8px;
    border: 1px solid #312E81;
    background-color: rgba(15, 15, 35, 0.6);
    color: #E2E8F0;
    font-size: 0.9rem;
    outline: none;
    transition: border-color 0.2s;
    font-family: inherit;
}

.field-input::placeholder {
    color: #64748B;
}

.field-input:focus {
    border-color: #F97316;
}

.field-select {
    padding: 9px 12px;
    border-radius: 8px;
    border: 1px solid #312E81;
    background-color: rgba(15, 15, 35, 0.6);
    color: #E2E8F0;
    font-size: 0.9rem;
    outline: none;
    font-family: inherit;
    cursor: pointer;
}

.field-textarea {
    padding: 9px 12px;
    border-radius: 8px;
    border: 1px solid #312E81;
    background-color: rgba(15, 15, 35, 0.6);
    color: #E2E8F0;
    font-size: 0.9rem;
    outline: none;
    transition: border-color 0.2s;
    font-family: inherit;
    resize: vertical;
}

.field-textarea::placeholder {
    color: #64748B;
}

.field-textarea:focus {
    border-color: #F97316;
}

/* 颜色选择器 */
.color-picker {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.color-swatch {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.15s;
    border: 2px solid transparent;
}

.color-swatch:hover {
    transform: scale(1.15);
}

.color-swatch.color-active {
    border-color: white;
    box-shadow: 0 0 8px rgba(255, 255, 255, 0.3);
}

/* 预览 */
.form-preview {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    background-color: rgba(15, 15, 35, 0.4);
    border-radius: 8px;
}

.preview-label {
    font-size: 0.8rem;
    color: #94A3B8;
}

.preview-id {
    font-size: 0.85rem;
    color: #F97316;
    font-weight: 600;
    font-family: 'Be Vietnam Pro', monospace;
}

/* 错误 */
.form-error {
    font-size: 0.82rem;
    color: #EF4444;
    padding: 8px 12px;
    background-color: rgba(239, 68, 68, 0.1);
    border-radius: 6px;
}

/* 底部 */
.wizard-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 16px 20px;
    border-top: 1px solid #312E81;
}

.wiz-btn {
    padding: 8px 18px;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    border: none;
    transition: all 0.2s;
    font-family: inherit;
}

.wiz-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.wiz-btn-cancel {
    background-color: rgba(148, 163, 184, 0.2);
    color: #CBD5E1;
}

.wiz-btn-cancel:hover {
    background-color: rgba(148, 163, 184, 0.3);
}

.wiz-btn-submit {
    background-color: #F97316;
    color: white;
}

.wiz-btn-submit:hover:not(:disabled) {
    background-color: #EA580C;
}
</style>
