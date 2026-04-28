<script setup lang="ts">
// 滤波器库管理组件
import { ref } from 'vue'
import { useLibrariesStore } from '@/stores/libraries'
import { createDefaultFilter } from '@/types'
import type { FilterItem, FilterType } from '@/types'

const libs = useLibrariesStore()
const editingItem = ref<FilterItem | null>(null)

const filterTypes: { value: FilterType; label: string }[] = [
  { value: 'lowpass', label: '低通 (Lowpass)' },
  { value: 'highpass', label: '高通 (Highpass)' },
  { value: 'bandpass', label: '带通 (Bandpass)' },
  { value: 'lowshelf', label: '低架 (Low Shelf)' },
  { value: 'highshelf', label: '高架 (High Shelf)' },
  { value: 'peaking', label: '峰值 (Peaking)' },
  { value: 'notch', label: '陷波 (Notch)' },
  { value: 'allpass', label: '全通 (Allpass)' },
  { value: 'distortion', label: '失真 (Distortion)' },
]

function openNew() {
  editingItem.value = createDefaultFilter()
}

function edit(item: FilterItem) {
  editingItem.value = { ...item }
}

function save() {
  if (!editingItem.value || !editingItem.value.name.trim()) return
  libs.saveFilter(editingItem.value)
  editingItem.value = null
}

function cancel() {
  editingItem.value = null
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h3 class="text-base font-bold text-slate-700 flex items-center gap-2">
        <span>🎛️</span> 滤波器库
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
            <input v-model="editingItem.name" class="input" placeholder="如：电话效果" />
          </div>
          <div>
            <label class="label">类型</label>
            <select v-model="editingItem.type" class="input appearance-none">
              <option v-for="ft in filterTypes" :key="ft.value" :value="ft.value">
                {{ ft.label }}
              </option>
            </select>
          </div>
        </div>
        <div class="grid grid-cols-3 gap-4">
          <div>
            <label class="label">频率 (Hz)</label>
            <input v-model.number="editingItem.frequency" type="number" class="input" />
          </div>
          <div>
            <label class="label">Q 值</label>
            <input v-model.number="editingItem.Q" type="number" step="0.1" class="input" />
          </div>
          <div>
            <label class="label">{{ editingItem.type === 'distortion' ? '失真量' : '增益 (dB)' }}</label>
            <input v-model.number="editingItem.gain" type="number" step="0.5" class="input" />
          </div>
        </div>
        <div>
          <label class="label">描述（AI 分析用）</label>
          <input v-model="editingItem.description" class="input" placeholder="效果描述" />
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
    <div v-if="libs.filterLibrary.length === 0 && !editingItem" class="text-center py-8 text-slate-400 bg-slate-50 rounded-xl border border-dashed border-slate-200">
      暂无滤波器，点击右上角添加
    </div>
    
    <div v-else class="space-y-2">
      <div v-for="item in libs.filterLibrary" :key="item.id"
        class="group flex items-center justify-between p-3 rounded-xl bg-white border border-slate-100 shadow-sm hover:shadow-md hover:border-primary/20 transition-all duration-200"
      >
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 text-xs">FX</div>
          <div>
            <div class="font-medium text-slate-700">{{ item.name }}</div>
            <div class="text-xs text-slate-400 font-mono">
              {{ filterTypes.find(f => f.value === item.type)?.label }} · {{ item.frequency }}Hz
            </div>
          </div>
        </div>
        
        <div class="flex gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
          <button @click="edit(item)" class="btn btn-ghost p-1.5 text-slate-500 hover:text-primary hover:bg-slate-100 rounded-lg">✎</button>
          <button @click="libs.deleteFilter(item.id)" class="btn btn-ghost p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>
