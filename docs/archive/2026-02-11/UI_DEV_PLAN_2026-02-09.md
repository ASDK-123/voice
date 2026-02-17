# UI开发优化方案（扫描审查稿）

最后更新：2026-02-09  
适用范围：`ui/`（PyQt5 + qfluentwidgets）对齐当前后端 v2（`/api/v2/*`，assets/voices/synthesize/jobs/merge）  
关联文档：`CACHE_QUEUE_DESIGN.md`，`EMOTION_VOICE_DESIGN.md`，`API_USAGE.md`

---

## 0. 一句话结论

当前桌面 UI 仍以 v1 与“本地直推理”为中心，和你已经完成的 v2（SQLite assets、结构化错误码 + request_id、emotion voices、jobs/merge）存在明显断层。UI 的最短升级路径是：先把 UI 变成“v2 优先的客户端”，再补齐“情绪/资产管理 UI（按角色分组）+ voice 绑定 ref_asset_ids”，最后再把文本页/任务页迁移到 v2 jobs 以吃到缓存与队列收益。

---

## 1. 扫描结果（现状与证据）

### 1.1 UI 导航与职责

- 主窗口导航包含：文本编辑、任务计划、语音设置、API 服务、设置。见 `ui/main_window.py:58`。
- 任务计划页本质上是“本地分段 + 本地输出管理 + 本地合并”，并不走 v2 jobs。见 `ui/task_plan.py:1`、`ui/main_window.py:506`。
- 语音设置页管理的是“本地 VoiceConfig 列表”，并在 UI 内直接调用 `model.add_zero_shot_spk()`/`save_spkinfo()`。见 `ui/voice_settings.py:74`、`ui/voice_settings.py:82`。

### 1.2 UI 的 API 页仍停留在 v1

- API 文档弹窗写死了 v1 端点（根路径 `/`、`/speakers`、`/api/tts`、`/api/health`）。见 `ui/api_page.py:39`、`ui/api_page.py:56`、`ui/api_page.py:70`、`ui/api_page.py:88`。
- API 页“刷新角色列表”走 `GET /speakers`（v1）。见 `ui/api_page.py:547`。
- API 页的流式开关与 spk_cache 开关走 v1 的 `/api/toggle_stream`、`/api/toggle_spk_cache`。见 `ui/api_page.py:603`、`ui/api_page.py:630`。

### 1.3 UI 内嵌 API Server 的“角色配置适配器”不满足 v2 voices CRUD

- UI 启动 API server 时把 `RuntimeCharacterConfig`（仅实现 `get_character`、`list_characters`）注入给后端。见 `ui/api_page.py:131`、`ui/api_page.py:458`、`ui/api_page.py:465`。
- 但 v2 `GET/POST/PUT/DELETE /api/v2/voices` 依赖 `get_all_characters/upsert_character/delete_character/save`。见 `core/api_v2_routes.py:132`、`core/api_v2_routes.py:179`、`core/api_v2_routes.py:242`、`core/api_v2_routes.py:207`。
- 这意味着：只要你未来在桌面 UI 中调用 v2 voices（为了“按角色分组+情绪管理”），当前的内嵌 server 会直接报错或返回 500（character_config 不可用或缺方法）。

### 1.4 Bridge 启动方式不规范（硬编码 Python 路径）

- UI 启动 bridge 时硬编码本机 Python 路径。见 `ui/api_page.py:680`。
- 这会导致：换电脑、换 Python 安装路径、用 `.pixi` 环境时桥接无法启动。

### 1.5 数据模型的“UI本地 VoiceConfig”与 v2 emotion voices 不一致

- UI 侧 `core/models.py` 的 `VoiceConfig` 只有：`name/mode/prompt_text/prompt_audio/instruct_text/color`，没有 `character/emotion/ref_asset_ids/selection_policy`。见 `core/models.py:3`。
- 后端 v2 voice 事实上已经支持：`ref_asset_ids`、`character/emotion`、`prompt_audio_asset_id`、compile all 等。见 `core/api_v2_routes.py:154`、`core/api_v2_routes.py:173`、`core/api_v2_routes.py:176`、`core/api_v2_routes.py:249`。

---

## 2. UI 升级的目标状态（你要的“情绪管理 UI”落到产品行为）

### 2.1 你提出的核心需求，转成 UI 可见能力

- 角色分组：左侧是角色列表（Tom/胡桃/旁白…），点击角色后进入该角色的情绪管理视图。
- 默认 8 种情绪：UI 提供默认情绪列表，同时允许你输入自定义情绪标签并上传参考音频绑定。
- 上传参考音频时选情绪标签：上传对话框字段与截图一致，至少包含 `language`、`emotion`、`audio file`，并自动带上当前 `character`。
- 同一情绪多条参考音频：同一 `(character, emotion)` 下允许多个 ref 音频，UI 显示数量、列表与试听。
- 随机化但不破坏缓存：默认采用“同文本稳定随机”策略（后端已实现 `random_per_text`，核心是同一个文本会稳定选择同一个 ref）。见 `core/emotion_selector.py:13`、`core/emotion_selector.py:26`。
- 缺省回退：请求某情绪没有 ref 时，回退到该角色的 `default`（后端已实现 fallback）。见 `core/emotion_selector.py:86`。
- voice 绑定 ref_asset_ids：每个 `voice_id = character#emotion` 保存 `ref_asset_ids[]`，UI 能一键“把当前筛选的 ref 资产加入 voice”并持久化。

