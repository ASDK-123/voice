// IndexedDB 持久化 Composable（单例模式）
// 管理 UnitaleStudio 数据库的双 Store 读写
// 所有调用方共享同一个数据库连接

import { ref } from 'vue'
import type { ProjectSnapshot } from '@/types'

const DB_NAME = 'UnitaleStudio'
const DB_VERSION = 1
const PROJECT_STORE = 'project'
const ASSETS_STORE = 'assets'
const PROJECT_KEY = 'main'

// ── 模块级单例状态（所有 useIndexedDB() 调用共享） ──
let db: IDBDatabase | null = null
const isReady = ref(false)

/** 防抖自动保存定时器 */
let autoSaveTimer: ReturnType<typeof setTimeout> | null = null

/** 打开/初始化数据库（单例，仅第一次真正打开） */
function openDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        if (db) return resolve(db)

        const request = indexedDB.open(DB_NAME, DB_VERSION)

        request.onupgradeneeded = () => {
            const database = request.result
            if (!database.objectStoreNames.contains(PROJECT_STORE)) {
                database.createObjectStore(PROJECT_STORE)
            }
            if (!database.objectStoreNames.contains(ASSETS_STORE)) {
                database.createObjectStore(ASSETS_STORE)
            }
        }

        request.onsuccess = () => {
            db = request.result
            isReady.value = true
            resolve(db)
        }

        request.onerror = () => {
            reject(new Error(`IndexedDB 打开失败: ${request.error?.message}`))
        }
    })
}

/** 保存项目状态快照 */
async function saveProject(snapshot: ProjectSnapshot): Promise<void> {
    const database = await openDB()
    // 深度克隆以脱离 Vue Proxy 响应式系统，防止 DataCloneError
    // 这是解决 "object could not be cloned" 的最稳健方案
    const dataToSave = JSON.parse(JSON.stringify(snapshot))

    return new Promise((resolve, reject) => {
        try {
            const tx = database.transaction(PROJECT_STORE, 'readwrite')
            const store = tx.objectStore(PROJECT_STORE)
            const req = store.put(dataToSave, PROJECT_KEY)
            req.onsuccess = () => resolve()
            req.onerror = () => reject(new Error('项目保存失败'))
        } catch (e: any) {
            console.error('[IndexedDB] 序列化/保存失败:', e)
            reject(e)
        }
    })
}

/** 加载项目状态 */
async function loadProject(): Promise<ProjectSnapshot | null> {
    const database = await openDB()
    return new Promise((resolve, reject) => {
        const tx = database.transaction(PROJECT_STORE, 'readonly')
        const store = tx.objectStore(PROJECT_STORE)
        const req = store.get(PROJECT_KEY)
        req.onsuccess = () => resolve(req.result || null)
        req.onerror = () => reject(new Error('项目加载失败'))
    })
}

/** 保存单个 Asset（带重试） */
async function saveAsset(key: string, blob: Blob, retries = 2): Promise<void> {
    const database = await openDB()
    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            await new Promise<void>((resolve, reject) => {
                const tx = database.transaction(ASSETS_STORE, 'readwrite')
                const store = tx.objectStore(ASSETS_STORE)
                const req = store.put(blob, key)
                req.onsuccess = () => resolve()
                req.onerror = () => reject(req.error)
            })
            return // 成功则返回
        } catch (e) {
            if (attempt === retries) throw e
            // 指数退避
            await new Promise(r => setTimeout(r, 100 * Math.pow(2, attempt)))
        }
    }
}

/** 删除单个 Asset */
async function deleteAsset(key: string): Promise<void> {
    const database = await openDB()
    return new Promise((resolve, reject) => {
        const tx = database.transaction(ASSETS_STORE, 'readwrite')
        const store = tx.objectStore(ASSETS_STORE)
        const req = store.delete(key)
        req.onsuccess = () => resolve()
        req.onerror = () => reject(req.error)
    })
}

/** 批量保存 Assets（单事务） */
async function saveAssetsBatch(items: { key: string; blob: Blob }[]): Promise<void> {
    if (items.length === 0) return
    const database = await openDB()
    return new Promise((resolve, reject) => {
        const tx = database.transaction(ASSETS_STORE, 'readwrite')
        const store = tx.objectStore(ASSETS_STORE)
        for (const { key, blob } of items) {
            store.put(blob, key)
        }
        tx.oncomplete = () => resolve()
        tx.onerror = () => reject(new Error('批量保存 assets 失败'))
    })
}

/** 获取单个 Asset */
async function getAsset(key: string): Promise<Blob | null> {
    const database = await openDB()
    return new Promise((resolve, reject) => {
        const tx = database.transaction(ASSETS_STORE, 'readonly')
        const store = tx.objectStore(ASSETS_STORE)
        const req = store.get(key)
        req.onsuccess = () => resolve(req.result || null)
        req.onerror = () => reject(req.error)
    })
}

/** 获取所有 Asset keys */
async function getAllAssetKeys(): Promise<string[]> {
    const database = await openDB()
    return new Promise((resolve, reject) => {
        const tx = database.transaction(ASSETS_STORE, 'readonly')
        const store = tx.objectStore(ASSETS_STORE)
        const req = store.getAllKeys()
        req.onsuccess = () => resolve(req.result as string[])
        req.onerror = () => reject(req.error)
    })
}

/** 加载所有 Assets 到内存 Map */
async function loadAllAssets(): Promise<Map<string, Blob>> {
    const database = await openDB()
    const map = new Map<string, Blob>()
    return new Promise((resolve, reject) => {
        const tx = database.transaction(ASSETS_STORE, 'readonly')
        const store = tx.objectStore(ASSETS_STORE)
        const req = store.openCursor()
        req.onsuccess = () => {
            const cursor = req.result
            if (cursor) {
                map.set(cursor.key as string, cursor.value)
                cursor.continue()
            } else {
                resolve(map)
            }
        }
        req.onerror = () => reject(req.error)
    })
}

/** 防抖自动保存（1 秒延迟） */
function triggerAutoSave(snapshot: ProjectSnapshot) {
    if (autoSaveTimer) clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(async () => {
        try {
            await saveProject(snapshot)
        } catch (e) {
            console.error('自动保存失败:', e)
        }
    }, 1000)
}

/** 返回单例 API（兼容现有调用方式） */
export function useIndexedDB() {
    return {
        isReady,
        openDB,
        saveProject,
        loadProject,
        saveAsset,
        deleteAsset,
        saveAssetsBatch,
        getAsset,
        getAllAssetKeys,
        loadAllAssets,
        triggerAutoSave,
    }
}
