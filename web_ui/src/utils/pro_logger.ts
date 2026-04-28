// Pro 前端日志工具
// 模拟原桌面端的 logging 模块，统一前端控制台输出
// 所有核心业务操作（API 调用、合成调度）应使用此模块

/** 日志等级 */
type LogLevel = 'info' | 'warn' | 'error' | 'debug'

/** 日志条目 */
export interface LogEntry {
    timestamp: string
    level: LogLevel
    module: string
    message: string
}

// 日志缓存（供可能的 UI 日志面板消费）
const LOG_BUFFER_SIZE = 200
const logBuffer: LogEntry[] = []

/** 格式化时间戳 */
function timestamp(): string {
    return new Date().toISOString().slice(11, 23)
}

/** 创建带模块标签的日志器 */
export function createLogger(module: string) {
    function log(level: LogLevel, message: string, ...args: unknown[]) {
        const entry: LogEntry = {
            timestamp: timestamp(),
            level,
            module,
            message,
        }

        // 写入缓冲区
        logBuffer.push(entry)
        if (logBuffer.length > LOG_BUFFER_SIZE) {
            logBuffer.shift()
        }

        // 输出到控制台（带颜色标记）
        const prefix = `[${entry.timestamp}] [${module}]`
        switch (level) {
            case 'info':
                console.log(`%c${prefix} ${message}`, 'color: #22C55E', ...args)
                break
            case 'warn':
                console.warn(`${prefix} ${message}`, ...args)
                break
            case 'error':
                console.error(`${prefix} ${message}`, ...args)
                break
            case 'debug':
                console.debug(`%c${prefix} ${message}`, 'color: #94A3B8', ...args)
                break
        }
    }

    return {
        info: (msg: string, ...args: unknown[]) => log('info', msg, ...args),
        warn: (msg: string, ...args: unknown[]) => log('warn', msg, ...args),
        error: (msg: string, ...args: unknown[]) => log('error', msg, ...args),
        debug: (msg: string, ...args: unknown[]) => log('debug', msg, ...args),
    }
}

/** 获取当前日志缓冲区（只读） */
export function getLogBuffer(): readonly LogEntry[] {
    return logBuffer
}

/** 清空日志缓冲区 */
export function clearLogBuffer(): void {
    logBuffer.length = 0
}
