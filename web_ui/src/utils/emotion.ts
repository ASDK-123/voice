// 工具函数：情绪标签处理
// 情绪标签仍以 Voice / Asset 动态数据为准，但 WebUI 需要一组稳定的常见情绪候选

/** WebUI 默认常见情绪顺序 */
export const defaultEmotionCatalog = [
    'default',
    'happy',
    'sad',
    'angry',
    'surprise',
    'disgust',
    'calm',
    'fear',
]

/** 情绪标签规范化（保留向后兼容） */
export function normalizeEmotionTag(emotion: string): string {
    if (!emotion) return 'default'
    return emotion.trim() || 'default'
}

/**
 * 合并常见情绪与运行时发现的情绪，并保持稳定顺序：
 * 1. 默认预设在前
 * 2. 其余扩展情绪按字母排序
 */
export function buildEmotionCatalog(extraEmotions: string[] = []): string[] {
    const normalized = extraEmotions
        .map(normalizeEmotionTag)
        .filter(Boolean)

    const set = new Set<string>([...defaultEmotionCatalog, ...normalized])
    const tail = Array.from(set)
        .filter(emotion => !defaultEmotionCatalog.includes(emotion))
        .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))

    return [...defaultEmotionCatalog, ...tail]
}
