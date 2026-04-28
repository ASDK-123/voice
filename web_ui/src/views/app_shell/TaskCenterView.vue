<script setup lang="ts">
import ProTaskPlanTable from '@/views/pro_workspace/ProTaskPlanTable.vue'
</script>

<template>
  <div class="page-shell">
    <section class="page-hero">
      <p class="page-eyebrow">任务域</p>
      <h2 class="page-title">任务</h2>
      <p class="page-desc">集中处理批量合成、单行运行、结果试听、任务草稿和结果导出。</p>
    </section>

    <section class="page-card">
      <ProTaskPlanTable />
    </section>
  </div>
</template>

<style scoped>
.page-shell {
  max-width: 1440px;
}
</style>
