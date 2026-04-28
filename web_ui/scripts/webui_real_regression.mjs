import process from 'node:process'

const baseUrl = (process.env.WEBUI_REAL_BASE_URL || '').replace(/\/+$/, '')
const apiKey = process.env.WEBUI_REAL_API_KEY || ''
const mode = process.env.WEBUI_REAL_MODE || 'manual'
const bridgeUrl = (process.env.WEBUI_REAL_BRIDGE_URL || '').replace(/\/+$/, '')
const allowSystemActions = process.env.WEBUI_REAL_ALLOW_SYSTEM_ACTIONS === '1'
const timeoutMs = Number(process.env.WEBUI_REAL_POLL_TIMEOUT_MS || 45000)
const batchText = process.env.WEBUI_REAL_BATCH_TEXT || 'webui real regression'

if (!baseUrl) {
  console.error('Missing WEBUI_REAL_BASE_URL')
  process.exit(1)
}

function headers(extra = {}) {
  return apiKey ? { ...extra, 'X-API-Key': apiKey } : extra
}

async function request(path, init = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: headers(init.headers || {}),
  })
  return response
}

async function requestJson(path, init = {}) {
  const response = await request(path, init)
  const text = await response.text()
  let json = null
  try {
    json = text ? JSON.parse(text) : null
  } catch {
    json = text
  }
  if (!response.ok) {
    throw new Error(`${path} failed: HTTP ${response.status} ${typeof json === 'string' ? json : JSON.stringify(json)}`)
  }
  return json
}

async function requestBlob(path, init = {}) {
  const response = await request(path, init)
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`${path} failed: HTTP ${response.status} ${text}`)
  }
  return response.blob()
}

async function pollBatch(batchId) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const status = await requestJson(`/api/v2/pro/batch/${encodeURIComponent(batchId)}`)
    if (status.status === 'done' || status.status === 'completed' || status.status === 'cancelled') {
      return status
    }
    await new Promise(resolve => setTimeout(resolve, 1500))
  }
  throw new Error(`batch ${batchId} timed out after ${timeoutMs}ms`)
}

async function maybeRunBridgeChecks(results) {
  if (!bridgeUrl) return
  const bridgeHealth = await fetch(`${bridgeUrl}/health`)
  results.push({
    name: 'bridge.health',
    status: bridgeHealth.ok ? 'passed' : 'failed',
    detail: `HTTP ${bridgeHealth.status}`,
  })
  if (allowSystemActions) {
    const ensureRuntime = await fetch(`${bridgeUrl}/api/ensure-runtime`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ baseUrl, apiKey }),
    })
    results.push({
      name: 'bridge.ensure-runtime',
      status: ensureRuntime.ok ? 'passed' : 'failed',
      detail: `HTTP ${ensureRuntime.status}`,
    })
  }
}

async function run() {
  const results = []
  console.log(`Running real regression in mode=${mode} against ${baseUrl}`)

  const health = await requestJson('/api/v2/health')
  results.push({ name: 'health', status: 'passed', detail: `status=${health.status}` })

  const voices = await requestJson('/api/v2/voices')
  results.push({ name: 'voices', status: 'passed', detail: `count=${(voices.items || []).length}` })

  const assets = await requestJson('/api/v2/assets/audio')
  results.push({ name: 'assets', status: 'passed', detail: `count=${(assets.items || []).length}` })

  const logSources = await requestJson('/api/v2/pro/logs/sources')
  results.push({ name: 'logs.sources', status: 'passed', detail: `count=${(logSources.items || []).length}` })

  const logTail = await requestJson('/api/v2/pro/logs/tail?source=app&limit=5')
  results.push({ name: 'logs.tail', status: 'passed', detail: `items=${(logTail.items || []).length}` })

  const diagnosticBundle = await requestBlob('/api/v2/pro/logs/diagnostic-bundle', { method: 'POST' })
  results.push({ name: 'logs.diagnostic-bundle', status: diagnosticBundle.size > 0 ? 'passed' : 'failed', detail: `bytes=${diagnosticBundle.size}` })

  if (allowSystemActions) {
    const reload = await requestJson('/api/v2/pro/system/reload', { method: 'POST' })
    results.push({ name: 'system.reload', status: 'passed', detail: reload.status || 'ok' })
    const unload = await requestJson('/api/v2/pro/system/unload', { method: 'POST' })
    results.push({ name: 'system.unload', status: 'passed', detail: unload.status || 'ok' })
  } else {
    results.push({ name: 'system.actions', status: 'skipped', detail: 'Set WEBUI_REAL_ALLOW_SYSTEM_ACTIONS=1 to enable.' })
  }

  const firstVoice = (voices.items || [])[0]
  if (!firstVoice?.name) {
    results.push({ name: 'pro.batch', status: 'skipped', detail: 'No voices available.' })
  } else {
    const created = await requestJson('/api/v2/pro/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: [{
          row_id: `real_${Date.now()}`,
          text: batchText,
          voice_id: firstVoice.name,
          speed: 1.0,
          mode: 'zero_shot',
          instruct_text: '',
          variation_seed: 42,
        }],
      }),
    })
    const batchStatus = await pollBatch(created.batch_id)
    const failed = (batchStatus.items || []).filter(item => item.status === 'failed').length
    results.push({
      name: 'pro.batch',
      status: failed === 0 ? 'passed' : 'failed',
      detail: `batch_id=${created.batch_id}, failed=${failed}`,
    })
  }

  await maybeRunBridgeChecks(results)

  const failed = results.filter(item => item.status === 'failed')
  console.table(results)
  if (failed.length > 0) {
    process.exit(1)
  }
}

run().catch(error => {
  console.error(error)
  process.exit(1)
})
