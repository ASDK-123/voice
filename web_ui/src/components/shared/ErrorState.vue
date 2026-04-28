<script setup lang="ts">
import StatusMessage from './StatusMessage.vue'

defineProps<{
  title?: string
  message: string
}>()
</script>

<template>
  <StatusMessage :title="title || '当前操作失败'" :message="message" tone="danger" />
</template>