### 2.2 UI 与 v2 API 的映射（不再手写一套逻辑）

- 参考音频 assets：`POST /api/v2/assets/audio` 上传，`GET /api/v2/assets/audio` 列表，`GET /api/v2/assets/audio/<id>/content` 试听，`DELETE /api/v2/assets/audio/<id>` 删除。见 `core/api_v2_routes.py:36`、`core/api_v2_routes.py:47`、`core/api_v2_routes.py:98`、`core/api_v2_routes.py:111`。
- Emotion voices：`/api/v2/voices` CRUD，`/api/v2/voices/<id>/compile` 预编译（支持 `?all=1` 编译该 voice 的所有 ref）。见 `core/api_v2_routes.py:129`、`core/api_v2_routes.py:249`、`core/api_v2_routes.py:282`。
- 合成：`POST /api/v2/synthesize`（支持 `character/emotion` 或 `voice_id`，支持 `variation_seed/selection_policy/selected_ref_asset_id` 等）。见 `core/api.py:1626`、`core/api.py:601`。
- 队列：后续 UI 迁移到 `POST /api/v2/jobs`，统一吃到缓存与限流。见 `core/api_v2_routes.py:308`。

---

## 3. 建议的 UI 技术路线（按“最短可执行”排序）

这里给两条路，你可以先审查我推荐的默认路。

### 3.1 路线 A（推荐）：UI 做 v2 客户端，API 做唯一事实源

- UI 所有“情绪/资产/voice 管理”都通过 v2 API 完成。
- UI 内嵌 server 仍可保留，但必须让 server 使用“完整 CharacterConfig 接口”，否则 v2 voices 不能用。
- 中长期：把“任务计划的生成/合并”也切到 v2 jobs/merge，GUI 不再自己跑推理 worker，只负责编排与播放。

推荐原因：
- 你已经把 v2 的缓存、SQLite assets、错误码、request_id、bridge 迁移做完了，UI 继续走本地 worker 会把系统分裂成两套。
- 你希望“同输入必命中缓存”，以及“缓存跨 UI/API 复用”，这只有 UI 走 v2 才能真正成立（见 `CACHE_QUEUE_DESIGN.md` 目标 2.1 第 4 条）。

### 3.2 路线 B（不推荐但可行）：继续本地 worker，单独补 UI 的情绪管理

- UI 仍然在进程内推理，不依赖 v2 jobs。
- 新增“情绪管理 UI”只负责维护本地配置与文件路径，不走 v2 assets/voices。

不推荐原因：
- 你已经选择“未来扩展上 SQLite 更稳”，本地 UI 再做一套索引会重复建设。
- 随机化、缓存键、voice 更新失效等规则会在两套链路中变得难维护。

---

## 4. 具体开发顺序（你可以按这个排期拆任务）

### 4.1 P0：把 UI 先对齐 v2（让后续页面有稳定底座）

目标：UI 不再写死 v1 文档与 v1 端点，至少能正确“识别 v2 server”和显示 request_id/错误码。

- 抽一个 UI 侧 API Client 层（建议新建 `ui/services/api_client_v2.py`，或扩展 `client/api_client.py`）。
- UI Settings 增加以下配置项：
- `api_base_url`（或 host/port），`api_key`，`timeout_s`，`prefer_v2=true`。
- API 页刷新角色列表改走 `GET /api/v2/voices`，并按 `name` 或 `character` 分组显示。
- API 文档弹窗不再硬编码 v1，建议直接展示 `API_USAGE.md` 的关键片段，或写一个 v2 简表。
- Bridge 启动不再硬编码 Python 路径，至少用 `sys.executable` 或读取 `.pixi` 环境的解释器路径（这一步属于 UI 工程规范修复）。现状见 `ui/api_page.py:680`。

验收：
- UI 能显示 v2 health（`/api/v2/health`）与 v2 voices 列表，不依赖 v1 `/speakers`。
- 任意 API 调用失败时，UI 能读到并展示 `error.code` 与 `request_id`（v2 JSON 错误格式见 `core/v2/http.py:38`）。

### 4.2 P1：修复“内嵌 API server 的 CharacterConfig 兼容性”（否则情绪管理 UI 无法落地）

目标：当 UI 点击“启动 API 服务”时，`/api/v2/voices` CRUD 必须可用。

推荐实现方式：
- 内嵌 server 不再注入 `RuntimeCharacterConfig`，而是注入“真正的可持久化 CharacterConfig”。
- 至少要满足：`get_character/list_characters/get_all_characters/upsert_character/delete_character/save`。后端依赖点见 `core/api_v2_routes.py:132`。

验收：
- UI 启动 server 后，浏览器访问 `GET /api/v2/voices` 返回 200 且 items 可用。
- `POST /api/v2/voices` 能创建 `character#emotion` voice，重启 UI 后仍存在（证明持久化）。

