<script setup lang="ts">
defineProps<{
  title: string
  description: string
}>()
</script>

<template>
  <div class="empty-state">
    <p class="empty-title">{{ title }}</p>
    <p class="empty-desc">{{ description }}</p>
  </div>
</template>

<style scoped>
.empty-state {
  padding: 28px 24px;
  border: 1px dashed var(--color-border);
  border-radius: 18px;
  background: var(--color-surface-soft);
  text-align: center;
}

.empty-title {
  margin: 0;
  color: var(--color-text);
  font-weight: 700;
}

.empty-desc {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
  line-height: 1.55;
}
</style>
