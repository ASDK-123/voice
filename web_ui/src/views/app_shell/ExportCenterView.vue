<script setup lang="ts">
import ExportPanel from '@/components/export/ExportPanel.vue'
</script>

<template>
  <div class="page-shell">
    <section class="page-hero">
      <p class="page-eyebrow">导出域</p>
      <h2 class="page-title">导出</h2>
      <p class="page-desc">统一放置工程导入导出、本地保存加载、音频导出和字幕导出。</p>
    </section>

    <section class="page-card">
      <ExportPanel />
    </section>
  </div>
</template>

<style scoped>
.page-shell {
  max-width: 1320px;
}
</style>
