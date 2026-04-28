<script setup lang="ts">
import SfxLibrary from '@/components/library/SfxLibrary.vue'
import BgmLibrary from '@/components/library/BgmLibrary.vue'
import TimbreLibrary from '@/components/library/TimbreLibrary.vue'
import FilterLibrary from '@/components/library/FilterLibrary.vue'
</script>

<template>
  <div class="page-shell">
    <section class="page-hero">
      <p class="page-eyebrow">资源库域</p>
      <h2 class="page-title">资源库</h2>
      <p class="page-desc">集中管理音效、背景音乐、滤镜和素材型资源，不与参考音频资产混用。</p>
    </section>

    <div class="stack-grid">
      <section class="page-card"><SfxLibrary /></section>
      <section class="page-card"><BgmLibrary /></section>
      <section class="page-card"><TimbreLibrary /></section>
      <section class="page-card"><FilterLibrary /></section>
    </div>
  </div>
</template>

<style scoped>
.page-shell {
  max-width: 1400px;
}

.stack-grid {
  display: grid;
  gap: 16px;
}
</style>
