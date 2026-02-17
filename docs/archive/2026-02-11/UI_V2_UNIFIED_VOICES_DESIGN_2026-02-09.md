# 优化方案：语音设置页全面迁移到 v2（单一数据源，和情绪管理统一）

最后更新：2026-02-09  
状态：已落地（核心链路已实现）  
背景：你认为“语音设置页”和“情绪管理页”各用一套配置文件不合理，希望在“方案 C：语音设置页也改走 v2”的基础上做更合理的整体设计。

---

## 0. 实现状态（截至 2026-02-10）
- v2 voices 作为单一数据源：`ui/voice_settings.py` 默认读写 `app_config.json:v2_voices_config_path`
- 旧 `config/config.json`（`app_config.json:voice_config_path`）仅作为“导入源/备份格式”，不再作为运行时依赖
- “情绪管理（v2）”页面：`ui/emotion_voices.py` 全量走 v2 `/api/v2/assets/audio` + `/api/v2/voices`（绑定 `ref_asset_ids`、试听、删除、compile）
- 语音设置页在上传/选择 prompt_audio 时，会把音频导入 v2 assets（SQLite + `data/assets/audio/*`）并写入 `ref_asset_ids`
- 运行中的 API 如需热刷新 voices 文件，支持 `POST /api/v2/voices/reload`

## 1. 现状问题（为什么你会感觉“不合理”是对的）

当前项目在桌面端同时存在两套“声音配置数据源”：

1. 旧 UI 声音配置（legacy 导入/备份格式）
- 文件：`config/config.json`（或 `app_config.json` 里记录的 `voice_config_path`）
- 结构：仅支持 `VoiceConfig = {name, mode, prompt_text, prompt_audio, instruct_text, color}`
- 现状：不再作为运行时配置来源，仅用于“一次性导入到 v2”或备份导出

2. v2 voices（情绪管理页 / v2 API）
- 数据源：`CharacterConfig(config_file)` 读取的 JSON 文件（当前由 `v2_voices_config_path` 指定）
- 结构：需要支持 `character/emotion/ref_asset_ids/selection_policy/prompt_audio_asset_id...`
- 使用方：`/api/v2/voices`、`ui/emotion_voices.py`（v2 API 链路）

如果两套数据源同时被当成“运行时事实源”，会带来典型现象：
- 语音设置页新增/编辑的角色不会出现在情绪管理页（因为后者只看 v2 `/api/v2/voices`）
- prompt_audio 如果只是本机路径而未导入 v2 assets，会导致 v2 无法管理/复用参考音频

这也是为什么现在要强制把运行时事实源统一到 v2：避免配置漂移。

另外，之前之所以“不得不分离文件”，是一个现实的技术约束：
- 旧 UI 加载 voice 配置时是 `VoiceConfig.from_dict(**data)`，遇到 v2 新字段会直接崩溃。

所以你说“分开不合理”，从产品体验上完全成立；它只是过渡期的技术避险，不应该长期存在。

---

## 2. 优化后的核心理念（C 方案的增强版）

一句话：把 v2 作为 **唯一事实源（Single Source of Truth）**，桌面 UI 的所有“声音管理/情绪管理/合成选择”都围绕 v2 的数据结构与 API 运转；旧 `config/config.json` 只保留“导入迁移”和“可选备份导出”。

这会带来三个关键结果：
- “语音设置”和“情绪管理”天然同步，因为读写的是同一套 v2 voices + v2 assets。
- ref 音频从“本地路径”变成“v2 assets”，可被 jobs/cache/merge/bridge 复用，符合你 v2 的整体架构目标。
- UI 不再需要维护两套 schema，也不需要把“声音管理逻辑”复制两遍。

---

## 3. v2 数据存储结构（必须遵守的事实）

当前 v2 的存储结构（以代码现状为准）：

### 3.1 v2 assets（参考音频/输出音频）
- 元数据：SQLite `data/api_v2_assets.sqlite3`（表 `assets`）
- 文件内容：磁盘 `data/assets/audio/*`
- API：
  - `GET/POST /api/v2/assets/audio`
  - `GET /api/v2/assets/audio/{asset_id}/content`
  - `DELETE /api/v2/assets/audio/{asset_id}`

### 3.2 v2 voices（角色/情绪配置）
- 存储：JSON 文件（`CharacterConfig(config_file)` 负责读写）
- API：
  - `GET/POST/PUT/DELETE /api/v2/voices`
  - `POST /api/v2/voices/{voice_id}/compile`

### 3.3 关键约束
- assets “必须可迁移、可复用”，所以 ref 音频的最终归宿应该是 v2 assets，而不是散落的本地路径。
- voices 的 schema 允许扩展字段（例如 `ref_asset_ids`），因此旧 UI 的 `VoiceConfig(**data)` 模型必须升级，否则永远无法共用同一文件。

---

## 4. 统一后的对象模型（建议的稳定规范）

### 4.1 Voice ID 规范（必须统一）
- 推荐：`voice_id = "{character}#{emotion}"`
  - 例：`胡桃#default`、`胡桃#happy`
- 这样：
  - 情绪管理页可直接按 `(character, emotion)` 定位 voice
  - 后端 fallback/选择策略的逻辑也更直观

