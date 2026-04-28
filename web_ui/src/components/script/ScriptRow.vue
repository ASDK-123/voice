<script setup lang="ts">
import { computed, watch } from 'vue'
import type { ScriptLine, BgmBlock } from '@/types'
// Alias ScriptLine as DialogueLine for clearer semantics in this component
type DialogueLine = ScriptLine 

import { useProjectStore } from '@/stores/project'
import { useAudioStore } from '@/stores/audio'
import { useLibrariesStore } from '@/stores/libraries'
import EmotionSelector from './EmotionSelector.vue'
import WaveformLine from './WaveformLine.vue'

// Defines props
const props = defineProps<{
  line: ScriptLine | BgmBlock // Accepts the union type
  index: number
}>()

const project = useProjectStore()
const audioStore = useAudioStore()
const libs = useLibrariesStore()

// Type Narrowing Helpers for Template
const bgmLine = computed(() => props.line.type === 'bgm' ? props.line as BgmBlock : null)
const dialogueLine = computed(() => props.line.type === 'dialogue' ? props.line as DialogueLine : null)

// Audio Lazy Loading Loop
watch(() => {
  if (props.line.type === 'dialogue') {
    return (props.line as DialogueLine).audioId
  }
  return undefined
}, async (newId) => {
  if (newId && props.line.type === 'dialogue') {
    const url = await audioStore.getAudioUrl(newId)
    // We modify the prop object directly (reactive), which is standard in Vue for object props
    if (url) {
      (props.line as DialogueLine).audioUrl = url
    }
  }
}, { immediate: true })

</script>

