// 工具函数：音频处理
// WAV 编码、AudioBuffer 工具

/** 向 DataView 写入字符串 */
function writeString(view: DataView, offset: number, str: string) {
    for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i))
    }
}

/**
 * AudioBuffer → WAV Blob（16-bit PCM）
 *
 * 从原 index.html L3522-L3562 迁移
 */
export function bufferToWave(buffer: AudioBuffer): Blob {
    const numChan = buffer.numberOfChannels
    const length = buffer.length * numChan * 2 + 44
    const arrayBuffer = new ArrayBuffer(length)
    const view = new DataView(arrayBuffer)

    // RIFF 头
    writeString(view, 0, 'RIFF')
    view.setUint32(4, length - 8, true)
    writeString(view, 8, 'WAVE')

    // fmt 块
    writeString(view, 12, 'fmt ')
    view.setUint32(16, 16, true)           // 块大小
    view.setUint16(20, 1, true)            // PCM 格式
    view.setUint16(22, numChan, true)      // 声道数
    view.setUint32(24, buffer.sampleRate, true)  // 采样率
    view.setUint32(28, buffer.sampleRate * 2 * numChan, true) // 字节率
    view.setUint16(32, numChan * 2, true)  // 块对齐
    view.setUint16(34, 16, true)           // 位深

    // data 块
    writeString(view, 36, 'data')
    view.setUint32(40, length - 44, true)

    // PCM 数据交织写入
    const channels = Array.from({ length: numChan }, (_, i) =>
        buffer.getChannelData(i),
    )
    let offset = 44
    for (let pos = 0; pos < buffer.length; pos++) {
        for (let ch = 0; ch < numChan; ch++) {
            const channelData = channels[ch]!
            const sample = Math.max(-1, Math.min(1, channelData[pos] ?? 0))
            const int16 = sample < 0 ? sample * 32768 : sample * 32767
            view.setInt16(offset, int16 | 0, true)
            offset += 2
        }
    }

    return new Blob([arrayBuffer], { type: 'audio/wav' })
}

/** 多段音频 Blob 顺序拼接为单个 WAV Blob */
export async function mergeAudioBlobs(blobs: Blob[]): Promise<Blob> {
    if (blobs.length === 0) {
        throw new Error('没有可合并的音频')
    }

    const Ctx = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctx) {
        throw new Error('当前浏览器不支持 AudioContext')
    }

    const ctx = new Ctx()
    try {
        const buffers = await Promise.all(
            blobs.map(async blob => {
                const arr = await blob.arrayBuffer()
                return await ctx.decodeAudioData(arr.slice(0))
            }),
        )

        const sampleRate = buffers[0]?.sampleRate || 22050
        const numberOfChannels = Math.max(...buffers.map(buffer => buffer.numberOfChannels || 1))
        const totalLength = buffers.reduce((sum, buffer) => sum + buffer.length, 0)
        const merged = ctx.createBuffer(numberOfChannels, totalLength, sampleRate)

        let offset = 0
        for (const buffer of buffers) {
            for (let channel = 0; channel < numberOfChannels; channel++) {
                const target = merged.getChannelData(channel)
                const sourceChannel = Math.min(channel, buffer.numberOfChannels - 1)
                const source = buffer.getChannelData(sourceChannel)
                target.set(source, offset)
            }
            offset += buffer.length
        }

        return bufferToWave(merged)
    } finally {
        void ctx.close()
    }
}

/**
 * 失真曲线生成
 *
 * 从原 index.html L2516-L2526 迁移
 */
export function makeDistortionCurve(amount: number): Float32Array {
    const k = typeof amount === 'number' ? amount : 50
    const n = 44100
    const curve = new Float32Array(n)
    const deg = Math.PI / 180
    for (let i = 0; i < n; i++) {
        const x = (i * 2) / n - 1
        curve[i] = ((3 + k) * x * 20 * deg) / (Math.PI + k * Math.abs(x))
    }
    return curve
}

/** 触发浏览器文件下载 */
export function downloadBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
}

/** Blob → Base64 字符串 */
export function blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result as string)
        reader.onerror = reject
        reader.readAsDataURL(blob)
    })
}

/** Base64 Data URL → Blob */
export function base64ToBlob(dataUrl: string): Blob {
    const parts = dataUrl.split(',')
    const header = parts[0] ?? ''
    const b64 = parts[1] ?? ''
    const mimeMatch = header.match(/:(.*?);/)
    const mime = mimeMatch?.[1] ?? 'application/octet-stream'
    const bytes = atob(b64)
    const arr = new Uint8Array(bytes.length)
    for (let i = 0; i < bytes.length; i++) {
        arr[i] = bytes.charCodeAt(i)
    }
    return new Blob([arr], { type: mime })
}
