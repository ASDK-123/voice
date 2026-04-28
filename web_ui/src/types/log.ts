export type LogSourceId = 'app' | 'access' | 'crash' | 'local_bridge'

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

export type LogApiErrorKind = 'logs_route_missing' | 'non_json_response' | 'http_error'

export interface LogSourceOption {
  id: LogSourceId
  label: string
  available: boolean
}

export interface LogItem {
  id: string
  source: LogSourceId
  timestamp: string
  level: LogLevel
  module: string
  event: string
  message: string
  request_id: string
  fields: Record<string, unknown>
  raw: string
}

export interface LogTailResponse {
  items: LogItem[]
  next_cursor: string
  reset_required: boolean
  source_available: boolean
}

export interface LogFocusPreset {
  source: LogSourceId
  level: Extract<LogLevel, 'ERROR' | 'CRITICAL'> | ''
  query: string
  reason: string
  origin: 'system-runtime'
}
