<script setup lang="ts">
// BGM 库管理组件
import { ref } from 'vue'
import { useLibrariesStore } from '@/stores/libraries'
import { createDefaultBgm } from '@/types'
import type { BgmItem } from '@/types'

const libs = useLibrariesStore()

const editingItem = ref<BgmItem | null>(null)
const pendingFile = ref<File | null>(null)

function openNew() {
  editingItem.value = createDefaultBgm()
  pendingFile.value = null
}

function edit(item: BgmItem) {
  editingItem.value = { ...item }
  pendingFile.value = null
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) {
    pendingFile.value = input.files[0]
    if (editingItem.value) {
      editingItem.value.filename = input.files[0].name
    }
  }
}

function save() {
  if (!editingItem.value || !editingItem.value.name.trim()) return
  libs.saveBgm(editingItem.value, pendingFile.value ?? undefined)
  editingItem.value = null
  pendingFile.value = null
}

function cancel() {
  editingItem.value = null
  pendingFile.value = null
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h3 class="text-base font-bold text-slate-700 flex items-center gap-2">
        <span>BGM</span> BGM 库
      </h3>
      <button @click="openNew()" class="btn btn-primary btn-sm rounded-full px-3">
        <span>＋</span> 添加
      </button>
    </div>

    <!-- 编辑表单 -->
    <transition name="fade">
      <div v-if="editingItem" class="card space-y-4 border-l-4 border-l-primary/50">
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="label">名称</label>
            <input v-model="editingItem.name" class="input" placeholder="如：战斗BGM" />
          </div>
          <div>
            <label class="label">音频文件</label>
            <input type="file" accept="audio/*" @change="onFileChange" class="input text-sm file:mr-4 file:py-1 file:px-3 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-primary/10 file:text-primary hover:file:bg-primary/20" />
          </div>
        </div>
        <div>
          <label class="label">描述（AI 分析用）</label>
          <input v-model="editingItem.description" class="input" placeholder="简要描述 BGM 氛围" />
        </div>
        <div class="flex items-center gap-2 pt-2">
          <label class="flex items-center gap-2 text-sm cursor-pointer select-none text-slate-600 hover:text-primary transition-colors">
            <input type="checkbox" v-model="editingItem.enabled" class="accent-primary w-4 h-4" />
            参与 AI 分析
          </label>
          <div class="flex-1" />
          <button @click="save()" class="btn btn-primary">保存</button>
          <button @click="cancel()" class="btn btn-ghost">取消</button>
        </div>
      </div>
    </transition>

    <!-- 列表 -->
    <div v-if="libs.bgmLibrary.length === 0 && !editingItem" class="text-center py-8 text-slate-400 bg-slate-50 rounded-xl border border-dashed border-slate-200">
      暂无 BGM，点击右上角添加
    </div>
    
    <div v-else class="space-y-2">
      <div v-for="item in libs.bgmLibrary" :key="item.id"
        class="group flex items-center justify-between p-3 rounded-xl bg-white border border-slate-100 shadow-sm hover:shadow-md hover:border-primary/20 transition-all duration-200"
      >
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 text-xs">BGM</div>
          <div>
            <div class="font-medium text-slate-700">{{ item.name }}</div>
            <div class="text-xs text-slate-400 font-mono">{{ item.filename || '未上传文件' }}</div>
          </div>
        </div>
        
        <div class="flex gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
          <button
            v-if="item.filename && libs.localFileMap.has(item.filename)"
            @click.stop="libs.previewingId === item.id ? libs.stopPreview() : libs.startPreview(item.id, item.filename)"
            class="btn btn-ghost p-1.5 text-primary hover:bg-primary/10 rounded-lg"
            :title="libs.previewingId === item.id ? '停止试听' : '试听'"
          >{{ libs.previewingId === item.id ? '停' : '播' }}</button>
          <button @click="edit(item)" class="btn btn-ghost p-1.5 text-slate-500 hover:text-primary hover:bg-slate-100 rounded-lg">✎</button>
          <button @click="libs.deleteBgm(item.id)" class="btn btn-ghost p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>
