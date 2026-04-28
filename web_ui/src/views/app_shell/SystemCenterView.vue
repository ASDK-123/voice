<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useSystemStore } from '@/stores/system'
import { useShellStore } from '@/stores/shell'
import ProSystemSettings from '@/views/pro_workspace/ProSystemSettings.vue'
import TtsConfigPanel from '@/components/config/TtsConfigPanel.vue'
import LlmConfigPanel from '@/components/config/LlmConfigPanel.vue'
import PromptConfigPanel from '@/components/config/PromptConfigPanel.vue'
import StatusBadge from '@/components/shared/StatusBadge.vue'
import StatusMessage from '@/components/shared/StatusMessage.vue'

const systemStore = useSystemStore()
const shellStore = useShellStore()
const runtimeIncident = computed(() => systemStore.lastRuntimeIncident)
const runtimeIncidentTone = computed(() => {
  if (!runtimeIncident.value) return 'is-neutral'
  return runtimeIncident.value.level === 'CRITICAL' ? 'is-danger' : 'is-warn'
})

function openLogs() {
  if (runtimeIncident.value) {
    systemStore.focusLogsForIncident(runtimeIncident.value)
    return
  }
  shellStore.setActiveTab('logs')
}

function formatTime(value: string) {
  if (!value) return '尚未记录'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  void systemStore.checkHealth()
})
</script>

<template>
  <div class="page-shell">
    <section class="page-hero">
      <div class="hero-copy">
        <p class="page-eyebrow">系统域</p>
        <h2 class="page-title">系统</h2>
        <p class="page-desc">统一管理连接配置、模型状态、LLM 设置和 Prompt 模板。</p>
      </div>
      <div class="hero-actions">
        <button class="btn btn-secondary" type="button" @click="openLogs">
          打开日志页
        </button>
      </div>
    </section>

    <section class="summary-grid">
      <article
        v-for="card in systemStore.summaryCards"
        :key="card.id"
        class="summary-card"
      >
        <p class="summary-label">{{ card.label }}</p>
        <h3 class="summary-value">{{ card.value }}</h3>
        <p class="summary-meta">{{ card.meta }}</p>
      </article>
    </section>

    <div class="overview-grid">
      <section class="page-card">
        <div class="section-head">
          <div>
            <h3 class="section-title">系统就绪检查</h3>
            <p class="section-desc">这一页只负责配置和运行时状态，不再承载批量任务与音色资产编辑。</p>
          </div>
        </div>
        <div class="status-list">
          <article
            v-for="item in systemStore.readinessChecks"
            :key="item.id"
            class="status-item"
          >
            <div>
              <p class="status-name">{{ item.label }}</p>
              <p class="status-detail">{{ item.detail }}</p>
            </div>
            <StatusBadge :label="item.ok ? '正常' : '待处理'" :tone="item.ok ? 'success' : 'warning'" />
          </article>
        </div>
      </section>

      <section class="page-card">
        <div class="section-head">
          <div>
            <h3 class="section-title">边界说明</h3>
            <p class="section-desc">本轮重构把系统域从页面拼装升级成正式边界，避免继续把配置逻辑散落在多个 Tab 里。</p>
          </div>
        </div>
        <dl class="meta-list">
          <div class="meta-item">
            <dt>TTS 配置数</dt>
            <dd>{{ systemStore.ttsConfigCount }}</dd>
          </div>
          <div class="meta-item">
            <dt>LLM 配置数</dt>
            <dd>{{ systemStore.llmConfigCount }}</dd>
          </div>
          <div class="meta-item">
            <dt>当前 GPU</dt>
            <dd>{{ systemStore.gpuName || '尚未获取' }}</dd>
          </div>
          <div class="meta-item">
            <dt>Prompt 模式</dt>
            <dd>{{ systemStore.promptModeLabel }}</dd>
          </div>
        </dl>
      </section>
    </div>

    <section class="page-card runtime-card">
      <div class="section-head runtime-head">
        <div>
          <h3 class="section-title">运行时联动</h3>
          <p class="section-desc">系统页负责动作与状态，日志页负责定位失败原因。两者现在通过运行时事件联动。</p>
        </div>
        <button class="btn btn-secondary" type="button" @click="openLogs">
          查看日志
        </button>
      </div>

      <StatusMessage
        v-if="systemStore.logsCapability === 'missing'"
        :title="systemStore.logsCapabilityWarningTitle"
        :message="systemStore.logsCapabilityWarningMessage"
        tone="warning"
      >
        <template #actions>
          <button class="btn btn-secondary" type="button" @click="openLogs">
            查看日志
          </button>
        </template>
      </StatusMessage>

      <div class="runtime-grid">
        <article class="runtime-metric">
          <p class="summary-label">运行模式</p>
          <h4 class="runtime-value">{{ systemStore.runtimeModeLabel }}</h4>
          <p class="runtime-meta">
            {{ systemStore.currentTtsConfig?.baseUrl || '请先选择 TTS 配置' }}
          </p>
        </article>

        <article class="runtime-metric">
          <p class="summary-label">本地桥接</p>
          <h4 class="runtime-value">{{ systemStore.bridgeStatusLabel }}</h4>
          <p class="runtime-meta">
            {{
              systemStore.bridgeStatus === 'online'
                ? '可直接触发本地服务启动与模型加载'
                : systemStore.bridgeStatus === 'offline'
                  ? '桥接未运行，系统动作失败时会自动跳到日志页'
                  : systemStore.bridgeStatus === 'unavailable'
                    ? '当前连接为远程服务模式'
                    : '等待下一次桥接状态检查'
            }}
          </p>
        </article>

        <article class="runtime-metric">
          <p class="summary-label">最近动作</p>
          <h4 class="runtime-value">{{ formatTime(systemStore.lastRuntimeActionAt) }}</h4>
          <p class="runtime-meta">用于判断最近一次运行时操作是否已经产生新的失败事件。</p>
        </article>
      </div>

      <article class="incident-card" :class="runtimeIncidentTone">
        <div class="incident-copy">
          <p class="incident-label">最近一次运行时事件</p>
          <h4 class="incident-title">
            {{ runtimeIncident?.title || '暂无运行时失败事件' }}
          </h4>
          <p class="incident-detail">
            {{
              runtimeIncident?.detail
                || '启动、加载或桥接失败时，会在这里保留摘要，并自动联动到日志页。'
            }}
          </p>
          <p class="incident-meta">
            {{
              runtimeIncident
                ? `${formatTime(runtimeIncident.occurredAt)} · 建议查看 ${runtimeIncident.logSource} 日志`
                : '当前没有需要排障的最新事件'
            }}
          </p>
        </div>
        <div class="incident-actions">
          <button class="btn btn-secondary" type="button" @click="openLogs">
            查看日志
          </button>
          <button
            v-if="runtimeIncident"
            class="btn btn-ghost"
            type="button"
            @click="systemStore.clearRuntimeIncident()"
          >
            清除摘要
          </button>
        </div>
      </article>
    </section>

    <section class="page-card">
      <ProSystemSettings />
    </section>

    <div class="config-grid">
      <section class="page-card">
        <TtsConfigPanel />
      </section>
      <section class="page-card">
        <LlmConfigPanel />
      </section>
    </div>

    <section class="page-card">
      <PromptConfigPanel />
    </section>
  </div>
