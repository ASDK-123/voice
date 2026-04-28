# Pro 重构审查报告（2026-03-03）

## 1. 审查范围与方法

本次审查基于以下计划与实现文件对照：

- 计划文件：
  - `AI1_BACKEND_PLAN.md`
  - `AI2_FRONTEND_PLAN.md`
- 后端实现：
  - `core/api_v2_routes.py`
  - `core/server/routes_v2_misc.py`
  - `core/api_legacy.py`
  - `API_USAGE.md`
- 前端实现：
  - `peiying/Unitale/unitale-app/src/App.vue`
  - `peiying/Unitale/unitale-app/src/api/pro_client.ts`
  - `peiying/Unitale/unitale-app/src/stores/pro_system.ts`
  - `peiying/Unitale/unitale-app/src/stores/pro_voice.ts`
  - `peiying/Unitale/unitale-app/src/stores/pro_task.ts`
  - `peiying/Unitale/unitale-app/src/views/pro_workspace/*.vue`
  - `peiying/Unitale/unitale-app/src/types/pro.ts`
  - `peiying/Unitale/unitale-app/src/types/index.ts`

并执行了前端构建验证：

- 命令：`npm run build`（目录：`peiying/Unitale/unitale-app`）
- 结果：失败（存在历史遗留类型错误 + 1 条 Pro 新增错误）

---

## 2. 总体结论

1. 后端 AI1 计划中的 Pro API 主体已落地，接口基本齐全。
2. 前端 AI2 计划中的 Pro Workspace 骨架已落地，Tab、Store、组件和 Mock 流程均已搭建。
3. 当前未达到“可稳定替代原 UI 对应能力”的状态，主要缺口在：
   - Pro 模块与真实后端契约细节不一致（状态枚举、鉴权、字段名）；
   - Pro 音色管理仍以本地 Mock 交互为主，缺乏原 UI 的持久化管理能力；
   - 若切换到真实接口，存在多处会直接影响功能可用性的 bug。

---

## 3. 计划完成度对照

### 3.1 AI1 后端计划完成度

已完成：

1. 批量 API 已新增：
   - `POST /api/v2/pro/batch`：`core/api_v2_routes.py:899`
   - `GET /api/v2/pro/batch/<batch_id>`：`core/api_v2_routes.py:977`
   - `GET /api/v2/pro/batch/<batch_id>/audio/<row_id>`：`core/api_v2_routes.py:1016`
   - `DELETE /api/v2/pro/batch/<batch_id>`：`core/api_v2_routes.py:1061`
2. 系统控制 API 已新增：
   - `POST /api/v2/pro/system/unload`：`core/server/routes_v2_misc.py:241`
   - `POST /api/v2/pro/system/reload`：`core/server/routes_v2_misc.py:297`
3. 健康检查增强字段已加入：
   - `model_loaded/gpu_name/vram_used_mb/vram_total_mb`：`core/server/routes_v2_misc.py:42-63`
4. CORS 已存在：
   - `CORS(app)`：`core/api_legacy.py:381`
5. `output/` 静态访问已挂载：
   - `GET /assets/output/<path:filename>`：`core/api_legacy.py:1630-1633`
6. API 文档已追加 Pro 章节：
   - `API_USAGE.md:439` 起

结论：AI1 结构性交付基本完成，但存在前后端契约细节问题（见第 5 节）。

### 3.2 AI2 前端计划完成度

已完成：

1. 类型与导出：
   - `src/types/pro.ts` 已创建：`peiying/Unitale/unitale-app/src/types/pro.ts:1`
   - `src/types/index.ts` 已追加导出：`peiying/Unitale/unitale-app/src/types/index.ts:9`
2. Pro API 客户端已创建：
   - `src/api/pro_client.ts`：`peiying/Unitale/unitale-app/src/api/pro_client.ts:1`
3. 三个 Pro Store 已创建：
   - `pro_system.ts`、`pro_voice.ts`、`pro_task.ts`
4. `App.vue` 三处接入已完成：
   - import：`App.vue:16`
   - tab：`App.vue:27`
   - template 渲染：`App.vue:63`
5. Pro Workspace 六个组件已创建并接入：
   - `ProWorkspace.vue`、`ProSystemSettings.vue`、`ProVoiceManager.vue`
   - `ProVoiceWizardModal.vue`、`ProTaskPlanTable.vue`、`ProStorageCleanup.vue`

结论：AI2 的“界面骨架 + Mock 可交互”已实现，但“与原 UI 能力等价的可用重构”尚未完成。

---

## 4. 当前缺少的功能（相对原前端能力与计划目标）

1. Pro 音色“新建向导”未接后端持久化，仅本地 push 到内存数组。
   - 证据：`ProVoiceWizardModal.vue:44-52`
   - 对比原能力：原 Voice Store 支持 create/update/delete 持久化 CRUD（`stores/voices.ts:89-135`）。

