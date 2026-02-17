# P2 开发计划：情绪管理 UI（v2 assets + v2 voices）

最后更新：2026-02-09  
目标：新增一个桌面端页面“情绪管理”，按角色分组管理多情绪参考音频（assets），并把参考音频绑定到 v2 voices 的 `ref_asset_ids`，支持试听/删除/compile。

---

## 1. 范围与不做项

- 本阶段做：
  - 新页面（与旧 `语音设置` 并存），完全走 v2 API：`/api/v2/assets/audio`、`/api/v2/voices`、`/api/v2/voices/{id}/compile`。
  - 角色分组视图：选择角色后按情绪 tab 展示参考音频列表。
  - 上传参考音频：选择语言、情绪标签、音频文件、备注。
  - 绑定/解绑：把选中的 `asset_id` 加入/移出当前 `voice_id = character#emotion` 的 `ref_asset_ids`。
  - 试听：优先直接播放 meta.path（本机存在），否则下载 `/content` 到临时文件播放。
  - 删除：先尝试从 `ref_asset_ids` 解绑，再删除 asset。
  - Compile：对当前 voice 执行 compile，支持 compile all refs。
- 本阶段不做：
  - 文本页/任务页迁移到 v2 synth/jobs（P3 做）。
  - 自动从“指令”解析情绪（可后续加）。
  - 更复杂的 ref 列表排序/搜索/批量元数据编辑（后续增强）。

---

## 2. UI 结构（页面布局）

- 左侧（角色与 voice 配置）：
  - API Host/Port + 刷新按钮（读写 `app_config.json` 的 `api_host/api_port`）。
  - 角色选择（下拉）+ 新建角色（创建 `{character}#default` voice）。
  - 当前情绪 voice 的字段编辑：
    - `mode`
    - `selection_policy`（`random_per_text/fixed/random_per_request`）
    - `prompt_text`（必填）
    - `instruct_text`（可选）
    - 保存 voice
    - compile（可选 compile all refs）
- 右侧（情绪 tabs + assets 表）：
  - 情绪 tab：默认 8 个 + 从现有 voices 的 emotion 合并补齐
  - assets 表：`asset_id/language/note/created_at/path/linked`
  - 操作按钮：试听选中、绑定到 voice、从 voice 解绑、删除选中
  - 上传区：语言下拉、情绪标签输入、选择文件、备注、上传

---

## 3. API 交互与规则

- 角色来源：
  - `GET /api/v2/voices`，按 `character` 分组；若缺 `character`，用 `name` 按 `#` 拆分推断。
- 情绪列表来源：
  - 默认 8 个情绪 + 当前角色下 voices 的 emotion 集合；本阶段不强依赖 assets 推断。
- assets 列表：
  - `GET /api/v2/assets/audio?character={c}&emotion={e}&kind=ref`
- 上传：
  - `POST /api/v2/assets/audio`（multipart）：`file`, `character`, `emotion`, `language`, `note`
- voice 绑定：
  - voice_id 固定：`{character}#{emotion}`
  - 若 voice 不存在：用当前页面字段 `prompt_text/mode/instruct_text/selection_policy` 创建 `POST /api/v2/voices`
  - 然后 `PUT /api/v2/voices/{voice_id}` 更新 `ref_asset_ids`
- 删除：
  - 尽量先 `PUT /api/v2/voices/{voice_id}` 移除 ref，再 `DELETE /api/v2/assets/audio/{asset_id}`
- 试听：
  - `GET /api/v2/assets/audio/{asset_id}` 拿 meta
  - 若 meta.path 本地存在，直接播放
  - 否则 `GET /content` 下载到 `./data/ui_tmp/preview_{asset_id}.wav` 播放
- Compile：
  - `POST /api/v2/voices/{voice_id}/compile`，可选 `?all=1`

---

## 4. 验收清单（必须）

1. 新页面在导航栏可打开，不影响现有页面。
2. 能刷新出 v2 voices 的角色列表，并按角色切换。
3. 角色下可切换默认 8 个情绪 tab。
4. 上传参考音频：上传成功后能在表格中看到新 asset。
5. 绑定：选中 asset -> 绑定到 voice 后，`GET /api/v2/voices/{voice_id}` 中 `ref_asset_ids` 包含该 asset。
6. 试听：能播放本地 path 或下载后的临时文件。
7. 删除：删除后 assets 列表消失，并且 voice 的 `ref_asset_ids` 不再包含该 asset（best-effort）。
8. Compile：能对当前 voice 执行 compile（前提 prompt_text 有值）。

---

## 5. 实现文件与改动点

- 新增：`ui/emotion_voices.py`
- 接入导航：`ui/main_window.py`
- 依赖配置：`core/config_manager.py`（P0 已加）
- 设置入口：`ui/settings.py`（P0 已加）

