<script setup lang="ts">
// EmotionSelector.vue — Apple Style 情绪/风格选择器
// P6: 基于角色动态聚合 Voice Variants，替代静态中文情绪下拉
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useProVoiceStore } from '@/stores/pro_voice'

const props = defineProps<{
  /** 当前角色名 */
  character: string
  /** 当前选中的情绪 Tag (v-model) */
  modelValue: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const voiceStore = useProVoiceStore()
const isOpen = ref(false)
const selectorRef = ref<HTMLElement | null>(null)

/** 当前角色可用的情绪变体列表 */
const variants = computed(() => {
  if (!props.character) return []

  return voiceStore.voices
    .filter(v => v.character === props.character || v.name.startsWith(`${props.character}#`))
    .map(v => ({
      tag: v.emotion || v.name.split('#')[1] || 'default',
      color: v.color || '#888888',
      voiceId: v.name,
    }))
    // 去重（按 tag）
    .filter((v, i, arr) => arr.findIndex(a => a.tag === v.tag) === i)
    .sort((a, b) => {
      // default 排第一
      if (a.tag === 'default') return -1
      if (b.tag === 'default') return 1
      return a.tag.localeCompare(b.tag)
    })
})

/** 当前选中变体的颜色 */
const currentColor = computed(() => {
  const found = variants.value.find(v => v.tag === props.modelValue)
  return found?.color || '#888888'
})

/** 是否有多个可选变体（只有1个时禁用交互） */
const hasMultiple = computed(() => variants.value.length > 1)

/** 显示文本 */
const displayText = computed(() => {
  return props.modelValue || 'default'
})

function select(tag: string) {
  emit('update:modelValue', tag)
  isOpen.value = false
}

function toggle() {
  if (!hasMultiple.value) return
  isOpen.value = !isOpen.value
}

// 点击外部关闭 Popover
function handleClickOutside(e: MouseEvent) {
  if (selectorRef.value && !selectorRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))
</script>

<template>
  <div ref="selectorRef" class="emotion-selector" :class="{ 'is-open': isOpen }">
    <!-- Pill 按钮 -->
    <button
      class="emotion-pill"
      :class="{ 'is-disabled': !hasMultiple }"
      :title="hasMultiple ? '点击切换情绪风格' : '当前角色只有一种风格'"
      @click.stop="toggle"
    >
      <span
        class="color-dot"
        :style="{ backgroundColor: currentColor }"
      />
      <span class="pill-text">{{ displayText }}</span>
      <svg v-if="hasMultiple" class="chevron" width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
        <path d="M2.5 3.5L5 6L7.5 3.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
      </svg>
    </button>

    <!-- Popover 菜单 -->
    <Transition name="popover">
      <div v-if="isOpen && hasMultiple" class="popover-menu">
        <button
          v-for="v in variants"
          :key="v.tag"
          class="popover-item"
          :class="{ 'is-selected': v.tag === modelValue }"
          @click.stop="select(v.tag)"
        >
          <span class="color-dot" :style="{ backgroundColor: v.color }" />
          <span class="item-text">{{ v.tag }}</span>
          <svg v-if="v.tag === modelValue" class="check-icon" width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 7.5L5.5 10L11 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.emotion-selector {
  position: relative;
  display: inline-flex;
}

/* ── Pill 按钮 ── */
.emotion-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px 3px 6px;
  border-radius: 20px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-secondary);
  color: var(--color-text);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.emotion-pill:hover:not(.is-disabled) {
  border-color: var(--color-primary);
  background: rgba(99, 102, 241, 0.08);
}

.emotion-pill.is-disabled {
  cursor: default;
  opacity: 0.6;
}

/* ── 颜色圆点 ── */
.color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.15);
}

.pill-text {
  line-height: 1;
}

.chevron {
  opacity: 0.5;
  transition: transform 0.2s ease;
  flex-shrink: 0;
}

.is-open .chevron {
  transform: rotate(180deg);
}

/* ── Popover 菜单 ── */
.popover-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  min-width: 130px;
  max-height: 200px;
  overflow-y: auto;
  padding: 4px;
  border-radius: 10px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-alt);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
  z-index: 100;
}

.popover-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 8px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--color-text);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.popover-item:hover {
  background: rgba(99, 102, 241, 0.12);
}

.popover-item.is-selected {
  color: var(--color-primary);
  font-weight: 600;
}

.item-text {
  flex: 1;
}

.check-icon {
  color: var(--color-primary);
  flex-shrink: 0;
}

/* ── Popover 动画 ── */
.popover-enter-active {
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.popover-leave-active {
  transition: all 0.15s ease-in;
}
.popover-enter-from {
  opacity: 0;
  transform: translateY(-4px) scale(0.95);
}
.popover-leave-to {
  opacity: 0;
  transform: translateY(-2px) scale(0.98);
}
</style>
