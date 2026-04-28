import type { LogLevel, LogSourceId } from './log'

export type SystemRuntimeMode = 'local' | 'remote' | 'unknown'

export type SystemBridgeStatus = 'unknown' | 'online' | 'offline' | 'unavailable'

export type SystemLogsCapability = 'supported' | 'missing' | 'unknown'

export interface SystemRuntimeIncident {
  id: string
  kind: 'bridge' | 'service' | 'model' | 'crash'
  level: Extract<LogLevel, 'ERROR' | 'CRITICAL'>
  title: string
  detail: string
  logSource: LogSourceId
  logLevel: Extract<LogLevel, 'ERROR' | 'CRITICAL'> | ''
  query: string
  occurredAt: string
}
