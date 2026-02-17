# 项目当前更新总结 + v2 统一后的同步说明（2026-02-09）

本文回答三个问题：
1. 目前仓库已经更新了什么（P0/P1/P2/P3 的结果）。
2. 为什么之前“语音设置”和“情绪管理(v2)”会不同步，以及现在项目如何做到统一（方案 C 已落地）。
3. 当前项目是如何处理“桌面 UI / 后端 API / 本地推理 / bridge”的关系与调用链路的。

---

## 1. 当前更新情况（以 2026-02-09 代码为准）

### 1.1 P0：UI 对齐 v2（配置与基础规范）
- `core/config_manager.py`：新增 UI 侧的 v2 配置项，写入 `app_config.json`。
  - `api_host` / `api_port` / `api_key`：给 UI 做 v2 客户端用。
  - `v2_voices_config_path`：v2 voices JSON 文件路径（v2 单一数据源）。
  - `bridge_python`：用于启动 `bridge.py` 时指定解释器（可选）。
- `ui/settings.py`：新增“API v2 设置”区域，可视化编辑上述配置项。
- `ui/api_page.py`：
  - API 文档弹窗改成 v2 优先的说明（v1 仍保留兼容提示）。
  - voices 列表刷新改走 `GET /api/v2/voices`，并在 UI 配了 `api_key` 时自动带 `X-API-Key`。
  - 启动 bridge 不再硬编码 Python 路径，改为优先用 `bridge_python`，否则用当前解释器 `sys.executable`。

### 1.2 P1：修复内嵌 API Server 的 v2 voices CRUD
- `ui/api_page.py` 内嵌启动 server 时，注入 `core/api.py:CharacterConfig`（完整 CRUD + `save()`）。
- 如果 UI 配了 `api_key`，启动 server 时会设置进程内环境变量 `V2_API_KEY`，从而让 v2 接口鉴权真正生效。

### 1.3 P2：新增“情绪管理 UI”页面（完全走 v2）
- 新增页面：`ui/emotion_voices.py`（导航已接入 `ui/main_window.py`，名称“情绪管理”）。
- 该页面只通过 HTTP 调用 v2 API：
  - `GET/POST/PUT/DELETE /api/v2/voices`：按 `character` 分组显示角色，并对 `voice_id = character#emotion` 进行创建/更新/compile。
  - `GET/POST/DELETE /api/v2/assets/audio`：上传/列出/删除参考音频（ref assets），并支持试听。
  - 绑定/解绑通过更新 voice 的 `ref_asset_ids` 实现。

### 1.4 P3：方案 C 落地（语音设置页也改走 v2 + 合成默认走 v2）
- `ui/voice_settings.py`：语音设置页默认加载/保存/应用 `v2_voices_config_path` 指向的 voices 文件（v2 单一数据源）。
  - 新增 `⬆️ 导入旧配置到 v2`：把旧 `config/config.json` 导入到 v2 voices，并把参考音频落到 v2 assets（SQLite + `data/assets/audio/*`）。
  - 选择“参考音频”时会自动导入到 v2 assets，并绑定到当前 voice 的 `ref_asset_ids`。
  - 保存/应用/导入后会 best-effort 调用 `POST /api/v2/voices/reload`（若 API 服务在运行）以刷新后端内存视图。
- `core/api_v2_routes.py`：新增 `POST /api/v2/voices/reload`，用于“文件已被外部更新（UI 直写 JSON）”后的热刷新。
- `core/api.py`：修复 `CharacterConfig.load_characters()` reload 时不清空旧内存的问题。
- `ui/main_window.py`：任务生成默认优先走 v2 `POST /api/v2/synthesize`（需要 API 服务已启动且模型已加载）；不可用时自动回退本地推理。
- `core/config_manager.py`：新增 `ui_use_v2_generation`（默认 true），用于控制桌面端是否优先使用 v2 API 合成。
- `scripts/import_legacy_voice_config_to_v2.py`：提供命令行导入工具（可在无 UI 的情况下执行迁移）。

---

## 2. 为什么之前会“不同步”？现在还会不同步吗？

### 2.1 历史原因（为什么之前不同步）
之前“语音设置”与“情绪管理(v2)”各自使用了不同的数据源：
- 历史上语音设置页写 `config/config.json`（旧 VoiceConfig schema，只含 `name/mode/prompt_text/prompt_audio/instruct_text/color`）。
- 情绪管理页读 `GET /api/v2/voices`（v2 voices schema，需要 `character/emotion/ref_asset_ids/selection_policy/...`）。

因此你在语音设置里增加的角色与本地 prompt_audio 路径，并不会自动变成 v2 的 assets + voices，自然无法在“情绪管理”里看到。

### 2.2 现状（方案 C 已落地后的统一结论）
现在角色与参考音频的事实来源都统一到 v2：
- v2 voices：`app_config.json:v2_voices_config_path` 指向的 JSON 文件
- v2 assets：SQLite `data/api_v2_assets.sqlite3` + 文件 `data/assets/audio/*`

