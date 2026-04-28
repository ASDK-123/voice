<script setup lang="ts">
import { computed } from 'vue'
import { useSystemStore } from '@/stores/system'
import { useProVoiceStore } from '@/stores/pro_voice'
import { useProTaskStore } from '@/stores/pro_task'

const emit = defineEmits<{
  (e: 'navigate', tab: string): void
}>()

const systemStore = useSystemStore()
const voiceStore = useProVoiceStore()
const taskStore = useProTaskStore()

const summaryCards = computed(() => [
  {
    label: '系统状态',
    value: systemStore.statusLabel,
    meta: systemStore.gpuName || '未连接后端',
  },
  {
    label: '音色数量',
    value: `${voiceStore.voices.length}`,
    meta: voiceStore.selectedVoice?.name || '未选择音色',
  },
  {
    label: '任务行数',
    value: `${taskStore.taskRows.length}`,
    meta: `已完成 ${taskStore.completedCount} 行`,
  },
  {
    label: '当前连接',
    value: systemStore.currentTtsConfig?.name || '未选择',
    meta: systemStore.currentTtsConfig?.baseUrl || '请先配置 TTS 后端',
  },
])

const quickLinks = [
  { id: 'script', title: '进入剧本', desc: '输入原文、角色管理、AI 分析' },
  { id: 'task', title: '进入任务', desc: '批量合成、单行运行、结果试听' },
  { id: 'voice', title: '进入音色', desc: '管理角色、情绪和参考音频入口' },
  { id: 'system', title: '进入系统', desc: '连接配置、模型状态、Prompt 设置' },
]

const recentRows = computed(() =>
  [...taskStore.taskRows]
    .filter(row => row.text.trim())
    .slice(-5)
    .reverse(),
)

function go(tab: string) {
  emit('navigate', tab)
}

function trimText(text: string): string {
  const normalized = text.trim()
  if (normalized.length <= 44) return normalized
  return `${normalized.slice(0, 44)}...`
}

function statusText(status: string): string {
  const map: Record<string, string> = {
    idle: '待编辑',
    pending: '排队中',
    processing: '合成中',
    done: '已完成',
    failed: '失败',
  }
  return map[status] || status
}
</script>

<template>
  <div class="dashboard-shell">
    <section class="hero-card">
      <div>
        <p class="hero-eyebrow">WebUI 主线</p>
        <h2 class="hero-title">工作台</h2>
        <p class="hero-desc">
          当前 WebUI 已拆分为正式模块。这里仅保留状态总览和快捷入口，不再承载所有编辑工作。
        </p>
      </div>
      <div class="hero-actions">
        <button class="hero-btn primary" @click="go('script')">开始写剧本</button>
        <button class="hero-btn secondary" @click="go('task')">查看任务</button>
      </div>
    </section>

    <section class="summary-grid">
      <article v-for="card in summaryCards" :key="card.label" class="summary-card">
        <p class="summary-label">{{ card.label }}</p>
        <h3 class="summary-value">{{ card.value }}</h3>
        <p class="summary-meta">{{ card.meta }}</p>
      </article>
    </section>

    <section class="content-grid">
      <article class="panel-card">
        <div class="section-head">
          <div>
            <h3 class="section-title">快捷入口</h3>
            <p class="section-desc">按领域进入正式页面，避免把所有操作堆到一个界面。</p>
          </div>
        </div>
        <div class="quick-grid">
          <button
            v-for="item in quickLinks"
            :key="item.id"
            class="quick-card"
            @click="go(item.id)"
          >
            <span class="quick-title">{{ item.title }}</span>
            <span class="quick-desc">{{ item.desc }}</span>
          </button>
        </div>
      </article>

      <article class="panel-card">
        <div class="section-head">
          <div>
            <h3 class="section-title">当前环境</h3>
            <p class="section-desc">用于确认连接、模型和本轮工作的基础状态。</p>
          </div>
        </div>
        <dl class="meta-list">
          <div class="meta-item">
            <dt>后端地址</dt>
            <dd>{{ systemStore.currentTtsConfig?.baseUrl || '未配置' }}</dd>
          </div>
          <div class="meta-item">
            <dt>鉴权状态</dt>
            <dd>{{ systemStore.apiKeyEnabled ? '已启用 API Key' : '未启用' }}</dd>
          </div>
          <div class="meta-item">
            <dt>模型状态</dt>
            <dd>{{ systemStore.healthInfo?.model_loaded ? '已加载' : '未加载' }}</dd>
          </div>
          <div class="meta-item">
            <dt>当前选中音色</dt>
            <dd>{{ voiceStore.selectedVoice?.name || '未选择' }}</dd>
          </div>
        </dl>
      </article>
    </section>

    <section class="panel-card">
      <div class="section-head">
        <div>
          <h3 class="section-title">最近任务</h3>
          <p class="section-desc">只展示最近几条任务摘要，完整编辑请进入“任务”页。</p>
        </div>
        <button class="inline-link" @click="go('task')">打开任务页</button>
      </div>

      <div v-if="recentRows.length === 0" class="empty-state">
        还没有任务记录。可以先进入“剧本”或“任务”开始新一轮合成。
      </div>

      <div v-else class="recent-list">
        <article v-for="row in recentRows" :key="row.row_id" class="recent-row">
          <div class="recent-main">
            <p class="recent-text">{{ trimText(row.text) }}</p>
            <p class="recent-meta">{{ row.voice_id || '未指定音色' }}</p>
          </div>
          <span class="recent-status" :class="`is-${row.status}`">{{ statusText(row.status) }}</span>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard-shell {
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.hero-card,
.panel-card,
.summary-card {
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 24px;
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.06);
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 32px;
  align-items: flex-start;
}

