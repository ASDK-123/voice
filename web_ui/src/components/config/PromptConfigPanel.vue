<script setup lang="ts">
import { onMounted } from 'vue'
import { useLlmStore } from '@/stores/llm'
import { DEFAULT_PROMPT_TEMPLATE } from '@/utils/prompt'

const llm = useLlmStore()

// 变量说明列表
const variableList = [
  { name: '${emotionList}', desc: '当前可用的情绪标签列表（基于已安装的音色动态生成）' },
  { name: '${sfxSection}', desc: '音效库描述区块（列出可用音效）' },
  { name: '${bgmSection}', desc: '背景音乐库描述区块（列出可用背景音乐）' },
  { name: '${filterSection}', desc: '滤波器库描述区块（列出可用滤波器）' },
  { name: '${rawScript}', desc: '用户输入的小说原文（必须包含）' },
  { name: '${bgmExampleLine}', desc: '生成的背景音乐示例 JSON 行' },
  { name: '${sfxExample}', desc: '生成的音效示例 JSON 片段' },
]

function handleReset() {
  if (confirm('确定要恢复默认提示词模板吗？自定义修改将丢失。')) {
    llm.resetPrompt()
    // 如果重置后为空，自动填充默认模板以便用户查看
    if (!llm.customPromptTemplate) {
      llm.customPromptTemplate = DEFAULT_PROMPT_TEMPLATE
    }
  }
}

function handleSave() {
  llm.savePrompt()
  // 简单的保存成功提示，实际项目中可以使用 Toast
  const btn = document.activeElement as HTMLButtonElement
  if (btn) {
    const originalText = btn.innerText
    btn.innerText = '已保存'
    setTimeout(() => btn.innerText = originalText, 1000)
  }
}

// 初始化时如果自定义内容为空（且启用了自定义），可以预填默认值方便编辑
onMounted(() => {
  if (llm.useCustomPrompt && !llm.customPromptTemplate) {
    llm.customPromptTemplate = DEFAULT_PROMPT_TEMPLATE
  }
})
</script>

<template>
  <div class="space-y-6 max-w-5xl mx-auto pb-20">
    
    <!-- 头部说明 -->
    <div class="glass p-6 rounded-xl border border-white/20 shadow-sm relative overflow-hidden">
      <div class="relative z-10 flex justify-between items-start">
        <div>
          <h2 class="text-xl font-bold text-slate-800">提示词模板管理</h2>
          <p class="text-sm text-slate-500 mt-1 max-w-2xl">
            自定义 AI 分析剧本时使用的系统提示词。你可以调整角色分析规则、JSON 输出格式，或者补充额外约束。
          </p>
        </div>
        
        <!-- 开关 -->
        <div class="flex items-center gap-3 bg-white/50 px-4 py-2 rounded-full border border-white/40 shadow-sm">
          <span class="text-sm font-bold text-slate-700">启用自定义提示词</span>
          <button 
            @click="llm.useCustomPrompt = !llm.useCustomPrompt; llm.savePrompt()"
            class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
            :class="llm.useCustomPrompt ? 'bg-primary' : 'bg-slate-200'"
          >
            <span
              class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform duration-200 ease-in-out shadow-sm"
              :class="llm.useCustomPrompt ? 'translate-x-6' : 'translate-x-1'"
            />
          </button>
        </div>
      </div>
      
      <!-- 装饰背景 -->
      <div class="absolute -right-10 -bottom-10 w-40 h-40 bg-gradient-to-br from-primary/10 to-purple-500/10 rounded-full blur-2xl pointer-events-none"></div>
    </div>

    <!-- 编辑区域 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      
      <!-- 左侧：编辑器 -->
      <div class="lg:col-span-2 space-y-4">
        <div class="card p-1 relative group" :class="{ 'opacity-60 pointer-events-none grayscale': !llm.useCustomPrompt }">
          <textarea
            v-model="llm.customPromptTemplate"
            class="w-full h-[600px] p-4 text-sm font-mono leading-relaxed bg-slate-50 border-none outline-none resize-none rounded-lg focus:bg-white transition-colors text-slate-700"
            spellcheck="false"
            placeholder="在此输入提示词模板..."
          ></textarea>
          
          <!-- 悬浮保存栏 -->
          <div class="absolute bottom-4 right-4 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <button @click="handleReset" class="btn btn-ghost bg-white/80 backdrop-blur shadow-sm text-xs hover:bg-red-50 hover:text-red-600">
              ↺ 恢复默认
            </button>
            <button @click="handleSave" class="btn btn-primary shadow-lg text-xs">
              保存修改
            </button>
          </div>
        </div>
      </div>

      <!-- 右侧：变量说明 -->
      <div class="space-y-4">
        <div class="card p-5 sticky top-6">
          <h3 class="font-bold text-slate-700 mb-4">动态变量</h3>
          <p class="text-xs text-slate-500 mb-4">
            在模板中使用以下变量，分析时会自动替换为实际的资源列表或文本。
            <br>
            <span class="text-red-500 font-bold">* 必须包含 ${rawScript}</span>
          </p>
          
          <div class="space-y-3">
            <div v-for="v in variableList" :key="v.name" class="group relative bg-slate-50 hover:bg-white border border-transparent hover:border-primary/20 p-2.5 rounded-lg transition-all cursor-help">
              <code class="text-xs font-bold text-primary bg-primary/5 px-1.5 py-0.5 rounded border border-primary/10 block w-fit mb-1">{{ v.name }}</code>
              <p class="text-[10px] text-slate-500 leading-snug">{{ v.desc }}</p>
              
              <!-- Copy Hint -->
              <!-- <div class="absolute right-2 top-2 opacity-0 group-hover:opacity-100 text-[10px] text-slate-400">点击复制</div> -->
            </div>
          </div>

          <div class="mt-6 pt-4 border-t border-slate-100">
             <h4 class="text-xs font-bold text-slate-700 mb-2">使用说明</h4>
             <ul class="text-[10px] text-slate-500 space-y-1.5 list-disc pl-4">
               <li>提示词的质量会直接影响 AI 分析的准确率。</li>
               <li>请保留 JSON 格式说明部分，否则 AI 可能输出无法解析的文本。</li>
               <li>如果新增了 `角色#情绪` 格式的音色，AI 会自动感知新情绪。</li>
             </ul>
          </div>
        </div>
      </div>

    </div>

  </div>
</template>

<style scoped>
textarea {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}
</style>
