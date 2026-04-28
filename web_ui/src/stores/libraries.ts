// 资源库 Store
// 管理 SFX、BGM、音色、滤波器四大资源库
// 支持 IndexedDB 持久化和素材试听

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { SfxItem, BgmItem, TimbreItem, FilterItem } from '@/types'
import { useIndexedDB } from '@/composables/useIndexedDB'

/** 素材在 IndexedDB 中的 key 前缀，与 TTS 音频区分 */
const LIB_ASSET_PREFIX = 'lib:'

export const useLibrariesStore = defineStore('libraries', () => {
    // ── 四大资源库 ──
    const sfxLibrary = ref<SfxItem[]>([])
    const bgmLibrary = ref<BgmItem[]>([])
    const timbres = ref<TimbreItem[]>([])
    const filterLibrary = ref<FilterItem[]>([])

    /** 本地文件映射：filename → File/Blob（内存缓存） */
    const localFileMap = ref(new Map<string, File | Blob>())

    /** IndexedDB 实例 */
    const idb = useIndexedDB()

    /** 当前正在试听的素材 ID */
    const previewingId = ref('')
    /** 内部 Audio 元素引用 */
    let previewAudio: HTMLAudioElement | null = null
    /** 当前预览的 Blob URL（用于释放） */
    let previewUrl: string | null = null

    // ── SFX CRUD ──

    function saveSfx(item: SfxItem, file?: File) {
        const idx = sfxLibrary.value.findIndex(s => s.id === item.id)
        if (idx >= 0) {
            sfxLibrary.value[idx] = { ...item }
        } else {
            sfxLibrary.value.push({ ...item })
        }
        if (file && item.filename) {
            localFileMap.value.set(item.filename, file)
            // 持久化到 IndexedDB
            _persistAsset(item.filename, file)
        }
    }

    function deleteSfx(id: string) {
        const item = sfxLibrary.value.find(s => s.id === id)
        if (item?.filename) {
            localFileMap.value.delete(item.filename)
            // 从 IndexedDB 删除
            _removeAsset(item.filename)
        }
        sfxLibrary.value = sfxLibrary.value.filter(s => s.id !== id)
    }

    // ── BGM CRUD ──

    function saveBgm(item: BgmItem, file?: File) {
        const idx = bgmLibrary.value.findIndex(b => b.id === item.id)
        if (idx >= 0) {
            bgmLibrary.value[idx] = { ...item }
        } else {
            bgmLibrary.value.push({ ...item })
        }
        if (file && item.filename) {
            localFileMap.value.set(item.filename, file)
            // 持久化到 IndexedDB
            _persistAsset(item.filename, file)
        }
    }

    function deleteBgm(id: string) {
        const item = bgmLibrary.value.find(b => b.id === id)
        if (item?.filename) {
            localFileMap.value.delete(item.filename)
            _removeAsset(item.filename)
        }
        bgmLibrary.value = bgmLibrary.value.filter(b => b.id !== id)
    }

    // ── Timbre CRUD ──

    function saveTimbre(item: TimbreItem, file?: File) {
        const idx = timbres.value.findIndex(t => t.id === item.id)
        if (idx >= 0) {
            timbres.value[idx] = { ...item }
        } else {
            timbres.value.push({ ...item })
        }
        if (file && item.refPath) {
            localFileMap.value.set(item.refPath, file)
            // 持久化到 IndexedDB
            _persistAsset(item.refPath, file)
        }
    }

    function deleteTimbre(id: string) {
        const item = timbres.value.find(t => t.id === id)
        if (item?.refPath) {
            localFileMap.value.delete(item.refPath)
            _removeAsset(item.refPath)
        }
        timbres.value = timbres.value.filter(t => t.id !== id)
    }

    // ── Filter CRUD ──

    function saveFilter(item: FilterItem) {
        const idx = filterLibrary.value.findIndex(f => f.id === item.id)
        if (idx >= 0) {
            filterLibrary.value[idx] = { ...item }
        } else {
            filterLibrary.value.push({ ...item })
        }
    }

    function deleteFilter(id: string) {
        filterLibrary.value = filterLibrary.value.filter(f => f.id !== id)
    }

    // ── 查询 ──

    function getSfxByName(name: string): SfxItem | undefined {
        return sfxLibrary.value.find(s => s.name === name)
    }

    function getBgmByName(name: string): BgmItem | undefined {
        return bgmLibrary.value.find(b => b.name === name)
    }

    function getFilterByName(name: string): FilterItem | undefined {
        return filterLibrary.value.find(f => f.name === name)
    }

    function getFileBlob(filename: string): File | Blob | undefined {
        return localFileMap.value.get(filename)
    }

    // ── 试听功能 ──

    /**
     * 播放指定素材的音频预览
     * @param id 素材 ID（用于追踪播放状态）
     * @param filename 文件名（localFileMap 的 key）
     */
    function startPreview(id: string, filename: string) {
        // 如果正在播放同一条，则停止
        if (previewingId.value === id) {
            stopPreview()
            return
        }

        // 停止上一条
        stopPreview()

        const blob = localFileMap.value.get(filename)
        if (!blob) {
            console.warn('试听失败：找不到文件', filename)
            return
        }

        previewUrl = URL.createObjectURL(blob)
        previewAudio = new Audio(previewUrl)
        previewingId.value = id

        previewAudio.onended = () => {
            _cleanupPreview()
        }
        previewAudio.onerror = () => {
            console.error('试听播放出错')
            _cleanupPreview()
        }
        previewAudio.play().catch(e => {
            console.error('试听播放失败:', e)
            _cleanupPreview()
        })
    }

    /** 停止当前试听 */
    function stopPreview() {
        if (previewAudio) {
            previewAudio.pause()
            previewAudio.currentTime = 0
        }
        _cleanupPreview()
    }

    /** 清理预览状态（内部方法） */
    function _cleanupPreview() {
        if (previewUrl) {
            URL.revokeObjectURL(previewUrl)
            previewUrl = null
        }
        previewAudio = null
        previewingId.value = ''
    }

    // ── IndexedDB 持久化 ──

    /** 将文件 Blob 写入 IndexedDB */
    async function _persistAsset(filename: string, blob: Blob) {
        try {
            await idb.saveAsset(LIB_ASSET_PREFIX + filename, blob)
        } catch (e) {
            console.error('素材持久化失败:', filename, e)
        }
    }

    /** 从 IndexedDB 删除文件 */
    async function _removeAsset(filename: string) {
        try {
            await idb.deleteAsset(LIB_ASSET_PREFIX + filename)
        } catch (e) {
            console.error('素材删除失败:', filename, e)
        }
    }

    /**
     * 从 IndexedDB 恢复所有素材文件到 localFileMap
     * 应在应用初始化时调用
     */
    async function restoreAssetsFromDB() {
        try {
            const allAssets = await idb.loadAllAssets()
            for (const [key, blob] of allAssets) {
                if (key.startsWith(LIB_ASSET_PREFIX)) {
                    const filename = key.slice(LIB_ASSET_PREFIX.length)
                    localFileMap.value.set(filename, blob)
                }
            }
            console.log(`[Libraries] 已从 IndexedDB 恢复 ${localFileMap.value.size} 个素材文件`)
        } catch (e) {
            console.error('素材恢复失败:', e)
        }
    }

    return {
        sfxLibrary,
        bgmLibrary,
        timbres,
        filterLibrary,
        localFileMap,
        // CRUD
        saveSfx,
        deleteSfx,
        saveBgm,
        deleteBgm,
        saveTimbre,
        deleteTimbre,
        saveFilter,
        deleteFilter,
        // 查询
        getSfxByName,
        getBgmByName,
        getFilterByName,
        getFileBlob,
        // 试听
        previewingId,
        startPreview,
        stopPreview,
        // 持久化
        restoreAssetsFromDB,
    }
})
