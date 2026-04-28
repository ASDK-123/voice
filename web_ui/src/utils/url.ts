// 工具函数：URL 处理

/** URL 拼接（避免双斜杠） */
export function urlJoin(base: string, path: string): string {
    const normalizedBase = base.trim().replace(/\/+$/, '')
    return `${normalizedBase}${path.startsWith('/') ? path : `/${path}`}`
}

/** 规范化 URL：移除尾部斜杠 */
export function normalizeUrl(url: string): string {
    return url.trim().replace(/\/+$/, '')
}
