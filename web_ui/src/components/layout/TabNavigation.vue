<script setup lang="ts">
// Tab 导航组件

defineProps<{
  tabs: { id: string; label: string }[]
  activeTab: string
}>()

const emit = defineEmits<{
  (e: 'update:activeTab', tab: string): void
}>()
</script>

<template>
  <nav class="tab-nav" aria-label="主导航">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      @click="emit('update:activeTab', tab.id)"
      class="tab-button"
      :class="{ 'is-active': activeTab === tab.id }"
      :aria-current="activeTab === tab.id ? 'page' : undefined"
    >
      {{ tab.label }}
    </button>
  </nav>
</template>

<style scoped>
.tab-nav {
  display: flex;
  gap: 10px;
  padding: 8px 24px 18px;
  overflow-x: auto;
  width: 100%;
  border-bottom: 1px solid var(--color-divider);
}

.tab-button {
  min-height: 44px;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.92);
  color: var(--color-text-secondary);
  font-size: 0.95rem;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-button:hover {
  background: #ffffff;
  color: var(--color-text);
  border-color: rgba(10, 132, 255, 0.18);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
}

.tab-button:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--color-focus-ring);
}

.tab-button.is-active {
  background: #ffffff;
  color: var(--color-text);
  border-color: rgba(10, 132, 255, 0.22);
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
}
</style>
