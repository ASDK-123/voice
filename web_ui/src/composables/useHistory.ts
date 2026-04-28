// 通用 Undo/Redo 历史记录管理 Composable
// 基于深拷贝快照（Snapshot）实现，独立于具体 Store

import { ref, computed } from 'vue'

export interface UseHistoryOptions {
    /** 最大历史步数，默认 50 */
    capacity?: number
}

export function useHistory<T>(options: UseHistoryOptions = {}) {
    const { capacity = 50 } = options

    // 历史栈
    const undoStack = ref<string[]>([])
    const redoStack = ref<string[]>([])

    // 当前快照（JSON 字符串）
    const currentSnapshot = ref<string>('')

    // 是否正在执行 undo/redo（防止 watch 死循环）
    const isUndoRedoing = ref(false)

    // ── 状态查询 ──
    const canUndo = computed(() => undoStack.value.length > 0)
    const canRedo = computed(() => redoStack.value.length > 0)
    const undoCount = computed(() => undoStack.value.length)
    const redoCount = computed(() => redoStack.value.length)

    /**
     * 提交一个新快照到历史记录
     * 每次用户做出有意义的修改时调用
     */
    function push(state: T): void {
        const json = JSON.stringify(state)

        // 如果与当前快照相同，跳过（避免无意义的历史记录）
        if (json === currentSnapshot.value) return

        // 当前快照入 undo 栈
        if (currentSnapshot.value) {
            undoStack.value.push(currentSnapshot.value)
            // 超出容量则移除最早的记录
            if (undoStack.value.length > capacity) {
                undoStack.value.shift()
            }
        }

        // 更新当前快照
        currentSnapshot.value = json

        // 新操作会清空 redo 栈
        redoStack.value = []
    }

    /**
     * 撤销操作：回退到上一个快照
     * 返回被恢复的状态对象（已反序列化），或 null 表示无法撤销
     */
    function undo(): T | null {
        if (!canUndo.value) return null

        isUndoRedoing.value = true

        // 当前快照推入 redo 栈
        if (currentSnapshot.value) {
            redoStack.value.push(currentSnapshot.value)
        }

        // 从 undo 栈弹出
        const prev = undoStack.value.pop()!
        currentSnapshot.value = prev

        isUndoRedoing.value = false
        return JSON.parse(prev) as T
    }

    /**
     * 重做操作：前进到下一个快照
     * 返回被恢复的状态对象（已反序列化），或 null 表示无法重做
     */
    function redo(): T | null {
        if (!canRedo.value) return null

        isUndoRedoing.value = true

        // 当前快照推入 undo 栈
        if (currentSnapshot.value) {
            undoStack.value.push(currentSnapshot.value)
        }

        // 从 redo 栈弹出
        const next = redoStack.value.pop()!
        currentSnapshot.value = next

        isUndoRedoing.value = false
        return JSON.parse(next) as T
    }

    /**
     * 初始化快照（设置初始状态，不计入历史）
     */
    function init(state: T): void {
        currentSnapshot.value = JSON.stringify(state)
        undoStack.value = []
        redoStack.value = []
    }

    /**
     * 清空所有历史记录
     */
    function clear(): void {
        undoStack.value = []
        redoStack.value = []
        currentSnapshot.value = ''
    }

    return {
        canUndo,
        canRedo,
        undoCount,
        redoCount,
        isUndoRedoing,
        push,
        undo,
        redo,
        init,
        clear,
    }
}
