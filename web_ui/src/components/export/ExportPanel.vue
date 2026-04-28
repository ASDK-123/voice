<script setup lang="ts">
import { ref } from 'vue'
import { useExportStore } from '@/stores/export'

const exportStore = useExportStore()

const projectFileInput = ref<HTMLInputElement | null>(null)
const taskPlanFileInput = ref<HTMLInputElement | null>(null)

function triggerProjectImport() {
  projectFileInput.value?.click()
}

function triggerTaskPlanImport() {
  taskPlanFileInput.value?.click()
}

async function handleProjectImport(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  await exportStore.importProjectFile(file)
  input.value = ''
}

async function handleTaskPlanImport(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  await exportStore.importTaskPlanFile(file)
  input.value = ''
}
</script>

<template>
  <div class="space-y-4">
    <input ref="projectFileInput" type="file" accept=".json" class="hidden" @change="handleProjectImport" />
    <input ref="taskPlanFileInput" type="file" accept=".json" class="hidden" @change="handleTaskPlanImport" />

    <div class="export-grid">
      <section class="card export-card">
        <div class="section-head">
          <h3 class="section-title">浏览器项目</h3>
          <p class="section-desc">将当前工程保存到浏览器，或从本机浏览器恢复最近保存的工作状态。</p>
        </div>
        <div class="action-row">
          <button @click="exportStore.saveToBrowser()" class="btn btn-primary text-sm">保存到浏览器</button>
          <button @click="exportStore.loadFromBrowser()" class="btn btn-ghost text-sm">从浏览器恢复</button>
        </div>
      </section>

      <section class="card export-card">
        <div class="section-head">
          <h3 class="section-title">工程文件</h3>
          <p class="section-desc">导入或导出完整工程文件，包含资源库、脚本行、音色和内嵌音频。</p>
        </div>
        <div class="action-row">
          <button @click="exportStore.exportProjectFile()" :disabled="exportStore.isExporting" class="btn btn-primary text-sm">
            {{ exportStore.isExporting ? '导出中...' : '导出工程文件' }}
          </button>
          <button @click="triggerProjectImport()" :disabled="exportStore.isImporting" class="btn btn-ghost text-sm">
            {{ exportStore.isImporting ? '导入中...' : '导入工程文件' }}
          </button>
        </div>
      </section>

      <section class="card export-card">
        <div class="section-head">
          <h3 class="section-title">任务计划</h3>
          <p class="section-desc">导入、导出或恢复批量任务计划，正式收口任务页和导出页之间的导出能力。</p>
        </div>
        <div class="action-row">
          <button @click="exportStore.exportTaskPlanFile()" class="btn btn-primary text-sm">导出任务计划</button>
          <button @click="triggerTaskPlanImport()" class="btn btn-ghost text-sm">导入任务计划</button>
          <button @click="exportStore.restoreTaskDraft()" class="btn btn-ghost text-sm">恢复浏览器草稿</button>
        </div>
      </section>

      <section class="card export-card">
        <div class="section-head">
          <h3 class="section-title">结果导出</h3>
          <p class="section-desc">导出完整工程音频、批量任务合并音频，或生成字幕文件。</p>
        </div>
        <div class="action-row">
          <button @click="exportStore.exportRenderedAudio()" :disabled="exportStore.isRenderingAudio" class="btn btn-primary text-sm">
            {{ exportStore.isRenderingAudio ? '渲染中...' : '导出工程音频（WAV）' }}
          </button>
          <button @click="exportStore.exportMergedTaskAudio()" :disabled="exportStore.isMergingTaskAudio" class="btn btn-primary text-sm">
            {{ exportStore.isMergingTaskAudio ? '合并中...' : '导出批量合并音频' }}
          </button>
          <button @click="exportStore.exportSrtFile()" class="btn btn-ghost text-sm">导出字幕（SRT）</button>
        </div>
      </section>
    </div>

    <div v-if="exportStore.progressMessage" class="card export-status">
      {{ exportStore.progressMessage }}
    </div>
  </div>
</template>

<style scoped>
.export-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.export-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-head {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  margin: 0;
  color: var(--color-text);
  font-size: 1rem;
}

.section-desc {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  line-height: 1.6;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.export-status {
  color: var(--color-text);
  font-size: 0.95rem;
}

@media (max-width: 1024px) {
  .export-grid {
    grid-template-columns: 1fr;
  }
}
</style>
