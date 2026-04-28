<script setup lang="ts">
// LLM 聊天/脚本分析面板
import { useLlmStore } from '@/stores/llm'
import { useProjectStore } from '@/stores/project'
import { useLibrariesStore } from '@/stores/libraries'
import { buildAnalysisPrompt, DEFAULT_PROMPT_TEMPLATE } from '@/utils/prompt'

const llm = useLlmStore()
const project = useProjectStore()
const libs = useLibrariesStore()

/** 一键生成分析 Prompt */
function generateAnalysisPrompt() {
  const rawScript = project.rawScript.trim()
  if (!rawScript) {
    llm.error = '请先在“剧本”页面粘贴原文内容'
    return
  }

  const template = llm.useCustomPrompt && llm.customPromptTemplate.trim()
    ? llm.customPromptTemplate
    : undefined

  llm.prompt = buildAnalysisPrompt({
    rawScript,
    sfxLibrary: libs.sfxLibrary,
    bgmLibrary: libs.bgmLibrary,
    filterLibrary: libs.filterLibrary,
    customTemplate: template,
  })
}

/** 一键分析 */
async function analyzeScript() {
  generateAnalysisPrompt()
  if (llm.prompt) {
    await llm.send()
  }
}

/** 将 AI 输出应用到脚本 */
function applyToScript() {
  if (!llm.result) return
  const success = project.parseAnalysisResult(llm.result)
  if (success) {
    project.rawAnalysisResult = llm.result
    applySuccess.value = true
    setTimeout(() => { applySuccess.value = false }, 3000)
  }
}

import { ref } from 'vue'
const applySuccess = ref(false)

function copyResult() {
  navigator.clipboard.writeText(llm.result)
}

function resetCustomPrompt() {
  llm.customPromptTemplate = DEFAULT_PROMPT_TEMPLATE
}
</script>

