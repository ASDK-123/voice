import { getActiveTtsConnection } from '@/api/client_factory'
import { isLocalTtsBaseUrl } from '@/api/local_bridge'
import type { LogApiErrorKind, LogLevel, LogSourceId, LogSourceOption, LogTailResponse, SystemLogsCapability } from '@/types'

interface DownloadedFile {
  blob: Blob
  filename: string
}

class LogsApiError extends Error {
  kind: LogApiErrorKind
  status: number

  constructor(message: string, kind: LogApiErrorKind, status = 0) {
    super(message)
    this.name = 'LogsApiError'
    this.kind = kind
    this.status = status
  }
}

function buildLogsRouteMissingMessage(baseUrl: string): string {
  return isLocalTtsBaseUrl(baseUrl)
    ? '当前连接的本地后端未加载日志接口，通常是旧进程仍在运行。请重启 StartWebUI.bat 或重启本地 API 后再刷新。'
    : '当前连接的远程后端未提供日志接口，请升级或重启远程服务。'
}

export function isLogsApiError(error: unknown): error is LogsApiError {
  return error instanceof LogsApiError
}

function buildHeaders(apiKey: string, extra: Record<string, string> = {}): Record<string, string> {
  const headers = { ...extra }
  if (apiKey) {
    headers['X-API-Key'] = apiKey
  }
  return headers
}

async function parseJson<T>(response: Response, baseUrl: string): Promise<T> {
  if (response.status === 404) {
    throw new LogsApiError(buildLogsRouteMissingMessage(baseUrl), 'logs_route_missing', 404)
  }
  const text = await response.text()
  const contentType = response.headers.get('Content-Type') || ''
  const isJson = contentType.includes('application/json') || contentType.includes('+json')

  if (text && !isJson) {
    const preview = text.slice(0, 120).trim()
    if (preview.startsWith('<!doctype') || preview.startsWith('<html') || preview.startsWith('<')) {
      throw new LogsApiError('日志接口返回了 HTML 页面，当前后端可能未提供 `/api/v2/pro/logs/*`，或连接地址指向了前端页面而不是 API 服务。', 'non_json_response', response.status)
    }
  }

  let payload: any = {}
  try {
    payload = text ? JSON.parse(text) : {}
  } catch {
    throw new LogsApiError('日志接口返回了非 JSON 响应，无法读取日志数据。请检查当前 TTS 连接地址是否正确，并确认后端已包含日志接口。', 'non_json_response', response.status)
  }
  if (!response.ok) {
    const errorMessage =
      payload?.error?.message_zh ||
      payload?.error?.message ||
      payload?.message ||
      `HTTP ${response.status}`
    throw new LogsApiError(errorMessage, 'http_error', response.status)
  }
  return payload as T
}

function parseFilename(response: Response, fallback: string): string {
  const header = response.headers.get('Content-Disposition') || ''
  const match = header.match(/filename="?([^"]+)"?/)
  return match?.[1] || fallback
}

async function download(path: string, fallback: string): Promise<DownloadedFile> {
  const { baseUrl, apiKey } = getActiveTtsConnection()
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'GET',
    headers: buildHeaders(apiKey),
  })
  if (response.status === 404) {
    throw new LogsApiError(buildLogsRouteMissingMessage(baseUrl), 'logs_route_missing', 404)
  }
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new LogsApiError(text || `HTTP ${response.status}`, 'http_error', response.status)
  }
  return {
    blob: await response.blob(),
    filename: parseFilename(response, fallback),
  }
}

export async function listLogSources(): Promise<LogSourceOption[]> {
  const { baseUrl, apiKey } = getActiveTtsConnection()
  const response = await fetch(`${baseUrl}/api/v2/pro/logs/sources`, {
    method: 'GET',
    headers: buildHeaders(apiKey),
  })
  const payload = await parseJson<{ items?: LogSourceOption[] }>(response, baseUrl)
  return payload.items || []
}

export async function probeLogsCapability(): Promise<SystemLogsCapability> {
  try {
    await listLogSources()
    return 'supported'
  } catch (error) {
    if (isLogsApiError(error) && error.kind === 'logs_route_missing') {
      return 'missing'
    }
    throw error
  }
}

export async function tailLogs(params: {
  source: LogSourceId
  cursor?: string
  limit?: number
  level?: LogLevel | ''
  q?: string
}): Promise<LogTailResponse> {
  const { baseUrl, apiKey } = getActiveTtsConnection()
  const query = new URLSearchParams({
    source: params.source,
    limit: String(params.limit ?? 200),
  })
  if (params.cursor) query.set('cursor', params.cursor)
  if (params.level) query.set('level', params.level)
  if (params.q?.trim()) query.set('q', params.q.trim())

  const response = await fetch(`${baseUrl}/api/v2/pro/logs/tail?${query.toString()}`, {
    method: 'GET',
    headers: buildHeaders(apiKey),
  })
  return parseJson<LogTailResponse>(response, baseUrl)
}

export async function downloadLogFile(source: LogSourceId): Promise<DownloadedFile> {
  return download(`/api/v2/pro/logs/file?source=${encodeURIComponent(source)}`, `${source}.log`)
}

export async function exportDiagnosticBundle(): Promise<DownloadedFile> {
  const { baseUrl, apiKey } = getActiveTtsConnection()
  const response = await fetch(`${baseUrl}/api/v2/pro/logs/diagnostic-bundle`, {
    method: 'POST',
    headers: buildHeaders(apiKey),
  })
  if (response.status === 404) {
    throw new LogsApiError(buildLogsRouteMissingMessage(baseUrl), 'logs_route_missing', 404)
  }
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new LogsApiError(text || `HTTP ${response.status}`, 'http_error', response.status)
  }
  return {
    blob: await response.blob(),
    filename: parseFilename(response, `diag_${Date.now()}.zip`),
  }
}
