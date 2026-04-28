// 波形编辑器 Composable
// Canvas 上绘制音频波形 + 剪辑区域拖拽

import type { Ref } from 'vue'
import type { ScriptLine } from '@/types'

export function useWaveformEditor(canvasRef: Ref<HTMLCanvasElement | null>) {

    /** 绘制波形 + 剪辑遮罩 + 进度指示线 */
    function drawWaveform(
        buffer: AudioBuffer,
        trimStart: number,
        trimEnd: number,
        progress?: number,
    ) {
        const canvas = canvasRef.value
        if (!canvas) return

        const ctx = canvas.getContext('2d')
        if (!ctx) return

        const w = canvas.width
        const h = canvas.height
        const data = buffer.getChannelData(0)

        // 清空
        ctx.clearRect(0, 0, w, h)

        // 绘制波形
        const step = Math.ceil(data.length / w)
        const halfH = h / 2

        ctx.beginPath()
        ctx.strokeStyle = '#6366f1'
        ctx.lineWidth = 1

        for (let i = 0; i < w; i++) {
            let min = 1.0
            let max = -1.0
            for (let j = 0; j < step; j++) {
                const idx = i * step + j
                if (idx < data.length) {
                    const val = data[idx] ?? 0
                    if (val < min) min = val
                    if (val > max) max = val
                }
            }
            const yMin = (1 + min) * halfH
            const yMax = (1 + max) * halfH
            ctx.moveTo(i, yMin)
            ctx.lineTo(i, yMax)
        }
        ctx.stroke()

        // 绘制剪辑遮罩（灰色半透明）
        ctx.fillStyle = 'rgba(0, 0, 0, 0.45)'
        // 左侧遮罩
        const trimStartX = trimStart * w
        const trimEndX = trimEnd * w
        ctx.fillRect(0, 0, trimStartX, h)
        // 右侧遮罩
        ctx.fillRect(trimEndX, 0, w - trimEndX, h)

        // 绘制剪辑边界线
        ctx.strokeStyle = '#f59e0b'
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(trimStartX, 0)
        ctx.lineTo(trimStartX, h)
        ctx.moveTo(trimEndX, 0)
        ctx.lineTo(trimEndX, h)
        ctx.stroke()

        // 绘制播放进度线
        if (progress !== undefined && progress > 0) {
            const progressX = (trimStart + (trimEnd - trimStart) * progress) * w
            ctx.strokeStyle = '#3b82f6'
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.moveTo(progressX, 0)
            ctx.lineTo(progressX, h)
            ctx.stroke()
        }
    }

    /** 开始拖拽剪辑 */
    function startDragTrim(
        event: PointerEvent,
        buffer: AudioBuffer,
        line: ScriptLine,
    ) {
        const canvas = canvasRef.value
        if (!canvas) return

        const rect = canvas.getBoundingClientRect()
        const x = (event.clientX - rect.left) / rect.width

        // 增加阈值检测 (5%)，防止误触
        const distStart = Math.abs(x - line.trimStart)
        const distEnd = Math.abs(x - line.trimEnd)
        const threshold = 0.05

        // 如果点击位置距离两端都太远，不触发拖拽
        if (distStart > threshold && distEnd > threshold) return

        // 判断拖拽 trimStart 还是 trimEnd
        const side = distStart < distEnd ? 'start' : 'end'

        // 设置鼠标样式
        document.body.style.cursor = 'col-resize'

        const onMove = (ev: PointerEvent) => {
            // 重新获取 rect 以防页面滚动导致坐标偏移
            const currentRect = canvas.getBoundingClientRect()
            const pos = Math.max(0, Math.min(1,
                (ev.clientX - currentRect.left) / currentRect.width,
            ))

            if (side === 'start') {
                // start 不能超过 end
                line.trimStart = Math.min(pos, line.trimEnd - 0.01)
            } else {
                // end 不能小于 start
                line.trimEnd = Math.max(pos, line.trimStart + 0.01)
            }
            drawWaveform(buffer, line.trimStart, line.trimEnd)
        }

        const onUp = () => {
            window.removeEventListener('pointermove', onMove)
            window.removeEventListener('pointerup', onUp)
            document.body.style.cursor = ''
        }

        window.addEventListener('pointermove', onMove)
        window.addEventListener('pointerup', onUp)
    }

    return {
        drawWaveform,
        startDragTrim,
    }
}
