// Web Audio 音频引擎 Composable
// 管理全局 AudioContext、滤波器链、BGM 控制、顺序播放、离线渲染

import { ref } from 'vue'
import type { ScriptLine, ScriptEntry, FilterItem } from '@/types'
import { isDialogue, isBgm } from '@/types'
import { useLibrariesStore } from '@/stores/libraries'
import { useAudioStore } from '@/stores/audio'
import { makeDistortionCurve } from '@/utils/audio'

/** 播放选项 */
interface PlayOptions {
    onProgress?: (progress: number) => void
    onEnded?: () => void
}

// ── 全局单例 ──
let audioCtx: AudioContext | null = null
const audioBufferCache = new Map<string, AudioBuffer>()

function getAudioContext(): AudioContext {
    if (!audioCtx) {
        audioCtx = new AudioContext()
    }
    // 恢复 suspended 状态（Chrome autoplay 策略）
    if (audioCtx.state === 'suspended') {
        audioCtx.resume()
    }
    return audioCtx
}

// ── 当前播放状态 ──
let currentSource: AudioBufferSourceNode | null = null
let currentGain: GainNode | null = null
let bgmSource: AudioBufferSourceNode | null = null
let bgmGain: GainNode | null = null
let sequenceAbort = false

export function useAudioEngine() {
    const isPlaying = ref(false)
    const currentPlayingId = ref<string | null>(null)

    const audioStore = useAudioStore()

    // ── 加载音频缓冲区 ──

    async function loadAudioBuffer(src: string | Blob): Promise<AudioBuffer | null> {
        const ctx = getAudioContext()

        // 字符串缓存 key
        const cacheKey = typeof src === 'string' ? src : ''
        if (cacheKey && audioBufferCache.has(cacheKey)) {
            return audioBufferCache.get(cacheKey)!
        }

        try {
            let arrayBuf: ArrayBuffer
            if (typeof src === 'string') {
                if (src.startsWith('blob:') || src.startsWith('http')) {
                    const res = await fetch(src)
                    arrayBuf = await res.arrayBuffer()
                } else {
                    // 尝试从 localFileMap 获取
                    const libs = useLibrariesStore()
                    const blob = libs.getFileBlob(src)
                    if (!blob) return null
                    arrayBuf = await blob.arrayBuffer()
                }
            } else {
                arrayBuf = await src.arrayBuffer()
            }

            const buffer = await ctx.decodeAudioData(arrayBuf)
            if (cacheKey) {
                audioBufferCache.set(cacheKey, buffer)
            }
            return buffer
        } catch (e) {
            console.error('音频加载失败:', e)
            return null
        }
    }

    // ── 构建滤波器链 ──

    function buildFilterChain(
        ctx: BaseAudioContext,
        source: AudioBufferSourceNode,
        filter: FilterItem | null,
    ): AudioNode {
        let lastNode: AudioNode = source

        if (filter) {
            if (filter.type === 'distortion') {
                const ws = ctx.createWaveShaper()
                ws.curve = makeDistortionCurve(filter.gain) as Float32Array<ArrayBuffer>
                ws.oversample = '4x'
                lastNode.connect(ws)
                lastNode = ws
            } else {
                const bq = ctx.createBiquadFilter()
                bq.type = filter.type as BiquadFilterType
                bq.frequency.value = filter.frequency
                bq.Q.value = filter.Q
                if (['lowshelf', 'highshelf', 'peaking'].includes(filter.type)) {
                    bq.gain.value = filter.gain
                }
                lastNode.connect(bq)
                lastNode = bq
            }
        }

        return lastNode
    }

    // ── 播放单行台词 ──

    async function playLine(line: ScriptLine, options?: PlayOptions): Promise<void> {
        if (!line.audioUrl) return

        stopPlayback()

        const ctx = getAudioContext()
        const buffer = await loadAudioBuffer(line.audioUrl)
        if (!buffer) return

        // 计算剪辑范围
        const startSec = buffer.duration * line.trimStart
        const endSec = buffer.duration * line.trimEnd
        const duration = endSec - startSec
        if (duration <= 0) return

        // 创建播放源
        const source = ctx.createBufferSource()
        source.buffer = buffer

        // 查找滤波器
        const libs = useLibrariesStore()
        const filterItem = line.filter ? libs.getFilterByName(line.filter) ?? null : null

        // 构建滤波器链
        const lastFilterNode = buildFilterChain(ctx, source, filterItem)

        // 增益节点（台词音量）
        const gain = ctx.createGain()
        gain.gain.value = line.dialogueVolume ?? 1.0
        lastFilterNode.connect(gain)
        gain.connect(ctx.destination)

        // 保存引用
        currentSource = source
        currentGain = gain
        isPlaying.value = true
        currentPlayingId.value = line.id
            ; (audioStore as any).isAuditioningId = line.id

        // 播放进度跟踪
        let progressTimer: ReturnType<typeof setInterval> | null = null
        if (options?.onProgress) {
            const startTime = ctx.currentTime
            progressTimer = setInterval(() => {
                const elapsed = ctx.currentTime - startTime
                const p = Math.min(1, elapsed / duration)
                options.onProgress!(p)
                    ; (audioStore as any).playbackProgress = p
            }, 50)
        }

        // 结束回调
        source.onended = () => {
            if (progressTimer) clearInterval(progressTimer)
            isPlaying.value = false
            currentPlayingId.value = null
            currentSource = null
            currentGain = null
                ; (audioStore as any).isAuditioningId = ''
                ; (audioStore as any).playbackProgress = 0
            options?.onEnded?.()
        }

        // 播放 SFX
        if (line.sfx && line.sfx.length > 0) {
            for (const sfxItem of line.sfx) {
                const sfxBlob = libs.getFileBlob(libs.getSfxByName(sfxItem.name)?.filename ?? '')
                if (sfxBlob) {
                    const sfxBuf = await loadAudioBuffer(sfxBlob)
                    if (sfxBuf) {
                        const sfxSource = ctx.createBufferSource()
                        sfxSource.buffer = sfxBuf
                        const sfxGain = ctx.createGain()
                        sfxGain.gain.value = line.sfxVolume ?? 0.5
                        sfxSource.connect(sfxGain)
                        sfxGain.connect(ctx.destination)
                        // SFX 按比例位置触发
                        const sfxDelay = duration * sfxItem.position
                        sfxSource.start(ctx.currentTime + sfxDelay)
                    }
                }
            }
        }

        // 开始播放
        source.start(0, startSec, duration)

        // 等待播放完成
        return new Promise(resolve => {
            const originalOnEnded = source.onended
            source.onended = (ev) => {
                if (originalOnEnded && typeof originalOnEnded === 'function') {
                    originalOnEnded.call(source, ev)
                }
                resolve()
            }
        })
    }

    // ── 停止播放 ──

    function stopPlayback() {
        if (currentSource) {
            try { currentSource.stop() } catch { /* 忽略 */ }
            currentSource = null
        }
        if (currentGain) {
            currentGain.disconnect()
            currentGain = null
        }
        isPlaying.value = false
        currentPlayingId.value = null
            ; (audioStore as any).isAuditioningId = ''
            ; (audioStore as any).playbackProgress = 0
    }

    // ── BGM 控制 ──

    async function playBgm(name: string, volume = 0.4): Promise<void> {
        stopBgm(0)

        const libs = useLibrariesStore()
        const bgmItem = libs.getBgmByName(name)
        if (!bgmItem) return

        const blob = libs.getFileBlob(bgmItem.filename)
        if (!blob) return

        const buffer = await loadAudioBuffer(blob)
        if (!buffer) return

        const ctx = getAudioContext()
        const source = ctx.createBufferSource()
        source.buffer = buffer
        source.loop = true

        const gain = ctx.createGain()
        gain.gain.value = 0 // 淡入起始
        source.connect(gain)
        gain.connect(ctx.destination)

        bgmSource = source
        bgmGain = gain

        source.start()

        // 2 秒淡入
        gain.gain.linearRampToValueAtTime(volume, ctx.currentTime + 2)
    }

    function stopBgm(fadeOutSec = 2) {
        if (!bgmSource || !bgmGain) return

        const ctx = getAudioContext()
        if (fadeOutSec > 0) {
            bgmGain.gain.linearRampToValueAtTime(0, ctx.currentTime + fadeOutSec)
            const src = bgmSource
            setTimeout(() => {
                try { src.stop() } catch { /* 忽略 */ }
            }, fadeOutSec * 1000 + 100)
        } else {
            try { bgmSource.stop() } catch { /* 忽略 */ }
        }

        bgmSource = null
        bgmGain = null
    }

    // ── 顺序播放 ──

    async function playSequence(lines: ScriptEntry[], startIndex = 0): Promise<void> {
        sequenceAbort = false
            ; (audioStore as any).isSequencePlaying = true

        for (let i = startIndex; i < lines.length; i++) {
            if (sequenceAbort) break

                ; (audioStore as any).currentSequenceIndex = i
            const entry = lines[i]!

            if (isBgm(entry)) {
                if (entry.action === 'play') {
                    await playBgm(entry.bgmName, entry.volume)
                } else {
                    stopBgm()
                }
                continue
            }

            if (isDialogue(entry) && entry.audioUrl) {
                await playLine(entry)

                // 行后停顿
                if (!sequenceAbort && entry.break_duration > 0) {
                    await new Promise(r => setTimeout(r, entry.break_duration * 1000))
                }
            }
        }

        ; (audioStore as any).isSequencePlaying = false
            ; (audioStore as any).currentSequenceIndex = -1
        stopBgm()
    }

    function stopSequence() {
        sequenceAbort = true
        stopPlayback()
        stopBgm()
            ; (audioStore as any).isSequencePlaying = false
            ; (audioStore as any).currentSequenceIndex = -1
    }

    // ── 离线渲染 ──

    async function renderOffline(lines: ScriptEntry[]): Promise<AudioBuffer | null> {
        // 第一遍：计算总时长并预加载台词音频
        let totalDuration = 0
        const timelineEvents: {
            line: ScriptLine;
            startTime: number;
            duration: number; // 实际播放时长 (trim后)
            buffer: AudioBuffer;
        }[] = []

        // 临时缓存 BGM Buffer 避免重复加载
        const bgmBuffers = new Map<string, AudioBuffer>()
        // 临时缓存 SFX Buffer
        const sfxBuffers = new Map<string, AudioBuffer>()
        const libs = useLibrariesStore()

        for (const entry of lines) {
            if (isDialogue(entry)) {
                let duration = 0
                if (entry.audioUrl) {
                    const buf = await loadAudioBuffer(entry.audioUrl)
                    if (buf) {
                        const trimDur = buf.duration * (entry.trimEnd - entry.trimStart)
                        timelineEvents.push({
                            line: entry,
                            startTime: totalDuration,
                            duration: trimDur,
                            buffer: buf,
                        })
                        duration = trimDur
                    }
                }
                totalDuration += duration + (entry.break_duration || 0)
            }
        }

        // 加上结尾缓冲 (2s) 避免混响截断
        totalDuration += 2.0

        if (totalDuration <= 0) return null

        const sampleRate = 44100
        const offlineCtx = new OfflineAudioContext(2, Math.ceil(totalDuration * sampleRate), sampleRate)

        // 辅助：调度 BGM 片段
        async function scheduleBgmSegment(name: string, start: number, end: number, volume: number) {
            if (end <= start) return
            let buf: AudioBuffer | null | undefined = bgmBuffers.get(name)
            if (!buf) {
                const item = libs.getBgmByName(name)
                if (item) {
                    const b = libs.getFileBlob(item.filename)
                    if (b) buf = await loadAudioBuffer(b)
                }
            }
            if (buf) {
                bgmBuffers.set(name, buf) // 缓存
                const src = offlineCtx.createBufferSource()
                src.buffer = buf
                src.loop = true

                const gain = offlineCtx.createGain()
                // 淡入淡出 (2s)
                const fadeIn = 2
                const fadeOut = 2

                // 初始音量 0
                gain.gain.setValueAtTime(0, start)
                // 淡入到 volume
                gain.gain.linearRampToValueAtTime(volume, Math.min(start + fadeIn, end))

                // 保持 volume
                gain.gain.setValueAtTime(volume, Math.max(start, end - fadeOut))
                // 淡出到 0
                gain.gain.linearRampToValueAtTime(0, end)

                src.connect(gain)
                gain.connect(offlineCtx.destination)

                src.start(start)
                src.stop(end + fadeOut) // 延长一点以完成淡出
            }
        }

        // 第二遍：调度所有音频源

        // 1. 调度台词 & SFX
        for (const ev of timelineEvents) {
            // (1) 台词
            const source = offlineCtx.createBufferSource()
            source.buffer = ev.buffer

            // 滤波器 & 音量
            const filterItem = ev.line.filter ? libs.getFilterByName(ev.line.filter) ?? null : null
            const lastNode = buildFilterChain(offlineCtx, source, filterItem)

            const gain = offlineCtx.createGain()
            gain.gain.value = ev.line.dialogueVolume ?? 1.0
            lastNode.connect(gain)
            gain.connect(offlineCtx.destination)

            const startOffset = ev.buffer.duration * ev.line.trimStart
            source.start(ev.startTime, startOffset, ev.duration)

            // (2) SFX
            if (ev.line.sfx && ev.line.sfx.length > 0) {
                for (const sfxItem of ev.line.sfx) {
                    let sfxBuf: AudioBuffer | null | undefined = sfxBuffers.get(sfxItem.name)
                    if (!sfxBuf) {
                        const item = libs.getSfxByName(sfxItem.name)
                        if (item) {
                            const b = libs.getFileBlob(item.filename)
                            if (b) sfxBuf = await loadAudioBuffer(b)
                        }
                    }
                    if (sfxBuf) {
                        sfxBuffers.set(sfxItem.name, sfxBuf)
                        const sfxSrc = offlineCtx.createBufferSource()
                        sfxSrc.buffer = sfxBuf
                        const sfxGain = offlineCtx.createGain()
                        sfxGain.gain.value = ev.line.sfxVolume ?? 0.5
                        sfxSrc.connect(sfxGain)
                        sfxGain.connect(offlineCtx.destination)

                        // 计算绝对时间: 台词开始时间 + (台词时长 * position)
                        const absTime = ev.startTime + (ev.duration * sfxItem.position)
                        sfxSrc.start(absTime)
                    }
                }
            }
        }

        // 2. 调度 BGM (基于 timelineEvents 推进时间)
        let currentTime = 0
        let activeBgm: { name: string; startTime: number; volume: number } | null = null

        // 重新遍历 lines 来推进时间（必须与第一遍逻辑一致）
        let eventIdx = 0
        for (const entry of lines) {
            // 当前行持续时间
            let duration = 0
            if (isDialogue(entry)) {
                // 查找对应的 timelineEvent
                if (eventIdx < timelineEvents.length && timelineEvents[eventIdx]!.line === entry) {
                    duration = timelineEvents[eventIdx]!.duration
                    eventIdx++
                }
                duration += (entry.break_duration || 0)
            }

            // 处理 BGM 指令
            if (isBgm(entry)) {
                if (entry.action === 'stop') {
                    if (activeBgm) {
                        // 结束上一段 BGM
                        await scheduleBgmSegment(activeBgm.name, activeBgm.startTime, currentTime, activeBgm.volume)
                        activeBgm = null
                    }
                } else if (entry.action === 'play') {
                    if (activeBgm) {
                        // 切换：结束上一段
                        await scheduleBgmSegment(activeBgm.name, activeBgm.startTime, currentTime, activeBgm.volume)
                    }
                    // 开始新段
                    activeBgm = {
                        name: entry.bgmName,
                        startTime: currentTime,
                        volume: entry.volume
                    }
                }
            }

            // 推进时间
            currentTime += duration
        }

        // 结束时如果有 BGM 仍在播放，截止到最后
        if (activeBgm) {
            await scheduleBgmSegment(activeBgm.name, activeBgm.startTime, totalDuration - 2.0, activeBgm.volume)
        }

        return await offlineCtx.startRendering()
    }

    return {
        isPlaying,
        currentPlayingId,
        loadAudioBuffer,
        playLine,
        stopPlayback,
        playBgm,
        stopBgm,
        playSequence,
        stopSequence,
        renderOffline,
    }
}
