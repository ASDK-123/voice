<script setup lang="ts">
defineEmits<{
  (e: 'navigate', tab: string): void
}>()

import ScriptEditor from '@/components/script/ScriptEditor.vue'
import ChatPanel from '@/components/chat/ChatPanel.vue'
</script>

<template>
  <div class="page-shell">
    <section class="page-hero">
      <div>
        <p class="page-eyebrow">剧本域</p>
        <h2 class="page-title">剧本</h2>
        <p class="page-desc">在这里完成原文输入、角色管理、AI 分析和脚本行整理。</p>
      </div>
    </section>

    <section class="page-note">
      <p class="note-title">当前边界</p>
      <p class="note-desc">
        剧本页保留创作、分析、角色绑定和单行试听流程；批量提交、任务轮询、结果合并与工程导出已经分别迁入“任务”和“导出”页。
      </p>
    </section>

    <div class="page-grid">
      <section class="page-card">
        <ScriptEditor />
      </section>
      <section class="page-card">
        <ChatPanel />
      </section>
    </div>
  </div>
</template>

<style scoped>
.page-shell {
  max-width: 1400px;
}

.page-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(360px, 0.9fr);
  gap: 16px;
  align-items: start;
}

.page-card {
  padding: 20px;
  min-width: 0;
}

@media (max-width: 1180px) {
  .page-grid {
    grid-template-columns: 1fr;
  }
}
</style>
