<script setup lang="ts">
withDefaults(defineProps<{
  title?: string
  message: string
  tone?: 'neutral' | 'success' | 'warning' | 'danger'
}>(), {
  title: '',
  tone: 'neutral',
})
</script>

<template>
  <section class="status-message" :class="`is-${tone}`">
    <div>
      <p v-if="title" class="message-title">{{ title }}</p>
      <p class="message-body">{{ message }}</p>
    </div>
    <div v-if="$slots.actions" class="message-actions">
      <slot name="actions" />
    </div>
  </section>
</template>

<style scoped>
.status-message {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid var(--color-border);
}

.status-message.is-neutral {
  background: var(--color-surface-muted);
}

.status-message.is-success {
  background: var(--color-success-soft);
  border-color: rgba(52, 199, 89, 0.16);
}

.status-message.is-warning {
  background: var(--color-warning-soft);
  border-color: rgba(255, 159, 10, 0.18);
}

.status-message.is-danger {
  background: var(--color-danger-soft);
  border-color: rgba(255, 69, 58, 0.18);
}

.message-title {
  margin: 0 0 6px;
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--color-text-tertiary);
}

.message-body {
  margin: 0;
  line-height: 1.55;
  color: var(--color-text);
  font-weight: 600;
}

.message-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
</style>