### 4.3 P2：新增“情绪管理 UI”（按角色分组 + 上传时选情绪标签 + voice 绑定 ref_asset_ids）

目标：提供一个新页面，完整覆盖你截图中的“上传参考音频”流程，并且把上传结果绑定到 voice 上。

页面建议结构（最少实现）：
- 左侧角色列表：显示角色名与情绪数量；支持创建/删除角色（删除前提示影响的 voices/assets）。
- 右侧情绪面板：情绪 tab（默认 8 个 + 自定义输入）；每个 tab 下是 ref 音频 assets 表格。
- 上传对话框字段：
- `language` 下拉（默认 `zh`）
- `emotion` 文本（默认 `default`，允许自定义）
- `audio file` 文件选择
- `note` 可选
- 行为按钮：
- “上传并绑定”：上传 asset 后，把其 `asset_id` 加入当前 `voice_id=character#emotion` 的 `ref_asset_ids` 并 `PUT /api/v2/voices/<id>` 保存。
- “试听”：`GET /api/v2/assets/audio/<id>/content`
- “删除”：先解绑（从 `ref_asset_ids` 移除），再 `DELETE /api/v2/assets/audio/<id>`
- “编译”：`POST /api/v2/voices/<id>/compile`，支持 `?all=1`。
- “随机策略”：在 voice 详情里设置 `selection_policy`（默认 `random_per_text`，见 `core/emotion_selector.py:26`）。

验收：
- 你可以为同一角色同一情绪上传多条 ref 音频，列表可见、可试听、可删除。
- 生成时若请求该情绪无 ref，则自动用 `default`（UI 提示已回退）。

### 4.4 P3：把“文本页/任务页”逐步迁移到 v2（吃到缓存与 jobs）

目标：用户在桌面里点“运行”不再走本地 worker，而是走 `/api/v2/synthesize` 或 `/api/v2/jobs`，从而共享缓存/队列/合并/资产管理。

- 文本页最小改造：增加 `character` + `emotion` 选择器，或者直接选择 `voice_id`（以 `Tom#happy` 的形式展示）。
- 任务页最小改造：把“运行单段/运行全部”改为创建一个 job，并轮询 `GET /api/v2/jobs/<id>` 更新状态。
- 合并功能优先走 v2 `/api/v2/merge`，从而把合并结果也存成 v2 asset（后端已实现）。见 `core/api_v2_routes.py:359`。

验收：
- 重复运行同一段文本，第二次能命中 v2 缓存，速度明显提升，并在 UI 可见“cache hit”（可从响应头或 v2 meta 中显示）。

---

## 5. 关键交互与“零基础解释”（避免你未来自己都忘了）

- 为什么要把 ref 音频做成 assets：
- 因为 assets 是“统一资源库”，不仅 UI 要用，bridge、API、jobs、merge 都要用，且已经落地 SQLite 索引（`data/api_v2_assets.sqlite3`）。
- 为什么默认随机策略是 `random_per_text`：
- 你希望“同一输入每次输出完全一致并命中缓存”，所以随机必须是“可重复的随机”。后端用文本+种子稳定选 ref，既有多样性又不破坏缓存。
- 什么是 `variation_seed`（重Roll）：
- 当你想“同一句话也能出不同风格”，就显式改变 `variation_seed`，这样缓存键也会变化，旧缓存不会被覆盖。

---

## 6. 风险清单与规避

- UI 卡顿：
- 任何 HTTP 请求都不要在 UI 主线程里做，统一放到 QThread/线程池，并把结果用 signal 回主线程更新 UI。
- 内嵌 server 与 UI 状态互相修改：
- 只要 server 直接读写 UI 内存结构（例如 `voice_interface.voice_configs`），都会引入线程安全与持久化问题。推荐让 server 读写“文件/SQLite”作为事实源。
- 随机化导致缓存爆炸：
- 避免默认使用 `random_per_request`；只有用户明确选择“多版本/重Roll”时才启用，并配合 `variation_seed` 控制数量。

---

## 7. 我需要你确认的 3 个 UI 决策（不确认也能做，但会影响实现细节）

1. 你希望“情绪管理 UI”是：
- 一个新页面（推荐，和旧 voice_settings 并存），还是直接改造现有 `ui/voice_settings.py`？
2. 你希望桌面端最终的“合成链路”是：
- 默认走 v2 API（推荐，和缓存/jobs 一致），还是默认保留本地 worker（只在需要时用 API）？
3. 你希望 UI 内“启动 API 服务”的实现是：
- 继续内嵌在 UI 进程里（共享模型，启动快），还是改为独立子进程（更稳、但可能重复加载模型）？

---

## 8. 下一步建议（你审查后我按你的选择推进）

如果你认可路线 A，我建议下一步先做 P0 + P1：
- P0 是 UI 改造的“底座”，否则新增页面每个地方都要自己处理错误码/request_id。
- P1 是情绪管理 UI 的前置条件，否则 v2 voices 无法在 UI 内真正跑通。

