import { createServer } from 'node:http'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { extname, join, normalize } from 'node:path'
import process from 'node:process'
import { chromium } from 'playwright'

const HOST = '127.0.0.1'
const DIST_DIR = join(process.cwd(), 'dist')
const OUTPUT_DIR = join(process.cwd(), 'output', 'playwright')

const MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.ico': 'image/x-icon',
} 

const WAV_HEADER = Buffer.from([
    0x52, 0x49, 0x46, 0x46, 0x24, 0x00, 0x00, 0x00,
    0x57, 0x41, 0x56, 0x45, 0x66, 0x6d, 0x74, 0x20,
    0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
    0x22, 0x56, 0x00, 0x00, 0x44, 0xac, 0x00, 0x00,
    0x02, 0x00, 0x10, 0x00, 0x64, 0x61, 0x74, 0x61,
    0x00, 0x00, 0x00, 0x00,
])

async function startStaticServer() {
    const server = createServer(async (req, res) => {
        try {
            const requestPath = req.url && req.url !== '/' ? req.url.split('?')[0] : '/index.html'
            const safePath = normalize(requestPath).replace(/^(\.\.[/\\])+/, '')
            const filePath = join(DIST_DIR, safePath === '/' ? 'index.html' : safePath)

            let body
            let contentType
            try {
                body = await readFile(filePath)
                contentType = MIME_TYPES[extname(filePath)] || 'application/octet-stream'
            } catch {
                body = await readFile(join(DIST_DIR, 'index.html'))
                contentType = MIME_TYPES['.html']
            }

            res.writeHead(200, { 'Content-Type': contentType })
            res.end(body)
        } catch {
            res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' })
            res.end('smoke server error')
        }
    })

    await new Promise((resolve, reject) => {
        server.once('error', reject)
        server.listen(0, HOST, resolve)
    })

    return server
}