理论上“语音设置 / 情绪管理 / v2 API / bridge”看到的应该一致。

### 2.3 若仍看到“不一致”，通常是这些原因
1. **v2 API 服务没启动 / 端口不对**
   - 情绪管理页只通过 HTTP 调用 v2 API；服务未启动时它拿不到数据。
2. **API 服务使用的 voices 文件与你 UI 写入的不是同一份**
   - 外部 `StartAPIServer.bat` 通过 `--config` 指定 voices 文件。
   - UI 内嵌服务通过 `app_config.json:v2_voices_config_path` 指定 voices 文件。
3. **voices 文件已更新，但 API 进程还在用内存里的旧版本**
   - 现在提供 `POST /api/v2/voices/reload`。
   - 语音设置页在“保存/应用/导入”后会 best-effort 调用 reload；外部启动的 API 也可以手动调用或直接重启。
4. **旧配置里的 prompt_audio 路径不存在**
   - 导入会跳过这类音频资产（v2 assets 只收录实际存在的文件）。

### 2.4 快速自检清单（建议按顺序）
1. 打开“设置”页确认：`api_host/api_port/api_key/v2_voices_config_path`。
2. 在 “TTS API 服务” 页启动服务并加载模型。
3. 打开 `GET /api/v2/health`，确认 `model_loaded=true`。
4. 打开 `GET /api/v2/voices`，确认 items 数量与语音设置页一致。
5. 若你刚保存/导入后 items 仍旧不变：调用 `POST /api/v2/voices/reload` 或重启 API 服务。

---

## 3. 统一后的调用关系（桌面 UI / 后端 API / 本地推理 / bridge）

该项目不是“传统前后端 Web”，而是“桌面端 + 可选内嵌 API Server + 可选 bridge”的组合。统一 v2 后，三条链路仍然同时存在，但默认以 v2 为主。

### 3.1 三条主要链路（同时存在，但 v2 为主）

1. **桌面端 UI（配置管理 + 可选本地推理回退）**
- 配置：语音设置页直写 v2 voices 文件（`v2_voices_config_path`）。
- 资产：语音设置页选择参考音频时会导入到 v2 assets，并写入 `ref_asset_ids` 绑定关系。
- 合成：默认优先调用 v2 `POST /api/v2/synthesize`；当 v2 API 不可用或模型未加载时自动回退到本地推理。
  - 控制开关：`app_config.json:ui_use_v2_generation`（默认 true）。

2. **Flask API（v1 兼容 + v2 新能力）**
- 后端：`core/api.py`
- v2 路由：`/api/v2/assets/*`、`/api/v2/voices/*`、`/api/v2/jobs/*`、`/api/v2/merge`、`/api/v2/synthesize`
- v2 数据：
  - assets 元数据：SQLite `data/api_v2_assets.sqlite3`
  - assets 文件：`data/assets/audio/*`
  - voices：`CharacterConfig(config_file)` 读写的 JSON 文件（由启动参数/`v2_voices_config_path` 决定）

3. **OpenAI 兼容 bridge（对外兼容输入输出）**
- `bridge.py` 对外提供 `POST /v1/audio/speech`
- bridge 内部转发到后端 v2：`POST /api/v2/synthesize`

### 3.2 “语音设置 / 情绪管理 / 任务合成”的关系
- “语音设置”页：编辑 v2 voices + 导入 v2 assets（本地直写 JSON + SQLite）。
- “情绪管理”页：纯 v2 API 客户端（需要 API 服务运行），对同一份 voices/assets 做管理与试听。
- “任务合成”：默认走 v2 synth（需要 API 服务运行且模型已加载），失败回退本地推理。

---

## 4. v2 存储结构（你需要知道的事实）
- voices：`app_config.json:v2_voices_config_path` 指向的 JSON 文件。
  - 推荐命名：`voice_id = character#emotion`，例如 `胡桃#default`、`胡桃#happy`。
- assets：SQLite `data/api_v2_assets.sqlite3` + 文件 `data/assets/audio/*`。
- cache：`data/cache/*`（默认上限 500MB，可清理，不影响 voices/assets）。

---

## 5. 推荐操作（不改代码）

### 5.1 首次迁移旧配置到 v2
两种方式任选其一：
1. UI：打开“语音设置”页点击 `⬆️ 导入旧配置到 v2`。
2. 命令行：
```powershell
python scripts/import_legacy_voice_config_to_v2.py --legacy ./config/config.json
```

### 5.2 让情绪管理与 API 看到最新 voices
- 确保 API 启动参数（`--config`）或 `app_config.json:v2_voices_config_path` 指向同一个文件。
- 若你是“外部脚本启动”的 API：保存后不刷新时，调用一次 `POST /api/v2/voices/reload`，或直接重启 API 服务。
