<script setup lang="ts">
// 脚本编辑器主面板 — P0+P2 完整版
// 左右分栏：角色面板 + 脚本编辑区
// 含 AI 分析、TTS 生成、播放控制、情绪下拉、滤波器选择、波形编辑、音量控制
import { ref, computed, onMounted } from 'vue'
import { useVirtualList } from '@vueuse/core'
import { useProjectStore } from '@/stores/project'
import { useProVoiceStore } from '@/stores/pro_voice'
import { useLlmStore } from '@/stores/llm'
import { useProTaskStore } from '@/stores/pro_task'
import { useShellStore } from '@/stores/shell'
import ScriptRow from './ScriptRow.vue'

const project = useProjectStore()
const voiceStore = useProVoiceStore()
const llm = useLlmStore()
const taskStore = useProTaskStore()
const shellStore = useShellStore()

onMounted(() => {
  if (voiceStore.voices.length === 0) {
    void voiceStore.fetchVoices()
  }
})

// 新增角色
const newCharName = ref('')
const exportMode = ref<'replace' | 'append'>('replace')
function addNewCharacter() {
  if (newCharName.value.trim()) {
    project.addCharacter(newCharName.value.trim())
    newCharName.value = ''
  }
}

const taskExportPreview = computed(() => project.buildTaskExportPreview(exportMode.value))
const availableVoiceCharacters = computed(() => {
  return Array.from(new Set(
    voiceStore.voices
      .map(voice => voice.character || voice.name.split('#')[0] || '')
      .filter(Boolean),
  )).sort((a, b) => a.localeCompare(b, 'zh-CN'))
})

function sendToTaskPlan() {
  const preview = taskExportPreview.value
  if (!preview.can_export) return

  if (preview.mode === 'replace') {
    taskStore.replaceRowsFromScript(preview.rows)
  } else {
    taskStore.appendRowsFromScript(preview.rows)
  }
  taskStore.setImportSummary({
    mode: preview.mode,
    imported: preview.resolved_count,
    skippedBgm: preview.skipped_bgm_count,
    unresolved: preview.unresolved_count,
  })
  shellStore.setActiveTab('task')
}

// ── P7: 虚拟滚动 ──
const { list, containerProps, wrapperProps } = useVirtualList(
  // @ts-ignore: computed refs are compatible
  computed(() => project.scriptLines),
  {
    itemHeight: 180, // 预估高度，支持动态扩展
    overscan: 5,
  }
)
</script>

