<script setup lang="ts">
// LLM 配置管理面板
import { useLlmStore } from '@/stores/llm'

const llm = useLlmStore()
</script>

<template>
  <div class="space-y-6">
    <!-- 配置表单 -->
    <div class="card space-y-4">
      <h2 class="text-lg font-bold text-slate-700 border-b border-slate-100 pb-2">
        {{ llm.isEditing ? '编辑 LLM 配置' : '添加 LLM 配置' }}
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="label">配置名称</label>
          <input v-model="llm.form.name" class="input" placeholder="如：Gemini Pro" />
        </div>
        <div>
          <label class="label">接口地址（Base URL）</label>
          <input v-model="llm.form.baseUrl" class="input" placeholder="https://..." />
        </div>
        <div>
          <label class="label">接口密钥（API Key）</label>
          <input v-model="llm.form.key" type="password" class="input" placeholder="sk-..." />
        </div>

        <!-- 模型选择区域 -->
        <div>
          <label class="label">模型</label>
          <div class="flex gap-2">
            <div class="flex-1 relative">
              <!-- 有模型列表时显示下拉框 -->
              <select
                v-if="llm.availableModels.length > 0"
                v-model="llm.form.model"
                class="input pr-8 appearance-none cursor-pointer"
              >
                <option value="" disabled>-- 选择模型 --</option>
                <option v-for="m in llm.availableModels" :key="m" :value="m">
                  {{ m }}
                </option>
              </select>
              <!-- 无模型列表时显示手动输入框 -->
              <input
                v-else
                v-model="llm.form.model"
                class="input"
                placeholder="填写地址和密钥后点击查询"
              />
            </div>
            <button
              @click="llm.fetchModels()"
              :disabled="llm.modelsFetching"
              class="btn btn-ghost text-xs px-3 flex-shrink-0 whitespace-nowrap border border-slate-200 hover:border-primary hover:bg-primary/5"
              :title="llm.modelsFetching ? '查询中...' : '查询可用模型'"
            >
              {{ llm.modelsFetching ? '查询中...' : '查询模型' }}
            </button>
          </div>
          <!-- 错误提示 -->
          <div v-if="llm.modelsError" class="text-xs mt-1 text-red-500">
            {{ llm.modelsError }}
          </div>
          <!-- 模型数量提示 -->
          <div v-else-if="llm.availableModels.length > 0" class="text-xs mt-1 text-green-500">
            已找到 {{ llm.availableModels.length }} 个可用模型
          </div>
        </div>

        <div class="md:col-span-2">
          <label class="label">额外参数（JSON）</label>
          <input v-model="llm.form.params" class="input font-mono text-xs" placeholder='{"temperature": 0.7}' />
        </div>
      </div>
      <div class="flex gap-3 mt-4 pt-2 border-t border-slate-100">
        <button @click="llm.saveConfig()" class="btn btn-primary">
          {{ llm.isEditing ? '更新' : '保存' }}
        </button>
        <button v-if="llm.isEditing" @click="llm.resetForm()" class="btn btn-ghost">
          取消
        </button>
      </div>
    </div>

    <!-- 配置列表 -->
    <div class="space-y-3">
      <h2 class="text-base font-bold text-slate-700 px-1">
        已保存配置
      </h2>
      <div v-if="llm.configs.length === 0" class="text-sm text-slate-400 italic px-1">
        暂无配置，请添加
      </div>
      <div v-else class="grid grid-cols-1 gap-3">
        <div
          v-for="cfg in llm.configs"
          :key="cfg.id"
          class="group flex items-center justify-between p-4 rounded-xl border transition-all cursor-pointer shadow-sm hover:shadow-md"
          :class="[
            llm.currentConfigId === cfg.id 
              ? 'bg-primary/5 border-primary ring-1 ring-primary' 
              : 'bg-white border-slate-100 hover:border-primary/30'
          ]"
          @click="llm.currentConfigId = cfg.id"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span
                v-if="llm.currentConfigId === cfg.id"
                class="text-xs px-2 py-0.5 rounded-full font-bold bg-primary text-white shadow-sm"
              >
                当前
              </span>
              <span class="font-bold text-slate-700 truncate text-base">
                {{ cfg.name }}
              </span>
            </div>
            <div class="text-xs mt-1 truncate text-slate-500 font-mono">
              {{ cfg.model }} · {{ cfg.baseUrl }}
            </div>
          </div>
          <div class="flex gap-1 flex-shrink-0 ml-4 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
            <button @click.stop="llm.editConfig(cfg.id)" class="btn btn-ghost p-1.5 text-slate-500 hover:text-primary hover:bg-slate-100 rounded-lg">
              ✎
            </button>
            <button @click.stop="llm.deleteConfig(cfg.id)" class="btn btn-ghost p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg">
              ✕
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
