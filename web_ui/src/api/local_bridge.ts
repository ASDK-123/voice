import { normalizeUrl } from '@/utils/url'

const LOCAL_BRIDGE_URL = 'http://127.0.0.1:9879'

export interface EnsureRuntimePayload {
  baseUrl: string
  apiKey: string
  timeoutMs?: number
}

export interface EnsureRuntimeResult {
  status: string
  base_url: string
  started_service: boolean
  triggered_reload: boolean
  model_loaded: boolean
  api_pid?: number | null
  health?: Record<string, unknown>
  error?: string
}

async function parseJson<T>(response: Response): Promise<T> {
  const text = await response.text()
  const payload = text ? JSON.parse(text) : {}
  if (!response.ok) {
    const message = payload?.message || payload?.error || `HTTP ${response.status}`
    throw new Error(message)
  }
  return (payload?.data ?? payload) as T
}

export function isLocalTtsBaseUrl(baseUrl: string): boolean {
  try {
    const parsed = new URL(normalizeUrl(baseUrl || 'http://127.0.0.1:9880'))
    return ['127.0.0.1', 'localhost', '0.0.0.0'].includes(parsed.hostname)
  } catch {
    return false
  }
}

export async function ensureRuntimeReady(payload: EnsureRuntimePayload): Promise<EnsureRuntimeResult> {
  const response = await fetch(`${LOCAL_BRIDGE_URL}/api/ensure-runtime`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      baseUrl: normalizeUrl(payload.baseUrl || 'http://127.0.0.1:9880'),
      apiKey: payload.apiKey || '',
      timeoutMs: payload.timeoutMs ?? 90000,
    }),
  })
  return parseJson<EnsureRuntimeResult>(response)
}

export async function probeLocalBridge(): Promise<boolean> {
  try {
    const response = await fetch(`${LOCAL_BRIDGE_URL}/health`, { method: 'GET' })
    if (!response.ok) return false
    return true
  } catch {
    return false
  }
}
