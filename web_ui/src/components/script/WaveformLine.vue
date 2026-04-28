<script setup lang="ts">
// 单行波形编辑器组件
// 显示 Canvas 波形 + trimStart/trimEnd 拖拽裁剪
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import type { ScriptLine } from '@/types'
import { useWaveformEditor } from '@/composables/useWaveformEditor'

const props = defineProps<{
  line: ScriptLine
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const { drawWaveform, startDragTrim } = useWaveformEditor(canvasRef)

// 解码后的 AudioBuffer 缓存
let audioBuffer: AudioBuffer | null = null
let audioCtx: AudioContext | null = null

/** 从 audioUrl 解码 AudioBuffer 并绘制波形 */
async function loadAndDraw() {
  if (!props.line.audioUrl || !canvasRef.value) return

  try {
    if (!audioCtx) {
      audioCtx = new AudioContext()
    }

    const response = await fetch(props.line.audioUrl)
    const arrayBuffer = await response.arrayBuffer()
    audioBuffer = await audioCtx.decodeAudioData(arrayBuffer)

    // 设置 Canvas 高分辨率
    const canvas = canvasRef.value
    if (canvas) {
      const dpr = window.devicePixelRatio || 1
      const rect = canvas.getBoundingClientRect()
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
      const ctx = canvas.getContext('2d')
      if (ctx) ctx.scale(dpr, dpr)
      // 重置 Canvas 尺寸为 CSS 像素
      canvas.width = rect.width
      canvas.height = rect.height
    }

    drawWaveform(audioBuffer, props.line.trimStart, props.line.trimEnd)
  } catch (e) {
    console.warn('波形加载失败:', e)
  }
}

/** 处理 Canvas 上的拖拽 */
function onPointerDown(event: PointerEvent) {
  if (!audioBuffer) return
  startDragTrim(event, audioBuffer, props.line)
}

// 监听 audioUrl 变化，自动重绘
watch(() => props.line.audioUrl, (newUrl) => {
  if (newUrl) {
    audioBuffer = null
    loadAndDraw()
  }
})

// 监听 trim 值变化重绘
watch(
  [() => props.line.trimStart, () => props.line.trimEnd],
  () => {
    if (audioBuffer) {
      drawWaveform(audioBuffer, props.line.trimStart, props.line.trimEnd)
    }
  },
)

onMounted(() => {
  if (props.line.audioUrl) loadAndDraw()
})

onBeforeUnmount(() => {
  audioBuffer = null
  if (audioCtx) {
    audioCtx.close()
    audioCtx = null
  }
})
</script>

<template>
  <div
    class="relative w-full rounded overflow-hidden cursor-col-resize"
    style="background: var(--color-surface-secondary); height: 48px; border: 1px solid var(--color-border);"
    @pointerdown="onPointerDown"
  >
    <canvas
      ref="canvasRef"
      class="w-full h-full"
      style="display: block;"
    />
    <!-- trim 数值标注 -->
    <div class="absolute bottom-0 left-1 text-[9px] font-mono opacity-50" style="color: var(--color-text-secondary);">
      {{ (props.line.trimStart * 100).toFixed(0) }}%
    </div>
    <div class="absolute bottom-0 right-1 text-[9px] font-mono opacity-50" style="color: var(--color-text-secondary);">
      {{ (props.line.trimEnd * 100).toFixed(0) }}%
    </div>
  </div>
</template>
