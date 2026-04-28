<script setup lang="ts">
// TTS 配置管理面板
import { useTtsStore } from '@/stores/tts'

const tts = useTtsStore()
</script>

<template>
  <div class="space-y-6">
    <!-- 配置表单 -->
    <div class="card space-y-4">
      <h2 class="text-lg font-bold text-slate-700 border-b border-slate-100 pb-2">
        {{ tts.isEditing ? '编辑 TTS 配置' : '添加 TTS 配置' }}
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="label">配置名称</label>
          <input v-model="tts.form.name" class="input" placeholder="如：本地 CosyVoice" />
        </div>
        <div>
          <label class="label">CosyVoice v2 后端地址</label>
          <input v-model="tts.form.baseUrl" class="input" placeholder="http://localhost:9880" />
        </div>
        <div class="md:col-span-2">
          <label class="label">API Key（可选）</label>
          <input
            v-model="tts.form.apiKey"
            class="input font-mono"
            placeholder="留空表示不启用 X-API-Key"
            type="password"
          />
        </div>
      </div>
      <div class="flex gap-3 mt-4 pt-2 border-t border-slate-100">
        <button @click="tts.saveConfig()" class="btn btn-primary">
          {{ tts.isEditing ? '更新' : '保存' }}
        </button>
        <button v-if="tts.isEditing" @click="tts.resetForm()" class="btn btn-ghost">
          取消
        </button>
      </div>
    </div>

    <!-- 配置列表 -->
    <div class="space-y-3">
      <h2 class="text-base font-bold text-slate-700 px-1">
        已保存配置
      </h2>
      <div v-if="tts.configs.length === 0" class="text-sm text-slate-400 italic px-1">
        暂无配置，请添加 CosyVoice v2 后端地址
      </div>
      <div v-else class="grid grid-cols-1 gap-3">
        <div
          v-for="cfg in tts.configs"
          :key="cfg.id"
          class="group flex items-center justify-between p-4 rounded-xl border transition-all cursor-pointer shadow-sm hover:shadow-md"
          :class="[
            tts.currentConfigId === cfg.id 
              ? 'bg-primary/5 border-primary ring-1 ring-primary' 
              : 'bg-white border-slate-100 hover:border-primary/30'
          ]"
          @click="tts.currentConfigId = cfg.id"
        >
          <div class="flex-1 min-w-0" @click="tts.currentConfigId = cfg.id">
            <div class="font-bold text-slate-700 text-base">
              {{ cfg.name }}
            </div>
            <div class="text-xs mt-1 text-slate-500 font-mono">
              {{ cfg.baseUrl }}
            </div>
            <div class="text-[11px] mt-1 text-slate-400">
              鉴权: {{ cfg.apiKey ? '已启用' : '未启用' }}
            </div>
          </div>
          <div class="flex gap-1 flex-shrink-0 ml-4 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
            <button @click.stop="tts.editConfig(cfg.id)" class="btn btn-ghost p-1.5 text-slate-500 hover:text-primary hover:bg-slate-100 rounded-lg">
              ✎
            </button>
            <button @click.stop="tts.deleteConfig(cfg.id)" class="btn btn-ghost p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg">
              ✕
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 连接状态 -->
    <div class="card bg-slate-50 border-slate-200">
      <h2 class="text-sm font-bold text-slate-500 uppercase tracking-wide mb-2">
        连接状态
      </h2>
      <div v-if="!tts.currentConfig" class="text-sm text-slate-400">
        请选择一个 TTS 配置
      </div>
      <div v-else class="text-sm text-slate-600 font-mono flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
        当前后端: <span class="font-bold text-primary">{{ tts.currentConfig.baseUrl }}</span>
        <span class="text-xs text-slate-400">
          {{ tts.currentConfig.apiKey ? 'X-API-Key 已启用' : '未启用鉴权' }}
        </span>
        <span class="text-xs text-slate-400 ml-auto">（仅支持 CosyVoice v2 协议）</span>
      </div>
    </div>
  </div>
</template>
