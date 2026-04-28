<script setup lang="ts">
import ProVoiceManager from '@/views/pro_workspace/ProVoiceManager.vue'
</script>

<template>
  <div class="page-shell">
    <section class="page-hero">
      <p class="page-eyebrow">音色域</p>
      <h2 class="page-title">音色</h2>
      <p class="page-desc">统一管理角色、情感、编译和参考音频入口，不再依赖桌面 GUI。</p>
    </section>

    <section class="page-card">
      <ProVoiceManager />
    </section>
  </div>
</template>

<style scoped>
.page-shell {
  max-width: 1280px;
}
</style>