<template>
  <div
    class="group relative transition-all duration-200 mb-3 rounded-xl border border-transparent"
    :class="[
      project.selectedLineIndex === index 
        ? 'bg-white ring-2 ring-primary shadow-md z-10' 
        : 'bg-white/80 hover:bg-white border-white/40 hover:shadow-md shadow-sm',
      project.currentSequenceIndex === index ? 'ring-2 ring-green-400 bg-green-50' : ''
    ]"
    @click="project.selectedLineIndex = index"
  >
    <!-- ──── BGM 控制块 ──── -->
    <div v-if="bgmLine" class="flex items-center gap-3 p-3 bg-purple-50/50 rounded-xl border border-purple-100/50">
      <div class="flex flex-col items-center gap-0.5 w-6 flex-shrink-0">
        <button @click.stop="project.moveLineUp(Number(index))" class="text-[10px] text-slate-400 hover:text-primary transition-colors" :disabled="index === 0">▲</button>
        <span class="text-[10px] font-mono text-slate-300">{{ index + 1 }}</span>
        <button @click.stop="project.moveLineDown(Number(index))" class="text-[10px] text-slate-400 hover:text-primary transition-colors" :disabled="index === project.scriptLines.length - 1">▼</button>
      </div>

      <div class="flex-1 flex items-center gap-3">
        <span class="text-[10px] font-bold px-2 py-1 rounded-md bg-purple-100 text-purple-600 shadow-sm border border-purple-200">背景音乐</span>
        
        <select v-model="bgmLine.action" class="input text-xs w-24 bg-white border-transparent hover:border-purple-200">
          <option value="play">播放</option>
          <option value="stop">停止</option>
          <option value="fade_in">淡入</option>
          <option value="fade_out">淡出</option>
        </select>

        <select v-model="bgmLine.bgmName" class="input text-xs flex-1 bg-white border-transparent hover:border-purple-200 font-medium text-slate-600">
          <option value="" disabled>选择背景音乐</option>
          <option v-for="b in libs.bgmLibrary" :key="b.id" :value="b.name">{{ b.name }}</option>
        </select>

        <div class="flex items-center gap-2 bg-white px-2 py-1 rounded-lg border border-slate-100">
           <span class="text-[10px] text-slate-400">音量</span>
           <input type="range" v-model.number="bgmLine.volume" min="0" max="1" step="0.1" class="w-16 accent-purple-500" />
           <span class="text-[10px] w-6 text-right font-mono text-slate-500">{{ Math.round((bgmLine.volume || 0.4) * 100) }}%</span>
        </div>
      </div>

      <button @click.stop="project.removeScriptLine(line.id)" class="p-1.5 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-md transition-all">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
      </button>
    </div>

    <!-- ──── 台词行 ──── -->
    <div v-else-if="dialogueLine" class="flex gap-0 p-1">
      <!-- 1. 序号与移动 (极简侧边) -->
      <div class="flex flex-col items-center justify-center gap-1 w-8 flex-shrink-0 pt-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <button @click.stop="project.moveLineUp(Number(index))" class="text-[10px] text-slate-300 hover:text-primary p-1">▲</button>
        <span class="text-[10px] font-mono text-slate-300 select-none">{{ index + 1 }}</span>
        <button @click.stop="project.moveLineDown(Number(index))" class="text-[10px] text-slate-300 hover:text-primary p-1">▼</button>
        <button @click.stop="project.removeScriptLine(line.id)" class="mt-2 text-slate-300 hover:text-red-500 p-1">×</button>
      </div>

      <!-- 2. 内容区 -->
      <div class="flex-1 space-y-2 min-w-0 py-2 pr-4 pl-1">
        <!-- 第一行：角色与文本 -->
        <div class="flex items-start gap-3">
          <!-- 角色绑定 (左侧头像位) -->
          <div class="flex flex-col gap-1.5 w-32 flex-shrink-0 pt-1">
            <!-- 角色选择 -->
            <div class="relative">
               <select
                 v-model="dialogueLine.role"
                 class="appearance-none w-full text-xs font-bold bg-slate-100 hover:bg-slate-200 border-none rounded-lg px-2 py-1.5 cursor-pointer text-center text-slate-700 focus:ring-2 focus:ring-primary/20 transition-all"
                 :class="dialogueLine.role === '旁白' ? 'text-slate-500' : 'text-primary'"
               >
                 <option v-for="r in project.availableRoles" :key="r" :value="r">{{ r }}</option>
               </select>
            </div>
            
            <!-- 情绪选择器 (Apple Style P6) -->
            <EmotionSelector
               :character="project.characters.find(c => c.name === dialogueLine?.role)?.voiceId || dialogueLine?.role || ''"
               v-model="dialogueLine!.emotion"
               class="w-full"
            />

            <!-- 生成/播放控制 (P2) -->
             <div class="flex items-center gap-1 mt-0.5">
                <button 
                  @click="project.generateLineAudio(dialogueLine)"
                  :disabled="project.isGeneratingAll || dialogueLine.isGenerating"
                  class="btn btn-xs flex-1 text-[10px] px-0 h-6 rounded-md shadow-sm border border-transparent whitespace-nowrap flex items-center justify-center"
                  :class="dialogueLine.audioUrl 
                    ? 'bg-white text-slate-500 border-slate-200 hover:border-primary hover:text-primary' 
                    : 'bg-gradient-to-r from-primary to-cyan-500 text-white hover:shadow-md hover:-translate-y-0.5 transition-all'"
                  title="生成音频"
                >
                  {{ dialogueLine.isGenerating ? '处理中' : (dialogueLine.audioUrl ? '重新生成' : '生成音频') }}
                </button>
                <button 
                   v-if="dialogueLine.audioUrl" 
                   @click="project.playLineAudio(dialogueLine)"
                   class="w-6 h-6 flex items-center justify-center rounded-full bg-green-100 text-green-600 hover:bg-green-500 hover:text-white transition-all shadow-sm"
                >
                  <span v-if="project.auditioningId === dialogueLine.id">停</span>
                  <span v-else>播</span>
                </button>
             </div>
          </div>

          <!-- 文本输入 (无边框设计) -->
          <div class="flex-1 min-w-0">
            <textarea
              v-model="dialogueLine.text"
              class="w-full text-base text-slate-700 bg-transparent border-none focus:ring-0 active:outline-none p-0 resize-none leading-relaxed placeholder-slate-300 font-medium"
              rows="2"
              placeholder="在这里输入台词..."
              style="min-height: 60px;"
            ></textarea>

            <!-- 波形显示 + 音量 (P5.1) -->
            <div v-if="dialogueLine.audioUrl" class="mt-3 flex items-center gap-3 bg-slate-50/50 rounded-xl border border-slate-100 p-2 backdrop-blur-sm">
                 <WaveformLine 
                    :line="dialogueLine"
                    class="flex-1 h-10 opacity-80"
                 />
                 <div class="flex flex-col gap-1 flex-shrink-0" style="min-width: 100px;">
                    <div class="flex items-center gap-1 group/vol">
                      <span class="text-[9px] w-6 text-slate-400 font-bold tracking-wider">人声</span>
                      <input type="range" v-model.number="dialogueLine.dialogueVolume" min="0" max="1" step="0.05" class="w-16 h-1 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-primary" />
                    </div>
                    <div class="flex items-center gap-1 group/vol">
                      <span class="text-[9px] w-6 text-slate-400 font-bold tracking-wider">音效</span>
                      <input type="range" v-model.number="dialogueLine.sfxVolume" min="0" max="1" step="0.05" class="w-16 h-1 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-green-500" />
                    </div>
                 </div>
            </div>
          </div>
        </div>

        <!-- 第三行：音效标签 -->
        <div class="flex flex-wrap items-center gap-1">
          <div
            v-for="(sfx, sIdx) in dialogueLine.sfx"
            :key="sIdx"
            class="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded"
            style="background: rgba(var(--color-primary-rgb, 99, 102, 241), 0.1); border: 1px solid rgba(var(--color-primary-rgb, 99, 102, 241), 0.2);"
          >
            <select
              v-model="sfx.name"
              class="bg-transparent outline-none text-[10px] font-medium"
              style="max-width: 80px; color: var(--color-primary);"
            >
              <option v-for="s in libs.sfxLibrary" :key="s.id" :value="s.name">{{ s.name }}</option>
            </select>
            <span style="color: var(--color-text-secondary);">@</span>
            <input
              type="number" v-model.number="sfx.position" step="0.1" min="0" max="1"
              class="bg-transparent outline-none text-[10px] text-center" style="width: 30px;"
            />
            <button @click="dialogueLine.sfx.splice(sIdx, 1)" class="font-bold opacity-60 hover:opacity-100" style="color: var(--color-danger);">×</button>
          </div>
          <button
            @click="dialogueLine.sfx.push({ name: libs.sfxLibrary[0]?.name || '', position: 0.5 })"
            class="text-[10px] px-2 py-0.5 rounded opacity-60 hover:opacity-100"
            style="border: 1px dashed var(--color-border); color: var(--color-text-secondary);"
          >+ 音效</button>
        </div>
      </div>
    </div>
  </div>
</template>
