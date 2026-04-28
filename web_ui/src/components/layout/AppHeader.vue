<script setup lang="ts">
// 顶部导航栏（含 Undo/Redo 按钮）
import { computed, onMounted, onUnmounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import {
  ArrowUturnLeftIcon,
  ArrowUturnRightIcon,
  SpeakerWaveIcon,
} from '@heroicons/vue/24/outline'

const props = defineProps<{
  activeTab: string
}>()

const project = useProjectStore()
const showScriptActions = computed(() => props.activeTab === 'script')

// ── 键盘快捷键 ──
function handleKeydown(e: KeyboardEvent) {
    if (!showScriptActions.value) return
    // Ctrl+Z = 撤销
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault()
        project.undo()
    }
    // Ctrl+Y 或 Ctrl+Shift+Z = 重做
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
        e.preventDefault()
        project.redo()
    }
}

onMounted(() => {
    window.addEventListener('keydown', handleKeydown)
})
onUnmounted(() => {
    window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <header class="app-header">
    <div class="brand-group">
      <div class="brand-mark">
        <SpeakerWaveIcon class="brand-icon" />
      </div>
      <div>
        <h1 class="brand-title">CosyVoice 控制台</h1>
        <p class="brand-subtitle">
          {{ showScriptActions ? '剧本工作流 · 支持撤销与重做' : 'WebUI 主线 · 简体中文工作站' }}
        </p>
      </div>
    </div>

    <div v-if="showScriptActions" class="action-group">
      <button
        @click="project.undo()"
        :disabled="!project.canUndo"
        class="action-btn"
        :class="{ 'is-disabled': !project.canUndo }"
        title="撤销 (Ctrl+Z)"
      >
        <ArrowUturnLeftIcon class="action-icon" />
        <span>撤销</span>
      </button>
      <button
        @click="project.redo()"
        :disabled="!project.canRedo"
        class="action-btn"
        :class="{ 'is-disabled': !project.canRedo }"
        title="重做 (Ctrl+Y)"
      >
        <ArrowUturnRightIcon class="action-icon" />
        <span>重做</span>
      </button>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 50;
  margin-bottom: 16px;
  padding: 16px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
}

.brand-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: linear-gradient(135deg, #0071e3, #5ac8fa);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 10px 24px rgba(0, 113, 227, 0.18);
}

.brand-icon {
  width: 22px;
  height: 22px;
  color: #fff;
}

.brand-title {
  margin: 0;
  font-size: 1.08rem;
  color: #1d1d1f;
}

.brand-subtitle {
  margin: 4px 0 0;
  color: #6e6e73;
  font-size: 0.84rem;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-btn {
  min-height: 40px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #fff;
  color: #1d1d1f;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font: inherit;
  transition: all 0.2s ease;
}

.action-btn:hover:not(.is-disabled) {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
}

.action-btn.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.action-icon {
  width: 16px;
  height: 16px;
}

@media (max-width: 768px) {
  .app-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