async function run() {
    await mkdir(OUTPUT_DIR, { recursive: true })
    const server = await startStaticServer()
    const address = server.address()
    const baseUrl = typeof address === 'object' && address ? `http://${HOST}:${address.port}` : `http://${HOST}`
    const legacyImportFile = join(OUTPUT_DIR, 'legacy-import-smoke.json')
    let healthState = 'offline'
    let bridgeOnline = false
    let reloadShouldFail = false
    let logsRouteMode = 'supported'
    let importCounter = 0
    let batchCounter = 0
    let voices = [
        {
            name: '测试角色#default',
            character: '测试角色',
            emotion: 'default',
            mode: 'zero_shot',
            prompt_text: '你好',
            prompt_audio: '',
            selection_policy: 'random_per_text',
            ref_asset_ids: ['asset_complete'],
            color: '#F97316',
        },
        {
            name: '测试角色#开心',
            character: '测试角色',
            emotion: '开心',
            mode: 'zero_shot',
            prompt_text: '开心一点',
            prompt_audio: '',
            selection_policy: 'random_per_text',
            ref_asset_ids: ['asset_legacy'],
            color: '#38BDF8',
        },
        {
            name: '测试角色#低沉',
            character: '测试角色',
            emotion: '低沉',
            mode: 'zero_shot',
            prompt_text: '低沉一点',
            prompt_audio: '',
            selection_policy: 'random_per_text',
            ref_asset_ids: [],
            color: '#A855F7',
        },
    ]
    let assets = [
        {
            asset_id: 'asset_complete',
            path: '/tmp/asset_complete.wav',
            kind: 'ref',
            character: '测试角色',
            emotion: 'default',
            language: 'zh',
            note: '完整 transcript',
            transcript_text: '完整文本',
            prompt_text: '完整文本',
            linked: true,
            ref_count: 1,
        },
        {
            asset_id: 'asset_legacy',
            path: '/tmp/asset_legacy.wav',
            kind: 'ref',
            character: '测试角色',
            emotion: '开心',
            language: 'zh',
            note: 'legacy 文本',
            transcript_text: '',
            prompt_text: '旧版 transcript',
            linked: true,
            ref_count: 1,
        },
        {
            asset_id: 'asset_missing',
            path: '/tmp/asset_missing.wav',
            kind: 'ref',
            character: '测试角色',
            emotion: '低沉',
            language: 'zh',
            note: '缺少 transcript',
            transcript_text: '',
            prompt_text: '',
            linked: false,
            ref_count: 0,
        },
    ]
    const rowAttempts = new Map()
    const batchStore = new Map()

    function refreshAssetLinkState() {
        assets = assets.map(asset => {
            const refCount = voices.filter(voice => (voice.ref_asset_ids || []).includes(asset.asset_id)).length
            return {
                ...asset,
                linked: refCount > 0,
                ref_count: refCount,
            }
        })
    }

    refreshAssetLinkState()
    await writeFile(legacyImportFile, JSON.stringify([
        {
            name: 'Legacy导入角色',
            mode: 'zero_shot',
            prompt_text: '来自旧版配置',
            prompt_audio: '/tmp/legacy-import.wav',
            color: '#16A34A',
        },
    ], null, 2), 'utf-8')

    try {
        const browser = await chromium.launch({ headless: true })
        const page = await browser.newPage()

        await page.route('**/api/v2/health', route => {
            if (healthState === 'online') {
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        status: 'ok',
                        model_loaded: true,
                        gpu_name: 'Smoke GPU',
                        vram_used_mb: 1024,
                        vram_total_mb: 8192,
                    }),
                })
            }
            return route.fulfill({
                status: 503,
                contentType: 'application/json',
                body: JSON.stringify({ error: 'service offline' }),
            })
        })

        await page.route('http://127.0.0.1:9879/health', route => route.fulfill({
            status: bridgeOnline ? 200 : 503,
            contentType: 'application/json',
            headers: { 'Access-Control-Allow-Origin': '*' },
            body: JSON.stringify({ status: bridgeOnline ? 'ok' : 'offline' }),
        }))

        await page.route('http://127.0.0.1:9879/api/ensure-runtime', route => route.fulfill({
            status: bridgeOnline ? 200 : 500,
            contentType: 'application/json',
            headers: { 'Access-Control-Allow-Origin': '*' },
            body: JSON.stringify(bridgeOnline
                ? {
                    status: 'loaded',
                    base_url: 'http://localhost:9880',
                    started_service: true,
                    triggered_reload: true,
                    model_loaded: true,
                    api_pid: 4321,
                }
                : { error: 'bridge offline' }),
        }))

        await page.route('**/api/v2/voices', route => {
            if (route.request().method() === 'GET') {
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        items: voices,
                    }),
                })
            }
            return route.continue()
        })

        await page.route('**/api/v2/voices/*', async route => {
            const req = route.request()
            const url = new URL(req.url())
            const voiceId = decodeURIComponent(url.pathname.split('/').slice(-1)[0] || '')
            if (voiceId === 'import-legacy' && req.method() === 'POST') {
                const body = req.postData() || ''
                const dryRun = /name="dry_run"[\s\S]*?\r\n\r\n1/.test(body)
                if (!dryRun) {
                    importCounter += 1
                    const importedAssetId = `imported_asset_${importCounter}`
                    voices = [
                        ...voices,
                        {
                            name: 'Legacy导入角色#default',
                            character: 'Legacy导入角色',
                            emotion: 'default',
                            mode: 'zero_shot',
                            prompt_text: '来自旧版配置',
                            prompt_audio: `/tmp/${importedAssetId}.wav`,
                            selection_policy: 'random_per_text',
                            ref_asset_ids: [importedAssetId],
                            color: '#16A34A',
                        },
                    ]
                    assets = [
                        ...assets,
                        {
                            asset_id: importedAssetId,
                            path: `/tmp/${importedAssetId}.wav`,
                            kind: 'ref',
                            character: 'Legacy导入角色',
                            emotion: 'default',
                            language: 'zh',
                            note: 'legacy import',
                            transcript_text: '来自旧版配置',
                            prompt_text: '来自旧版配置',
                            linked: true,
                            ref_count: 1,
                        },
                    ]
                    refreshAssetLinkState()
                }
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({
                        imported_voices: 1,
                        imported_assets: 1,
                        skipped_assets: 0,
                        errors: [],
                        dry_run: dryRun,
                    }),
                })
            }
            if (req.method() === 'PUT') {
                const payload = req.postDataJSON?.() || {}
                const index = voices.findIndex(voice => voice.name === voiceId)
                if (index < 0) {
                    return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'voice not found' }) })
                }
                const updated = { ...voices[index], ...payload }
                voices[index] = updated
                refreshAssetLinkState()
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(updated),
                })
            }
            if (req.method() === 'DELETE') {
                voices = voices.filter(voice => voice.name !== voiceId)
                refreshAssetLinkState()
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ status: 'deleted', voice_id: voiceId }),
                })
            }
            return route.continue()
        })

        await page.route('**/api/v2/assets/audio*', async route => {
            const req = route.request()
            const url = new URL(req.url())
            if (!url.pathname.endsWith('/api/v2/assets/audio')) {
                return route.continue()
            }
            if (req.method() === 'GET') {
                refreshAssetLinkState()
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ items: assets }),
                })
            }
            return route.continue()
        })

        await page.route('**/api/v2/assets/audio/*', async route => {
            const req = route.request()
            const url = new URL(req.url())
            const tail = url.pathname.split('/').slice(-2)
            const assetId = decodeURIComponent(tail[0] === 'audio' ? tail[1] : tail[0] || '')
            if (url.pathname.endsWith('/content')) {
                return route.fulfill({
                    status: 200,
                    contentType: 'audio/wav',
                    body: WAV_HEADER,
                })
            }
            if (req.method() === 'PUT') {
                const payload = req.postDataJSON?.() || {}
                const index = assets.findIndex(asset => asset.asset_id === assetId)
                if (index < 0) {
                    return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'asset not found' }) })
                }
                assets[index] = { ...assets[index], ...payload }
                refreshAssetLinkState()
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(assets[index]),
                })
            }
            if (req.method() === 'DELETE') {
                assets = assets.filter(asset => asset.asset_id !== assetId)
                refreshAssetLinkState()
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ status: 'deleted', asset_id: assetId }),
                })
            }
            return route.continue()
        })

        await page.route('**/api/v2/pro/batch', async route => {
            const body = route.request().postDataJSON?.() || {}
            const items = body.items || []
            const batchId = `smoke_batch_${++batchCounter}`
            const resultItems = items.map(item => {
                const nextAttempt = (rowAttempts.get(item.row_id) || 0) + 1
                rowAttempts.set(item.row_id, nextAttempt)
                const shouldFail = String(item.text || '').includes('失败') && nextAttempt === 1
                return {
                    row_id: item.row_id,
                    status: shouldFail ? 'failed' : 'done',
                    audio_url: shouldFail ? null : `/api/v2/pro/batch/${batchId}/audio/${item.row_id}`,
                    duration_ms: shouldFail ? null : 1200,
                    error: shouldFail ? 'Smoke 首次失败，用于验证重试链路。' : null,
                }
            })
            batchStore.set(batchId, {
                batch_id: batchId,
                total: resultItems.length,
                completed: resultItems.filter(item => item.status === 'done').length,
                failed: resultItems.filter(item => item.status === 'failed').length,
                status: 'done',
                items: resultItems,
            })
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ batch_id: batchId }),
            })
        })

        await page.route('**/api/v2/pro/batch/**', route => {
            const url = new URL(route.request().url())
            const parts = url.pathname.split('/')
            const batchId = parts[parts.indexOf('batch') + 1] || ''

            if (url.pathname.includes('/audio/')) {
                return route.fulfill({
                    status: 200,
                    contentType: 'audio/wav',
                    body: WAV_HEADER,
                })
            }

            if (route.request().method() === 'DELETE') {
                batchStore.delete(batchId)
                return route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ status: 'cancelled', batch_id: batchId }),
                })
            }

            const batch = batchStore.get(batchId)
            return route.fulfill({
                status: batch ? 200 : 404,
                contentType: 'application/json',
                body: JSON.stringify(batch || { error: 'batch not found' }),
            })
        })

        await page.route('**/api/v2/pro/system/reload', route => route.fulfill({
            status: reloadShouldFail ? 500 : 200,
            contentType: reloadShouldFail ? 'text/plain; charset=utf-8' : 'application/json',
            body: reloadShouldFail
                ? '模型重载失败：缺少 Smoke 权重'
                : JSON.stringify({ status: 'loaded', model_name: 'Smoke Reload Model' }),
        }))

        await page.route('**/api/v2/pro/logs/sources', route => {
            if (logsRouteMode === 'missing') {
                return route.fulfill({
                    status: 404,
                    contentType: 'text/html; charset=utf-8',
                    body: '<!doctype html><html><body><h1>404 Not Found</h1></body></html>',
                })
            }
            return route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    items: [
                        { id: 'app', label: '应用日志', available: true },
                        { id: 'access', label: '访问日志', available: true },
                        { id: 'crash', label: '崩溃日志', available: false },
                        { id: 'local_bridge', label: '本地桥接日志', available: true },
                    ],
                }),
            })
        })

        await page.route('**/api/v2/pro/logs/tail*', route => {
            if (logsRouteMode === 'missing') {
                return route.fulfill({
                    status: 404,
                    contentType: 'text/html; charset=utf-8',
                    body: '<!doctype html><html><body><h1>404 Not Found</h1></body></html>',
                })
            }
            const url = new URL(route.request().url())
            const source = url.searchParams.get('source') || 'app'
            const level = url.searchParams.get('level') || ''

            const sourceItems = {
                app: [
                    {
                        id: 'log_smoke_app_error',
                        source: 'app',
                        timestamp: '2026-03-06T20:01:00+08:00',
                        level: 'ERROR',
                        module: 'api',
                        event: 'MODEL_RELOAD_FAILED',
                        message: '模型重载失败：缺少 Smoke 权重',
                        request_id: 'req_reload',
                        fields: { model: 'Smoke Reload Model' },
                        raw: '[错误][api] 模型重载失败：缺少 Smoke 权重 | request_id=req_reload',
                    },
                ],
                access: [
                    {
                        id: 'log_smoke_access_info',
                        source: 'access',
                        timestamp: '2026-03-06T20:00:00+08:00',
                        level: 'INFO',
                        module: 'api',
                        event: 'SYN_DONE',
                        message: 'Smoke 日志已就绪',
                        request_id: 'req_smoke',
                        fields: { voice_id: '测试角色#default' },
                        raw: '{"request_id":"req_smoke"}',
                    },
                ],
                crash: [],
                local_bridge: [
                    {
                        id: 'log_smoke_bridge_error',
                        source: 'local_bridge',
                        timestamp: '2026-03-06T20:02:00+08:00',
                        level: 'ERROR',
                        module: 'bridge',
                        event: 'BRIDGE_OFFLINE',
                        message: '本地桥接未运行，请使用 StartWebUI.bat 启动 WebUI。',
                        request_id: '',
                        fields: {},
                        raw: '[错误][bridge] 本地桥接未运行，请使用 StartWebUI.bat 启动 WebUI。',
                    },
                ],
            }

            const items = (sourceItems[source] || []).filter(item => !level || item.level === level)
            return route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    items,
                    next_cursor: '128',
                    reset_required: false,
                    source_available: source !== 'crash',
                }),
            })
        })

        await page.goto(baseUrl, { waitUntil: 'networkidle' })
        await page.getByRole('heading', { name: '工作台' }).waitFor()
        await page.getByRole('button', { name: '剧本', exact: true }).click()
        await page.getByRole('heading', { name: '剧本', exact: true }).waitFor()
        await page.locator('button[title="添加台词行"]').evaluate(button => button.click())
        await page.waitForFunction(() => document.querySelectorAll('textarea').length > 1)
        await page.locator('textarea').nth(1).fill('这是一条未解析的剧本行')
        await page.getByRole('button', { name: '发送到任务', exact: true }).waitFor({ timeout: 5000 })
        if (!(await page.getByRole('button', { name: '发送到任务', exact: true }).isDisabled())) {
            throw new Error('script export should be blocked when unresolved rows exist')
        }

        await page.getByRole('button', { name: '任务', exact: true }).click()
        await page.getByRole('heading', { name: '任务', exact: true }).waitFor()
        await page.locator('textarea.text-edit').first().waitFor({ timeout: 5000 })
        await page.locator('textarea.text-edit').first().fill('这是 smoke 测试文本')
        await page.locator('.task-row').first().locator('select.voice-select').first().selectOption('测试角色#default')
        await page.getByRole('button', { name: /全部合成/ }).click()
        await page.locator('.task-row').first().getByText('完成', { exact: true }).waitFor({ timeout: 5000 })
        await page.locator('audio.audio-player').first().waitFor({ timeout: 5000 })

        await page.getByRole('button', { name: '新增行', exact: true }).click()
        await page.locator('textarea.text-edit').last().fill('这是失败任务 A')
        await page.locator('.task-row').nth(1).locator('select.voice-select').first().selectOption('测试角色#default')
        await page.getByRole('button', { name: /全部合成/ }).click()
        await page.locator('.task-row').nth(1).getByText('失败', { exact: true }).waitFor({ timeout: 5000 })
        await page.getByText('最近批次已完成').first().waitFor({ timeout: 5000 })
        await page.locator('.task-row').nth(1).locator('button[title="重试失败行"]').click()
        await page.locator('.task-row').nth(1).getByText('完成', { exact: true }).waitFor({ timeout: 5000 })

        await page.getByRole('button', { name: '新增行', exact: true }).click()
        await page.locator('textarea.text-edit').last().fill('这是失败任务 B')
        await page.locator('.task-row').nth(2).locator('select.voice-select').first().selectOption('测试角色#default')
        await page.getByRole('button', { name: '新增行', exact: true }).click()
        await page.locator('textarea.text-edit').last().fill('这是失败任务 C')
        await page.locator('.task-row').nth(3).locator('select.voice-select').first().selectOption('测试角色#default')
        await page.getByRole('button', { name: /全部合成/ }).click()
        await page.locator('.task-row').nth(2).getByText('失败', { exact: true }).waitFor({ timeout: 5000 })
        await page.locator('.task-row').nth(3).getByText('失败', { exact: true }).waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: '仅恢复失败行', exact: true }).click()
        await page.locator('.task-row').first().getByText('待定', { exact: true }).waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: /全部合成/ }).click()
        await page.locator('.task-row').first().getByText('完成', { exact: true }).waitFor({ timeout: 5000 })
        await page.locator('.task-row').nth(1).getByText('完成', { exact: true }).waitFor({ timeout: 5000 })

        await page.getByRole('button', { name: '音色', exact: true }).click()
        await page.getByRole('heading', { name: '音色', exact: true }).waitFor()
        await page.getByRole('button', { name: '按角色批量改名' }).click()
        await page.locator('.utility-modal input[type="text"]').first().fill('重命名角色')
        await page.locator('.rename-row').filter({ hasText: '测试角色#default' }).locator('input').fill('沉稳')
        await page.getByText('重命名角色#沉稳').waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: '提交批量改名', exact: true }).click()
        await page.getByText('已更新 3 条音色命名').waitFor({ timeout: 5000 })
        await page.getByText('重命名角色').first().waitFor({ timeout: 5000 })

        await page.getByRole('button', { name: 'legacy 导入', exact: true }).click()
        await page.locator('.utility-modal input[type="file"]').setInputFiles(legacyImportFile)
        await page.getByRole('button', { name: '先预检', exact: true }).click()
        await page.getByText('预检摘要').waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: '确认导入', exact: true }).click()
        await page.getByText('导入结果').waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: '关闭', exact: true }).click()
        await page.getByText('Legacy导入角色').first().waitFor({ timeout: 5000 })

        await page.locator('[data-voice-id="重命名角色#沉稳"]').click()
        await page.getByRole('button', { name: '资产', exact: true }).click()
        await page.getByRole('heading', { name: '资产', exact: true }).waitFor()
        await page.getByText('当前绑定目标：重命名角色#沉稳').waitFor({ timeout: 5000 })
        await page.locator('.assets-toolbar select').nth(4).selectOption('selected')
        await page.getByText('已绑定到当前音色').first().waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: '从当前音色解绑', exact: true }).first().waitFor({ timeout: 5000 })
        await page.locator('.assets-toolbar select').nth(4).selectOption('all')
        await page.locator('.assets-toolbar select').nth(3).selectOption('missing')
        await page.getByText('asset_missing').waitFor({ timeout: 5000 })
        await page.locator('.asset-badge.is-transcript-missing').first().waitFor({ timeout: 5000 })

        await page.getByRole('button', { name: '导出', exact: true }).click()
        await page.getByRole('heading', { name: '导出', exact: true }).waitFor()
        await page.getByRole('button', { name: '导出工程文件', exact: true }).waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: '导出任务计划', exact: true }).waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: '导出批量合并音频', exact: true }).waitFor({ timeout: 5000 })

        await page.getByRole('button', { name: '日志', exact: true }).click()
        await page.getByRole('heading', { name: '日志', exact: true }).waitFor()
        await page.locator('select').first().selectOption('access')
        await page.getByText('req_smoke').waitFor({ timeout: 5000 })

        await page.getByRole('button', { name: '系统', exact: true }).click()
        await page.getByRole('heading', { name: '系统', exact: true }).waitFor()
        await page.getByRole('button', { name: '启动服务并加载模型', exact: true }).click()
        await page.getByRole('heading', { name: '日志', exact: true }).waitFor()
        await page.getByText('来自系统页的联动定位').waitFor({ timeout: 5000 })
        await page.getByText('本地桥接未运行，请使用 StartWebUI.bat 启动 WebUI。').first().waitFor({ timeout: 5000 })
        await page.waitForFunction(() => {
            const selects = document.querySelectorAll('select')
            return selects.length >= 2 && selects[0].value === 'local_bridge' && selects[1].value === 'ERROR'
        })
        await page.getByRole('button', { name: '清除联动', exact: true }).click()
        await page.waitForFunction(() => {
            const selects = document.querySelectorAll('select')
            return selects.length >= 2 && selects[1].value === ''
        })

        healthState = 'online'
        bridgeOnline = true
        reloadShouldFail = true
        await page.reload({ waitUntil: 'networkidle' })
        await page.getByRole('button', { name: '系统', exact: true }).click()
        await page.getByRole('heading', { name: '系统', exact: true }).waitFor()
        await page.getByRole('button', { name: '重载模型', exact: true }).click()
        await page.getByRole('heading', { name: '日志', exact: true }).waitFor()
        await page.getByText('模型重载失败：缺少 Smoke 权重').first().waitFor({ timeout: 5000 })
        await page.waitForFunction(() => {
            const selects = document.querySelectorAll('select')
            return selects.length >= 2 && selects[0].value === 'app' && selects[1].value === 'ERROR'
        })

        await page.evaluate(() => {
            const remoteConfig = [{
                id: 'tts_remote_smoke',
                name: '远程 Smoke',
                baseUrl: 'http://remote-smoke:9880',
                apiKey: '',
            }]
            localStorage.setItem('unitale_tts_configs', JSON.stringify(remoteConfig))
            localStorage.setItem('unitale_tts_current', 'tts_remote_smoke')
        })
        await page.reload({ waitUntil: 'networkidle' })
        await page.getByRole('button', { name: '系统', exact: true }).click()
        await page.getByRole('heading', { name: '系统', exact: true }).waitFor()
        await page.getByText('远程模式').first().waitFor({ timeout: 5000 })
        await page.getByText('本地桥接不适用').first().waitFor({ timeout: 5000 })

        healthState = 'online'
        bridgeOnline = true
        reloadShouldFail = false
        logsRouteMode = 'missing'
        await page.evaluate(() => {
            const localConfig = [{
                id: 'tts_local_smoke',
                name: '本地默认',
                baseUrl: 'http://localhost:9880',
                apiKey: '',
            }]
            localStorage.setItem('unitale_tts_configs', JSON.stringify(localConfig))
            localStorage.setItem('unitale_tts_current', 'tts_local_smoke')
        })
        await page.reload({ waitUntil: 'networkidle' })
        await page.getByRole('button', { name: '系统', exact: true }).click()
        await page.getByRole('heading', { name: '系统', exact: true }).waitFor()
        await page.getByText('当前后端为旧进程，需要重启以启用日志中心').waitFor({ timeout: 5000 })
        await page.getByText('重启 StartWebUI.bat 或重启本地 API 后，再回到日志页刷新。').first().waitFor({ timeout: 5000 })
        await page.getByRole('button', { name: '日志', exact: true }).click()
        await page.getByRole('heading', { name: '日志', exact: true }).waitFor()
        await page.getByText('后端在线，但未提供日志接口').waitFor({ timeout: 5000 })
        await page.getByText('当前连接的本地后端未加载日志接口').waitFor({ timeout: 5000 })

        await browser.close()
        console.log('WebUI smoke passed')
    } catch (error) {
        const browser = await chromium.launch({ headless: true }).catch(() => null)
        if (browser) {
            const page = await browser.newPage()
            await page.goto(baseUrl).catch(() => {})
            await page.screenshot({ path: join(OUTPUT_DIR, 'smoke-failure.png'), fullPage: true }).catch(() => {})
            await browser.close().catch(() => {})
        }
        throw error
    } finally {
        await new Promise(resolve => server.close(resolve))
    }
}

run().catch(error => {
    console.error(error)
    process.exit(1)
})
