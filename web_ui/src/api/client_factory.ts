import { CosyVoiceClient } from '@/api/cosyvoice'
import { useTtsStore } from '@/stores/tts'

export interface ActiveTtsConnection {
  baseUrl: string
  apiKey: string
  name: string
}

export function getActiveTtsConnection(): ActiveTtsConnection {
  const tts = useTtsStore()
  const cfg = tts.currentConfig
  if (!cfg) {
    throw new Error('请先在“系统”页面选择一个 TTS 配置')
  }
  return {
    baseUrl: cfg.baseUrl,
    apiKey: cfg.apiKey || '',
    name: cfg.name,
  }
}

export function createCosyVoiceClientFromActiveConfig(): CosyVoiceClient {
  const cfg = getActiveTtsConnection()
  return new CosyVoiceClient(cfg.baseUrl, cfg.apiKey)
}