2. Pro 模块未复用现有全局后端配置（如 baseUrl/apiKey 配置链路），仍多处硬编码默认地址。
   - 证据：`pro_client.ts:7`、`pro_voice.ts:27`、`pro_task.ts:26`、`ProStorageCleanup.vue:24`
   - 对比原能力：原模块通过 `tts.currentConfig.baseUrl` 初始化客户端（`stores/voices.ts:68-73`）。

3. Pro 模块缺少原 Voice 管理中的编辑/删除等管理闭环。
   - 证据：Pro 侧仅“选择 + 本地新建”；原 UI 有 edit/delete（`VoiceManager.vue:221-229`）。

4. Mock 与真实后端切换机制未产品化（仅常量开关，默认一直 Mock）。
   - 证据：`pro_client.ts:11` 固定 `const USE_MOCK = true`
   - 影响：当前默认并不会真正验证新后端链路。

---

## 5. 已完成重构部分中的 bug / 风险

### P0（高优先级，直接影响可用性）

1. 批量任务失败状态前后端不一致：后端返回 `failed`，前端只识别 `error`。
   - 后端写入：`core/api_v2_routes.py:883`
   - 前端状态类型：`types/pro.ts:42`
   - 前端统计/样式：`pro_task.ts:75`、`ProTaskPlanTable.vue:45-52`
   - 影响：失败行可能被当成 `idle` 展示，失败计数与错误提示异常。

2. Pro 接口与音频播放在启用 API Key 时会失效（客户端未带鉴权头；audio URL 也受保护）。
   - 鉴权要求：`core/api_legacy.py:478-490`
   - Pro API 请求未带 `X-API-Key`：`pro_client.ts` 各 `fetch` 调用（如 `101/170/192/205/219`）
   - 音频路由也被 `@require` 保护：`core/api_v2_routes.py:1017`
   - 影响：安全部署下，Pro 页面核心功能不可用，`<audio>` 直接播放会 401。

3. 缓存清理响应字段前后端不一致。
   - 后端返回：`deleted`、`bytes_reclaimed`（`core/api_v2_routes.py:480-483`）
   - 前端期望：`deleted_count`、`freed_mb`（`pro_client.ts:228`，`ProStorageCleanup.vue:65/69`）
   - 影响：切到真实接口后，弹窗结果字段会显示 `undefined` 或不正确。

### P1（中优先级，功能正确性问题）

1. Pro 音色搜索逻辑未真正生效（界面仍按未过滤分组渲染）。
   - 空状态判断用了 `filteredVoices`：`ProVoiceManager.vue:102`
   - 实际列表渲染用 `voiceStore.characters`：`ProVoiceManager.vue:110`
   - 影响：输入搜索词后列表不会按关键词收敛。

2. 在线状态与模型加载状态耦合，模型卸载后会显示“离线”。
   - `isOnline` 由 `result.status === 'ok'` 决定：`pro_system.ts:30`
   - 后端在模型未加载时 `status = degraded`：`routes_v2_misc.py:40-43`
   - 影响：服务在线但模型卸载时，UI 给出误导性“离线”状态。

3. 批次结束状态兼容性不足。
   - 轮询停止条件仅 `done/cancelled`：`pro_task.ts:150`
   - 计划文档曾定义 `completed`（`AI2_FRONTEND_PLAN.md:130`）
   - 影响：若后端按 `completed` 返回，会导致前端轮询不停。

4. Pro 健康类型与后端返回可空值不一致。
   - 后端 GPU 字段可 `null`：`routes_v2_misc.py:56-62`
   - 前端类型写成必填 number/string：`types/pro.ts:53-55`
   - 影响：在无 GPU 或异常降级时会出现显示/类型不一致问题。

### P2（低优先级，工程质量）

1. Pro 新增文件存在 TS 严格模式错误（未使用导入）。
   - `onUnmounted` 未使用：`pro_system.ts:5`
   - 构建报错可复现：`npm run build`

---

## 6. 构建与验证结论

1. `npm run build` 失败，当前前端主分支存在多处历史遗留 TS 错误。
2. 本次重构新增中，明确可定位到 1 条 Pro 相关编译错误（`pro_system.ts` 未使用导入）。
3. 由于全量构建失败，无法给出“生产可发布”结论；当前只能认定为“功能原型 + 部分联调阶段”。

---

## 7. 建议的修复优先级（仅建议，不含代码改动）

1. 先统一批量状态契约（`failed` vs `error`，批次 `done/completed`）并同步前后端类型。
2. 给 ProApiClient 加入与现有客户端一致的鉴权头逻辑；明确 audio 播放鉴权方案。
3. 修正清理接口字段映射（前端字段与后端响应一致）。
4. 修复 ProVoiceManager 搜索分组渲染逻辑。
5. 解除 `isOnline` 与模型加载状态耦合（在线性与模型状态分别展示）。
6. 将 Pro 音色向导接入真实 `/api/v2/voices`，补齐至少 create + refresh 的持久化闭环。
7. 最后处理编译红线（含 Pro 与历史遗留错误），再做一次完整 build 验证。

