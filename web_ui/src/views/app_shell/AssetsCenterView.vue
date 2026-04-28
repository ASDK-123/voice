<script setup lang="ts">
import { computed } from 'vue'
import ProAssetsPanel from '@/views/pro_workspace/ProAssetsPanel.vue'
import { useProVoiceStore } from '@/stores/pro_voice'

const voiceStore = useProVoiceStore()

const assetSummary = computed(() => ({
  total: voiceStore.assets.length,
  linked: voiceStore.assets.filter(asset => asset.linked).length,
  unused: voiceStore.assets.filter(asset => !asset.linked).length,
}))
</script>

<template>
  <div class="page-shell">
    <section class="page-hero">
      <div>
        <p class="page-eyebrow">资产域</p>
        <h2 class="page-title">资产</h2>
        <p class="page-desc">统一处理参考音频上传、试听、绑定、备注和未使用资产筛查。</p>
      </div>
      <div class="hero-stats">
        <span class="stat-pill">总数 {{ assetSummary.total }}</span>
        <span class="stat-pill">已绑定 {{ assetSummary.linked }}</span>
        <span class="stat-pill">未绑定 {{ assetSummary.unused }}</span>
      </div>
    </section>

    <ProAssetsPanel inline />
  </div>
</template>

<style scoped>
.page-shell {
  max-width: 1480px;
}

.page-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.hero-stats {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.stat-pill {
  background: var(--color-surface-soft);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 8px 12px;
  font-size: 0.82rem;
  font-weight: 700;
}

@media (max-width: 768px) {
  .page-hero {
    flex-direction: column;
  }
}
</style>