<template>
  <div class="flex flex-col lg:flex-row gap-4 items-start">
    <!-- ════════ 左侧：角色面板 ════════ -->
    <div class="w-full lg:w-56 flex-shrink-0 space-y-3">
      <div class="bg-white/60 backdrop-blur-sm border border-white/40 rounded-xl p-4 shadow-sm">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-bold text-slate-700">角色列表</h3>
          <span class="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded-full">{{ project.characters.length }}</span>
        </div>

        <!-- 新增角色 -->
        <div class="flex gap-1 mb-3">
          <input
            v-model="newCharName"
            @keyup.enter="addNewCharacter"
            class="input text-xs flex-1 bg-white"
            placeholder="角色名"
          />
          <button @click="addNewCharacter" class="btn btn-primary text-xs px-2 py-1 shadow-sm">+</button>
        </div>

        <!-- 角色列表 -->
        <div class="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
          <div
            v-for="char in project.characters"
            :key="char.id"
            class="p-2 rounded-lg text-xs space-y-1.5 transition-all duration-200 group hover:shadow-sm bg-white/50 border border-white/80"
          >
            <div class="flex items-center justify-between">
              <input
                v-model="char.name"
                class="input text-xs font-bold bg-transparent border-transparent hover:bg-white focus:bg-white px-1 py-0.5 h-6 max-w-[100px]"
              />
              <button
                @click="project.deleteCharacter(char.id)"
                class="text-xs px-1 opacity-0 group-hover:opacity-60 hover:!opacity-100 text-slate-400 hover:text-red-500 transition-opacity"
              >×</button>
            </div>
            <!-- Voice 绑定（v2） -->
            <div>
              <div class="text-[10px] font-bold mb-0.5 text-slate-400">角色音色</div>
              <select
                v-model="char.voiceId"
                class="input text-[10px] w-full !py-1 bg-white/50"
              >
                <option value="">-- 自动匹配 --</option>
                <option v-for="c in availableVoiceCharacters" :key="c" :value="c">
                  {{ c }}
                </option>
              </select>
            </div>
          </div>

          <!-- Empty State -->
          <div v-if="project.characters.length === 0" class="text-center py-8">
            <div class="text-2xl mb-2 opacity-20">角色</div>
            <p class="text-xs text-slate-400">暂无角色</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ════════ 右侧：脚本编辑区 ════════ -->
    <div class="flex-1 w-full min-w-0 space-y-4">

      <!-- 原文输入区 -->
      <div class="card">
        <label class="label">1. 输入原文 / 小说片段</label>
        <textarea
          v-model="project.rawScript"
          class="textarea text-sm"
          rows="6"
          placeholder="请粘贴小说内容或剧本原文..."
        />
      </div>

      <!-- 操作工具栏 (Floating Glass Bar) -->
      <div class="glass rounded-xl p-3 flex flex-wrap items-center gap-3 shadow-sm sticky top-0 z-10 transition-all duration-300">
        <!-- LLM 选择 -->
        <div class="flex flex-col gap-0.5">
           <label class="text-[10px] font-bold text-slate-400 tracking-wider pl-1">分析模型</label>
           <select v-model="llm.currentConfigId" class="input text-xs !py-1 bg-white/50 border-transparent hover:bg-white w-32">
            <option value="" disabled>选择模型</option>
            <option v-for="c in llm.configs" :key="c.id" :value="c.id">{{ c.name }}</option>
           </select>
        </div>

        <div class="w-px h-8 bg-slate-200/50 mx-1"></div>

        <!-- AI 分析按钮 -->
        <button
          @click="project.analyzeScript()"
          :disabled="project.isAnalyzing || !llm.currentConfig || !project.rawScript"
          class="btn btn-primary text-xs h-9 px-4 rounded-lg shadow-md hover:shadow-lg hover:-translate-y-0.5 transition-all"
        >
          {{ project.isAnalyzing ? '正在分析中...' : '开始 AI 分析' }}
        </button>

        <div class="flex-1"></div>

        <!-- 统计信息 -->
        <div class="flex items-center gap-3 text-xs text-slate-400 px-2">
           <span>{{ project.scriptLines.length }} 行脚本</span>
           <span class="w-1 h-1 rounded-full bg-slate-300"></span>
           <span>预计 {{ Math.round(project.scriptLines.length * 2.5 / 60) }} 分钟</span>
        </div>
      </div>

      <div class="card border-slate-200 bg-slate-50/80">
        <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div class="space-y-1">
            <p class="text-xs font-semibold tracking-wide text-slate-500">发送到任务</p>
            <h4 class="text-sm font-semibold text-slate-700">发送前预检</h4>
            <p class="text-xs text-slate-500">
              只处理台词行；背景音乐会计入跳过统计。若存在未解析音色行，则本次发送会被阻止。
            </p>
          </div>

          <div class="flex items-center gap-2">
            <select v-model="exportMode" class="input text-xs w-32 bg-white">
              <option value="replace">替换任务表</option>
              <option value="append">追加到任务表</option>
            </select>
            <button
              class="btn btn-primary text-xs"
              :disabled="!taskExportPreview.can_export"
              @click="sendToTaskPlan"
            >
              发送到任务
            </button>
          </div>
        </div>

        <div class="mt-3 grid gap-3 md:grid-cols-4">
          <div class="rounded-xl border border-slate-200 bg-white p-3">
            <p class="text-[11px] text-slate-500">台词行</p>
            <p class="mt-1 text-lg font-semibold text-slate-800">{{ taskExportPreview.dialogue_count }}</p>
          </div>
          <div class="rounded-xl border border-slate-200 bg-white p-3">
            <p class="text-[11px] text-slate-500">可导入</p>
            <p class="mt-1 text-lg font-semibold text-emerald-700">{{ taskExportPreview.resolved_count }}</p>
          </div>
          <div class="rounded-xl border border-slate-200 bg-white p-3">
            <p class="text-[11px] text-slate-500">跳过 BGM</p>
            <p class="mt-1 text-lg font-semibold text-slate-700">{{ taskExportPreview.skipped_bgm_count }}</p>
          </div>
          <div class="rounded-xl border border-slate-200 bg-white p-3">
            <p class="text-[11px] text-slate-500">未解析</p>
            <p class="mt-1 text-lg font-semibold" :class="taskExportPreview.unresolved_count > 0 ? 'text-rose-700' : 'text-slate-700'">
              {{ taskExportPreview.unresolved_count }}
            </p>
          </div>
        </div>

        <div v-if="taskExportPreview.unresolved_count > 0" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3">
          <p class="text-xs font-semibold text-rose-700">存在未解析音色行，暂不能发送到任务。</p>
          <ul class="mt-2 space-y-1 text-xs text-rose-700">
            <li v-for="item in taskExportPreview.unresolved.slice(0, 5)" :key="item.line_id">
              第 {{ item.line_index }} 行：{{ item.role }} / {{ item.emotion }}，{{ item.reason }}
            </li>
          </ul>
        </div>
      </div>

      <!-- 错误信息 -->
      <div v-if="project.analysisError" class="card border-red-500">
        <pre class="text-xs whitespace-pre-wrap text-red-500">{{ project.analysisError }}</pre>
      </div>

      <!-- LLM 推理过程 -->
      <div v-if="llm.reasoning && project.isAnalyzing" class="card">
        <details open>
          <summary class="text-xs font-medium cursor-pointer text-slate-500">推理过程</summary>
          <pre class="mt-2 text-xs whitespace-pre-wrap text-slate-500 max-h-[200px] overflow-y-auto">{{ llm.reasoning }}</pre>
        </details>
      </div>

      <!-- ════════ 中间：脚本编辑器 ════════ -->
    <div class="flex-1 min-w-0 flex flex-col h-[calc(100vh-140px)]">
      <!-- 工具栏 -->
      <div class="flex items-center gap-2 mb-2">
        <button
          @click="project.addDialogueBlock"
          class="btn btn-sm btn-primary text-xs"
          title="添加台词行"
        >＋ 台词</button>
        <button
          @click="project.addBgmBlock"
          class="btn btn-sm btn-ghost text-xs"
          title="添加背景音乐控制"
        >背景音乐</button>
        
        <div class="w-px h-4 bg-slate-200 mx-1"></div>

        <button
          @click="project.generateAllAudio"
          :disabled="project.isGeneratingAll"
          class="btn btn-sm btn-accent text-xs"
        >
          {{ project.isGeneratingAll ? `生成中 ${project.generateProgress}` : '批量生成音频' }}
        </button>
        
        <button
          @click="project.isSequencePlaying ? project.stopSequentially() : project.playSequentially()"
          class="btn btn-sm text-xs"
          :class="project.isSequencePlaying ? 'btn-error' : 'btn-success'"
        >
          {{ project.isSequencePlaying ? '停止连播' : '顺序连播' }}
        </button>
      </div>

      <!-- 虚拟滚动容器 (P7) -->
      <div v-bind="containerProps" class="space-y-0 h-full px-1 pb-10">
        <div v-bind="wrapperProps">
          <ScriptRow
            v-for="{ data: line, index } in list"
            :key="line.id"
            :line="line"
            :index="index"
          />
        </div>
      </div>

      <!-- AI 原始输出 -->
      <div v-if="project.rawAnalysisResult" class="card">
        <details>
          <summary class="text-xs font-medium cursor-pointer text-slate-500">
            AI 原始输出（调试）
          </summary>
          <pre class="mt-2 text-xs whitespace-pre-wrap rounded p-3 bg-slate-50 text-slate-500 max-h-[256px] overflow-y-auto">{{ project.rawAnalysisResult }}</pre>
        </details>
      </div>
    </div>
  </div>
</div>
</template>
