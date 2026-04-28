import { defineStore } from 'pinia'
import { ref } from 'vue'
import { get, set, del } from 'idb-keyval'

/**
 * P7.2: Audio Resource Manager
 * Manages Blob URLs to prevent memory leaks from large audio generation.
 * Strategy: LRU (Least Recently Used) + Persistence (IndexedDB).
 */
export const useAudioStore = defineStore('audio', () => {
    // Memory Cache: audioId -> blobUrl
    const cache = ref(new Map<string, string>())
    // LRU Queue: audioId list (tail = most recently used)
    const lru = ref<string[]>([])

    // Config
    const MAX_IN_MEMORY = 20

    /**
     * Register new audio blob.
     * Saves to IDB and creates URL if space available.
     */
    async function registerAudio(audioId: string, blob: Blob): Promise<string> {
        // 1. Save to IDB (Persistence)
        try {
            await set(audioId, blob)
        } catch (e) {
            console.error('Failed to save audio to IDB:', e)
        }

        // 2. Load into memory (forces eviction if needed)
        return await loadToMemory(audioId, blob)
    }

    /**
     * Get URL for existing audioId.
     * If in memory, return immediately.
     * If in IDB, load to memory.
     */
    async function getAudioUrl(audioId: string): Promise<string | null> {
        if (!audioId) return null

        // Hit Memory Cache
        if (cache.value.has(audioId)) {
            refreshLru(audioId)
            return cache.value.get(audioId)!
        }

        // Hit Disk Cache (IDB)
        try {
            const blob = await get<Blob>(audioId)
            if (blob) {
                return await loadToMemory(audioId, blob)
            }
        } catch (e) {
            console.error(`Audio ${audioId} not found in IDB`)
        }

        return null
    }

    /**
     * Delete audio from everywhere.
     */
    async function deleteAudio(audioId: string) {
        // 1. Memory
        if (cache.value.has(audioId)) {
            URL.revokeObjectURL(cache.value.get(audioId)!)
            cache.value.delete(audioId)
        }
        lru.value = lru.value.filter(id => id !== audioId)

        // 2. Disk
        await del(audioId)
    }

    // --- Internals ---

    async function loadToMemory(audioId: string, blob: Blob): Promise<string> {
        // Create URL
        const url = URL.createObjectURL(blob)

        // Add to cache
        cache.value.set(audioId, url)
        refreshLru(audioId)

        // Evict if full
        while (lru.value.length > MAX_IN_MEMORY) {
            evictOldest()
        }

        return url
    }

    function refreshLru(audioId: string) {
        // Remove existing
        lru.value = lru.value.filter(id => id !== audioId)
        // Push to end (most recently used)
        lru.value.push(audioId)
    }

    function evictOldest() {
        const oldestId = lru.value.shift() // Get first (least recently used)
        if (oldestId && cache.value.has(oldestId)) {
            const url = cache.value.get(oldestId)!
            URL.revokeObjectURL(url) // Free memory
            cache.value.delete(oldestId)
            console.debug(`[AudioStore] Evicted ${oldestId} from memory`)
        }
    }

    return {
        registerAudio,
        getAudioUrl,
        deleteAudio
    }
})
