<script setup lang="ts">
// 音色库管理组件
import { ref } from 'vue'
import { useLibrariesStore } from '@/stores/libraries'
import type { TimbreItem } from '@/types'

const libs = useLibrariesStore()

const editingItem = ref<TimbreItem | null>(null)
const pendingFile = ref<File | null>(null)

function openNew() {
  editingItem.value = {
    id: `timbre_${Date.now()}`,
    name: '',
    description: '',
    refPath: '',
  }
  pendingFile.value = null
}

function edit(item: TimbreItem) {
  editingItem.value = { ...item }
  pendingFile.value = null
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) {
    pendingFile.value = input.files[0]
    if (editingItem.value) {
      editingItem.value.refPath = input.files[0].name
    }
  }
}

function save() {
  if (!editingItem.value || !editingItem.value.name.trim()) return
  libs.saveTimbre(editingItem.value, pendingFile.value ?? undefined)
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
        <span>音色</span> 音色库
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
            <label class="label">音色名称</label>
            <input v-model="editingItem.name" class="input" placeholder="如：温柔女声" />
          </div>
          <div>
            <label class="label">参考音频</label>
            <input type="file" accept="audio/*" @change="onFileChange" class="input text-sm file:mr-4 file:py-1 file:px-3 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-primary/10 file:text-primary hover:file:bg-primary/20" />
          </div>
        </div>
        <div>
          <label class="label">描述</label>
          <input v-model="editingItem.description" class="input" placeholder="音色特点描述" />
        </div>
        <div class="flex gap-2 justify-end pt-2">
          <button @click="save()" class="btn btn-primary">保存</button>
          <button @click="cancel()" class="btn btn-ghost">取消</button>
        </div>
      </div>
    </transition>

    <!-- 列表 -->
    <div v-if="libs.timbres.length === 0 && !editingItem" class="text-center py-8 text-slate-400 bg-slate-50 rounded-xl border border-dashed border-slate-200">
      暂无音色，点击右上角添加
    </div>
    
    <div v-else class="space-y-2">
      <div v-for="item in libs.timbres" :key="item.id"
        class="group flex items-center justify-between p-3 rounded-xl bg-white border border-slate-100 shadow-sm hover:shadow-md hover:border-primary/20 transition-all duration-200"
      >
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 text-xs">VOICE</div>
          <div>
            <div class="font-medium text-slate-700">{{ item.name }}</div>
            <div class="text-xs text-slate-400 font-mono">{{ item.refPath || '未上传参考音频' }}</div>
          </div>
        </div>
        
        <div class="flex gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
          <button @click="edit(item)" class="btn btn-ghost p-1.5 text-slate-500 hover:text-primary hover:bg-slate-100 rounded-lg">✎</button>
          <button @click="libs.deleteTimbre(item.id)" class="btn btn-ghost p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>