<template>
  <div class="space-y-4">
    <!-- 快捷操作区 -->
    <div class="card space-y-4">
      <div class="flex items-center gap-3 border-b border-slate-100 pb-2">
        <h3 class="text-base font-bold text-slate-700">脚本分析</h3>
        <span class="text-xs text-slate-400 font-mono bg-slate-50 px-2 py-0.5 rounded-full">
          {{ project.rawScript ? `原文 ${project.rawScript.length} 字` : '尚未输入原文' }}
        </span>
      </div>
      
      <div class="flex flex-wrap items-center gap-2">
        <button
          @click="analyzeScript()"
          :disabled="llm.loading || !llm.currentConfig || !project.rawScript"
          class="btn btn-primary"
        >
          {{ llm.loading ? '分析中...' : '一键分析剧本' }}
        </button>
        <button
          @click="generateAnalysisPrompt()"
          :disabled="!project.rawScript"
          class="btn btn-ghost"
          title="仅生成提示词草稿，不发送"
        >
          生成提示词
        </button>
        <button
          v-if="llm.loading"
          @click="llm.stopGeneration()"
          class="btn btn-danger"
        >
          停止
        </button>
        
        <div class="flex-1" />
        
        <span v-if="!llm.currentConfig" class="text-xs flex items-center gap-1 text-orange-500 bg-orange-50 px-2 py-1 rounded-lg">
          请先配置大语言模型
        </span>
      </div>
      
      <p class="text-xs text-slate-400 flex items-center gap-2 bg-blue-50/50 p-2 rounded-lg text-blue-600/80">
        系统会自动注入资源库信息和情绪列表。建议先在“剧本”页面整理原文，再回到这里查看分析过程。
      </p>
    </div>

    <!-- Prompt 编辑区域 -->
    <div class="card space-y-3">
      <div class="flex items-center justify-between">
        <label class="label mb-0">提示词预览</label>
        <span v-if="llm.prompt" class="text-xs font-mono text-slate-400">
          {{ llm.prompt.length }} 字符
        </span>
      </div>
      <textarea
        v-model="llm.prompt"
        class="textarea font-mono text-xs leading-relaxed text-slate-600"
        rows="8"
        placeholder="点击“一键分析剧本”自动生成，也可以手动编辑提示词..."
      />
      <div class="flex items-center gap-2 justify-end">
        <button @click="llm.clearAll()" class="btn btn-ghost text-xs">清空</button>
        <button
          v-if="llm.loading"
          @click="llm.stopGeneration()"
          class="btn btn-danger text-xs"
        >
          停止
        </button>
        <button
          @click="llm.send()"
          :disabled="llm.loading || !llm.currentConfig || !llm.prompt"
          class="btn btn-primary text-xs px-4"
        >
          {{ llm.loading ? '生成中...' : '发送提示词' }}
        </button>
      </div>
    </div>

    <!-- 错误 -->
    <div v-if="llm.error" class="card border-red-200 bg-red-50/50">
      <pre class="text-xs whitespace-pre-wrap text-red-600">{{ llm.error }}</pre>
    </div>

    <!-- 推理过程 -->
    <div v-if="llm.reasoning" class="card bg-slate-50 border-slate-200">
      <details>
        <summary class="text-xs font-bold text-slate-500 cursor-pointer hover:text-primary transition-colors select-none">
          推理过程
        </summary>
        <pre class="mt-2 text-xs whitespace-pre-wrap text-slate-600 leading-relaxed font-mono p-2 rounded bg-white border border-slate-200 overflow-x-auto">{{ llm.reasoning }}</pre>
      </details>
    </div>

    <!-- 输出结果 -->
    <transition name="fade">
      <div v-if="llm.result" class="card border-primary/20 shadow-md">
        <div class="flex items-center justify-between mb-3 border-b border-slate-100 pb-2">
          <h3 class="text-base font-bold text-slate-700">分析结果</h3>
          <div class="flex gap-2">
            <!-- 应用到脚本按钮 -->
            <button
              @click="applyToScript()"
              class="btn btn-sm text-xs px-3 py-1 transition-all"
              :class="applySuccess ? 'bg-green-500 text-white hover:bg-green-600' : 'btn-primary'"
            >
              {{ applySuccess ? '已应用到脚本' : '应用到脚本' }}
            </button>
            <button @click="copyResult()" class="btn btn-ghost text-xs px-2 py-1">复制结果</button>
          </div>
        </div>
        
        <!-- 解析错误提示 -->
        <div v-if="project.analysisError" class="text-xs mb-3 p-3 rounded-lg bg-red-50 text-red-600 border border-red-100 flex items-start gap-2">
          <span>错误</span>
          <pre class="whitespace-pre-wrap font-sans">{{ project.analysisError }}</pre>
        </div>
        
        <pre class="text-sm whitespace-pre-wrap leading-relaxed font-mono text-slate-700 bg-slate-50 p-4 rounded-lg border border-slate-100 max-h-[500px] overflow-y-auto custom-scrollbar">{{ llm.result }}</pre>
      </div>
    </transition>

    <!-- 自定义 Prompt 设置 -->
    <div class="card">
      <details>
        <summary class="text-xs font-bold text-slate-500 cursor-pointer hover:text-primary transition-colors select-none">
          自定义提示词模板
        </summary>
        <div class="mt-4 space-y-3 pl-4 border-l-2 border-slate-100">
          <label class="flex items-center gap-2 text-sm cursor-pointer select-none text-slate-700">
            <input type="checkbox" v-model="llm.useCustomPrompt" class="accent-primary w-4 h-4" />
            启用自定义模板
          </label>
          
          <div class="text-xs text-slate-400 bg-slate-50 p-2 rounded border border-slate-100">
            <strong>可用变量：</strong>
            <div class="flex flex-wrap gap-1 mt-1 font-mono text-[10px]">
              <span class="bg-white px-1 rounded border border-slate-200" v-for="v in ['${rawScript}', '${sfxSection}', '${bgmSection}', '${filterSection}', '${emotionList}', '${bgmExampleLine}', '${sfxExample}']" :key="v">{{ v }}</span>
            </div>
          </div>
          
          <textarea
            v-model="llm.customPromptTemplate"
            class="textarea text-xs font-mono h-64"
            :placeholder="DEFAULT_PROMPT_TEMPLATE.slice(0, 200) + '...'"
          />
          
          <div class="flex gap-2 justify-end">
            <button @click="resetCustomPrompt()" class="btn btn-ghost text-xs">重置默认</button>
            <button @click="llm.savePrompt()" class="btn btn-primary text-xs">保存配置</button>
          </div>
        </div>
      </details>
    </div>
  </div>
</template>
