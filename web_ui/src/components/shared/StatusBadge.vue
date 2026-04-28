<script setup lang="ts">
const props = withDefaults(defineProps<{
  label: string
  tone?: 'neutral' | 'processing' | 'success' | 'warning' | 'danger'
  compact?: boolean
}>(), {
  tone: 'neutral',
  compact: false,
})
</script>

<template>
  <span class="status-badge" :class="[`is-${props.tone}`, { 'is-compact': props.compact }]">
    <span class="status-dot"></span>
    <span>{{ props.label }}</span>
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 0.75rem;
  font-weight: 700;
}

.status-badge.is-compact {
  min-height: 24px;
  padding: 4px 9px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-badge.is-neutral {
  background: #f3f4f6;
  border-color: #d1d5db;
  color: #4b5563;
}

.status-badge.is-processing {
  background: #fff4ea;
  border-color: rgba(249, 115, 22, 0.22);
  color: var(--color-warning);
}

.status-badge.is-success {
  background: #edf9f0;
  border-color: rgba(21, 128, 61, 0.2);
  color: var(--color-success);
}

.status-badge.is-warning {
  background: rgba(255, 159, 10, 0.12);
  border-color: rgba(255, 159, 10, 0.18);
  color: #b45309;
}

.status-badge.is-danger {
  background: #fff1f2;
  border-color: rgba(220, 38, 38, 0.2);
  color: var(--color-danger);
}

.status-badge.is-neutral .status-dot { background: #64748b; }
.status-badge.is-processing .status-dot { background: #f97316; }
.status-badge.is-success .status-dot { background: #16a34a; }
.status-badge.is-warning .status-dot { background: #d97706; }
.status-badge.is-danger .status-dot { background: #dc2626; }
</style>
