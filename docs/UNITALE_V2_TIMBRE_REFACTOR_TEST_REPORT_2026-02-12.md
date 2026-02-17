# Unitale v2 音色重构测试报告

日期：2026-02-12
范围：`peiying/Unitale/index.html` 的 v2 音色管理改造

## 1. 环境与前置

1. API 服务端口：`127.0.0.1:9880`
2. 启动方式：手动启动进程
   - `.pixi\\envs\\default\\python.exe core\\api.py --config "config\\super_agent.json" --host 127.0.0.1 --port 9880`

## 2. 后端 API 冒烟

### 2.1 health / voices / assets / synth

结果：通过

- `GET /api/v2/health`：`ok`，`model_loaded=true`
- `GET /api/v2/voices`：`voice_count=18`
- `GET /api/v2/assets/audio`：`asset_count=18`
- `POST /api/v2/synthesize`：成功输出文件
  - 输出：`output/unitale_v2_smoke.wav`
  - 大小：`698960` bytes

### 2.2 voices CRUD

结果：通过

- 新建：`UnitaleSmoke#default`
- 查询：成功返回 `name=UnitaleSmoke#default`
- 更新：`prompt_text=smoke-updated`
- 删除：`status=deleted`

### 2.3 assets 上传/查询/删除

结果：通过

- 上传成功：`asset_id=ref_009ec32c1656`
- 查询成功：`character=UnitaleSmoke`
- 删除成功：`status=deleted`

## 3. 前端加载冒烟

结果：通过（基础加载）

- 使用 Edge headless 加载本地页面：
  - `file:///C:/Users/lilei/Desktop/voice/peiying/Unitale/index.html`
- DOM 中检测到：`data-v-app`（说明 Vue 已挂载）
- 产物：`output/unitale_dom_dump.html`

说明：该项验证了页面基础可加载与挂载成功；未覆盖“逐按钮点击”的全交互自动化回归。

## 4. 结论

本次改造对应的核心链路（v2 接口可用性 + 页面可挂载）测试通过。

剩余建议（可选）：

1. 补一轮手工 UI 回归（切到“音色资源库”页，执行 voice 新建/编辑、asset 上传/绑定、角色绑定 voiceId、单句合成）。
2. 若需要全自动 UI 回归，可后续引入 Playwright。