</template>

<style scoped>
.page-shell {
  max-width: 1400px;
}

.page-hero {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.hero-copy {
  min-width: 0;
}

.hero-actions {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.summary-card {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(250, 251, 253, 0.98) 100%);
  border: 1px solid var(--color-border);
  border-radius: 24px;
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.06);
  padding: 20px 22px;
}

.summary-label {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: 0.82rem;
  font-weight: 700;
}

.summary-value {
  margin: 12px 0 8px;
  color: var(--color-text);
  font-size: 1.4rem;
}

.summary-meta {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.5;
  font-size: 0.9rem;
}

.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: 16px;
}

.section-head {
  margin-bottom: 18px;
}

.section-title {
  margin: 0;
  color: var(--color-text);
  font-size: 1.05rem;
}

.section-desc {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
  line-height: 1.55;
  font-size: 0.92rem;
}

.status-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.status-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-radius: 18px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-muted);
}

.status-name {
  margin: 0;
  color: var(--color-text);
  font-weight: 700;
}

.status-detail {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
  line-height: 1.55;
  font-size: 0.9rem;
}

.meta-list {
  display: grid;
  gap: 14px;
}

.meta-item {
  display: grid;
  grid-template-columns: 112px 1fr;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--color-divider);
}

.meta-item:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.meta-item dt {
  color: var(--color-text-tertiary);
  font-size: 0.9rem;
}

.meta-item dd {
  margin: 0;
  color: var(--color-text);
  word-break: break-word;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.runtime-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.runtime-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.runtime-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.runtime-metric {
  padding: 18px;
  border-radius: 20px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-muted);
}

.runtime-value {
  margin: 10px 0 8px;
  color: var(--color-text);
  font-size: 1.1rem;
}

.runtime-meta {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.55;
  font-size: 0.9rem;
}

.incident-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 20px;
  border-radius: 20px;
  border: 1px solid var(--color-border);
  background: var(--color-surface-muted);
}

.incident-card.is-neutral {
  background: var(--color-surface-muted);
}

.incident-card.is-warn {
  background: var(--color-warning-soft);
  border-color: rgba(255, 159, 10, 0.18);
}

.incident-card.is-danger {
  background: var(--color-danger-soft);
  border-color: rgba(255, 69, 58, 0.18);
}

.incident-copy {
  min-width: 0;
}

.incident-label {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: 0.82rem;
  font-weight: 700;
}

.incident-title {
  margin: 12px 0 8px;
  color: var(--color-text);
  font-size: 1.05rem;
}

.incident-detail,
.incident-meta {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.55;
  font-size: 0.92rem;
}

.incident-meta {
  margin-top: 10px;
}

.incident-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 12px;
}

@media (max-width: 1024px) {
  .summary-grid,
  .overview-grid,
  .config-grid,
  .runtime-grid {
    grid-template-columns: 1fr;
  }

  .page-hero {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .meta-item {
    grid-template-columns: 1fr;
  }

  .runtime-head,
  .incident-card {
    flex-direction: column;
  }
}
</style>