.hero-eyebrow {
  margin: 0 0 8px;
  font-size: 0.8rem;
  font-weight: 600;
  color: #6e6e73;
}

.hero-title {
  margin: 0;
  font-size: 2rem;
  color: #1d1d1f;
}

.hero-desc {
  margin: 12px 0 0;
  max-width: 640px;
  color: #4b5563;
  line-height: 1.65;
}

.hero-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.hero-btn {
  min-height: 44px;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid transparent;
  font: inherit;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}

.hero-btn:hover {
  transform: translateY(-1px);
}

.hero-btn.primary {
  background: #0071e3;
  color: #fff;
  box-shadow: 0 10px 24px rgba(0, 113, 227, 0.22);
}

.hero-btn.secondary {
  background: #f5f5f7;
  color: #1d1d1f;
  border-color: rgba(15, 23, 42, 0.08);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.summary-card {
  padding: 20px 22px;
}

.summary-label {
  margin: 0;
  font-size: 0.82rem;
  color: #6e6e73;
}

.summary-value {
  margin: 12px 0 8px;
  font-size: 1.5rem;
  color: #1d1d1f;
}

.summary-meta {
  margin: 0;
  color: #4b5563;
  font-size: 0.9rem;
  line-height: 1.5;
}

.content-grid {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 16px;
}

.panel-card {
  padding: 24px;
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

.section-title {
  margin: 0;
  font-size: 1.05rem;
  color: #1d1d1f;
}

.section-desc {
  margin: 8px 0 0;
  color: #6e6e73;
  font-size: 0.92rem;
  line-height: 1.55;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.quick-card {
  text-align: left;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: linear-gradient(180deg, #fff 0%, #fafafc 100%);
  border-radius: 18px;
  padding: 18px;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  min-height: 88px;
}

.quick-card:hover {
  transform: translateY(-1px);
  border-color: rgba(0, 113, 227, 0.2);
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.06);
}

.quick-title,
.quick-desc {
  display: block;
}

.quick-title {
  color: #1d1d1f;
  font-weight: 600;
}

.quick-desc {
  margin-top: 8px;
  font-size: 0.88rem;
  line-height: 1.5;
  color: #6e6e73;
}

.meta-list {
  display: grid;
  gap: 14px;
}

.meta-item {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
}

.meta-item:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.meta-item dt {
  color: #6e6e73;
  font-size: 0.9rem;
}

.meta-item dd {
  margin: 0;
  color: #1d1d1f;
  word-break: break-all;
}

.inline-link {
  border: none;
  background: transparent;
  color: #0071e3;
  cursor: pointer;
  font: inherit;
  padding: 0;
}

.empty-state {
  border-radius: 18px;
  background: #f5f5f7;
  color: #6e6e73;
  padding: 24px;
  line-height: 1.6;
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.recent-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-radius: 18px;
  background: #fafafc;
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.recent-main {
  min-width: 0;
}

.recent-text {
  margin: 0;
  color: #1d1d1f;
  font-weight: 500;
}

.recent-meta {
  margin: 6px 0 0;
  color: #6e6e73;
  font-size: 0.88rem;
}

.recent-status {
  flex-shrink: 0;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 0.78rem;
  font-weight: 600;
}

.recent-status.is-idle {
  background: #f3f4f6;
  color: #4b5563;
}

.recent-status.is-pending,
.recent-status.is-processing {
  background: rgba(255, 159, 10, 0.12);
  color: #b45309;
}

.recent-status.is-done {
  background: rgba(52, 199, 89, 0.14);
  color: #15803d;
}

.recent-status.is-failed {
  background: rgba(255, 59, 48, 0.12);
  color: #dc2626;
}

@media (max-width: 1024px) {
  .summary-grid,
  .content-grid,
  .quick-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 768px) {
  .hero-card,
  .summary-grid,
  .content-grid,
  .quick-grid {
    grid-template-columns: 1fr;
  }

  .hero-card {
    flex-direction: column;
    padding: 24px;
  }

  .meta-item {
    grid-template-columns: 1fr;
  }

  .recent-row {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