### 4.2 v2 voice 的推荐字段（与现状兼容）
最小必备：
- `name`（= voice_id）
- `character`（建议始终写入，即使 `name` 能推断）
- `emotion`（建议始终写入，默认 `default`）
- `mode`（参考音色/零样本复制/精细控制/指令控制）
- `prompt_text`（v2 compile 与推理的关键输入）
- `instruct_text`（可选）
- `ref_asset_ids: string[]`（同一情绪下多参考音频）
- `selection_policy`（默认 `random_per_text`，保证“同文本稳定随机”，不破坏缓存）
可选增强：
- `color`
- `prompt_audio_asset_id`（如果你希望“主参考音频”这个概念更明确）

### 4.3 v2 asset 的推荐元数据（与现状兼容）
上传 ref 音频时写入：
- `kind=ref`
- `character`
- `emotion`
- `language`
- `note`

---

## 5. UI 侧的最终形态（你要的“更合理”应该长这样）

### 5.1 “语音设置页”改造目标：变成 v2 Voice Manager
语音设置页不再编辑本地 `config/config.json`，而是：
- voices 列表来自 `GET /api/v2/voices`（按角色分组，默认展示 `#default`）
- 编辑 voice：`PUT /api/v2/voices/{voice_id}`
- 创建 voice：`POST /api/v2/voices`（支持创建 `角色#default` 和新增情绪 `角色#happy`）
- 编译：`POST /api/v2/voices/{voice_id}/compile`（支持 compile all refs）
- ref 管理入口：显示当前 `ref_asset_ids` 数量，并提供“跳转/打开 情绪管理页”按钮

这样语音设置页与情绪管理页的分工更清晰：
- 语音设置页：管理 voice 配置（prompt_text/mode/策略/编译）
- 情绪管理页：管理 ref assets（上传/试听/删除/绑定）

### 5.2 情绪管理页保持 v2（已实现的方向正确）
情绪管理页继续以 v2 API 为准：
- assets 列表：`GET /api/v2/assets/audio?character=...&emotion=...`
- 绑定：更新 voice 的 `ref_asset_ids`

### 5.3 文本/任务页（配套改造，才能彻底结束“双配置”）
为了真正消除旧配置文件的存在意义，需要让：
- 文本页、任务页的“可选声音列表”也来自 v2 voices
- 合成默认走 v2 `/api/v2/synthesize` 或 `/api/v2/jobs`

一旦这一步做完，旧 `config/config.json` 就可以彻底退役为“导入备份格式”，不再是运行时依赖。

---

## 6. 迁移策略（从现在的双配置过渡到单一数据源）

这是关键：你不想丢现有语音设置页里已经配置好的几十个角色。

### 阶段 0：确定唯一 v2 voices 文件
- 统一约定 `v2_voices_config_path = config/voices_v2.json`（示例命名）
- 内嵌 server 与所有 UI 页面都只读写这一个 voices 文件

### 阶段 1：一次性导入旧 `config/config.json` -> v2 voices + v2 assets
导入规则建议：
- 对旧 voice `name=胡桃`：
  - 创建 v2 voice：`胡桃#default`
  - 写入字段：`prompt_text/mode/instruct_text/color`
- 对旧 `prompt_audio`：
  - 如果文件存在：上传到 v2 assets，meta 写入 `character=胡桃 emotion=default kind=ref`
  - 把返回的 `asset_id` 追加到 `胡桃#default.ref_asset_ids`

导入完成后：
- v2 voices 里就拥有你旧 UI 的全部角色
- 情绪管理页也能立刻看到这些角色，并且 ref 音频都在 assets 中

### 阶段 2：语音设置页切换到 v2（停止写旧 config）
- 语音设置页只读写 `/api/v2/voices`
- 旧 `voice_config_path` 只保留“导入”入口，不再是运行时保存位置

### 阶段 3：文本/任务页切换到 v2（彻底结束双体系）
实现后：
- 全 UI 都是 v2 数据源
- 旧 `config/config.json` 不再被任何运行路径依赖

---

## 7. 风险与对策

1. 编译 compile 依赖“server 有模型并已加载”
- 对策：语音设置页显示 `/api/v2/health` 的 model 状态；必要时引导用户先启动 API 服务并加载模型。

2. 资产“linked”字段现在语义不强
- 对策：以 voice 的 `ref_asset_ids` 作为真实绑定关系；未来可在后端补齐“反向索引/linked 自动维护”。

3. 导入时 prompt_audio 路径不可用（文件丢失/相对路径）
- 对策：导入 UI 提供“缺失文件列表”，允许用户补选文件后再上传。

---

## 8. 验收标准（方案落地后你应该看到的效果）

1. 语音设置页与情绪管理页显示的角色列表一致（同一套 v2 voices）。
2. 在语音设置页新增角色后，情绪管理页无需任何操作即可立刻出现该角色。
3. 在情绪管理页上传 ref 音频并绑定后，语音设置页能看到该 voice 的 ref 数量变化（同一个数据源）。
4. 所有 ref 音频都可在 v2 assets 中查询到（SQLite 索引 + 文件落盘）。
5. 文本/任务页最终不再依赖 `config/config.json` 作为运行时配置（可保留为导入备份格式）。

---

## 9. 推荐的下一步（先落地最小闭环）

如果你认可这个“单一数据源”方案，最短闭环建议顺序：
1. 增加“旧 config 导入到 v2”的迁移工具（UI 按钮或脚本都行）
2. 改造语音设置页：列表/编辑/编译全部走 v2 voices
3. 再改文本/任务页：选择 voice 与合成走 v2（这样旧 config 可以真正退役）
