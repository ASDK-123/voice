# Unitale 音色管理重构实施方案（v2 资源直连）

文档日期：2026-02-12  
适用范围：`peiying/Unitale/index.html` 对接当前项目 v2 API（`/api/v2/voices`、`/api/v2/assets/audio`、`/api/v2/synthesize`）

## 1. 目标

把 Unitale 的“音色管理”从“本地文件+refPath”模型，重构为“后端资源驱动”模型：

1. 页面直接读取你项目的 voice 资源（角色+情绪）。
2. 页面可直接管理参考音频资产，并绑定到 voice。
3. 生成链路以 `voice_id` 为主，不再依赖本地 `refPath` 作为长期事实源。
4. 保留兼容路径，避免一次性切换导致存量工程不可用。

## 2. 当前现状与核心问题

### 2.1 前端状态模型与后端事实源不一致

当前 Unitale：

1. 音色库是前端本地列表 `timbres[] = {id,name,description,refPath}`。参考：`peiying/Unitale/index.html:951`。
2. 角色绑定字段是 `char.voiceFile`，值来自 `timbre.refPath`。参考：`peiying/Unitale/index.html:1652`、`peiying/Unitale/index.html:464`。
3. 音色管理主要动作是上传本地文件，不是 voice CRUD。参考：`peiying/Unitale/index.html:1761`。

当前后端：

1. voice 事实源是 v2 voices（含 `name/character/emotion/ref_asset_ids`）。参考：`core/api_v2_routes.py:429`。
2. 资产事实源是 v2 assets（含 `asset_id/path/character/emotion/note`）。参考：`core/api_v2_routes.py:83`。
3. 合成统一入口支持 `voice_id` 和 direct 两种模式。参考：`core/server/routes_v2_misc.py:71`。

### 2.2 导致的问题

1. 双事实源：前端改音色，不等于后端 voice 改了。
2. 多情绪能力被弱化：前端绑定是 `refPath`，无法准确表达 `角色#情绪`。
3. 数据漂移：导入/导出后本地 `refPath` 与服务器 asset/voice 可能失配。

## 3. 重构原则

1. 后端单一事实源：voice 与 asset 只认 v2 API。
2. 前端兼容优先：先“读后端、写后端”，再逐步下线本地旧字段。
3. 生成稳定优先：`voice_id` 主路径必须先跑通，direct 仅做兜底。
4. 渐进迁移：保留旧工程加载能力，提供一次性迁移按钮。

## 4. 目标架构（重构后）

### 4.1 页面职责

1. 音色管理页：管理 v2 voices（角色+情绪）与其参考资产绑定。
2. 参考音频区：管理 v2 assets（上传、筛选、试听、绑定、解绑）。
3. 脚本页角色绑定：绑定 `voice_id`（或 `character+emotion`），不再绑定 `refPath`。

### 4.2 生成职责

1. 主路径：`POST /api/v2/synthesize`，payload 使用 `voice_id`。
2. 兜底路径：voice 缺失时使用 direct（`prompt_audio_asset_id + prompt_text`）。
3. `emo_vector` 不再作为后端主输入，仅保留在脚本元信息里。

## 5. 数据模型改造

### 5.1 前端新模型

新增：

1. `voiceLibrary[]`
2. `assetLibrary[]`
3. `characterBindings[]`（每个角色绑定 `voice_id`，可选附带 `character/emotion`）

建议字段：

`voiceLibrary` 每项：

1. `voice_id`（对应后端 `name`）
2. `character`
3. `emotion`
4. `mode`
5. `prompt_text`
6. `ref_asset_ids[]`
7. `selection_policy`

`assetLibrary` 每项：

1. `asset_id`
2. `character`
3. `emotion`
4. `note`
5. `path`（仅展示，合成不用）

### 5.2 旧字段兼容策略

1. 保留读取 `timbres` 与 `char.voiceFile` 的能力。
2. 新保存写入 `characters[].voiceId`（新字段）。
3. 读取时优先 `voiceId`，缺失再尝试旧字段映射。

## 6. 接口契约与调用规范

### 6.1 Voices

1. 列表：`GET /api/v2/voices`
2. 新建：`POST /api/v2/voices`
3. 更新：`PUT /api/v2/voices/{voice_id}`
4. 删除：`DELETE /api/v2/voices/{voice_id}`
5. 预编译：`POST /api/v2/voices/{voice_id}/compile`

请求约束：

1. `voice_id` 统一采用 `character#emotion`。
2. `emotion` 缺省写为 `default`。
3. `ref_asset_ids` 始终传数组，避免类型漂移。

### 6.2 Assets

1. 上传：`POST /api/v2/assets/audio`
2. 列表：`GET /api/v2/assets/audio?character=&emotion=`
3. 试听：`GET /api/v2/assets/audio/{asset_id}/content`
4. 删除：`DELETE /api/v2/assets/audio/{asset_id}`

上传建议携带：

1. `character`
2. `emotion`
3. `note`（记录来源，如 `unitale:migrated:<filename>`）

### 6.3 Synthesize

1. 主路径 payload：`{ text, voice_id, response_format: "audio" }`
2. 兜底 payload：`{ text, mode, prompt_audio_asset_id, prompt_text, response_format: "audio" }`
3. 优先命中 `voice_id`，只在 voice 不存在时触发 direct。

## 7. 页面改造清单（分区）

### 7.1 音色管理页（UI）

把“添加音色”改成“创建/编辑 voice”：

1. 字段：角色、情绪、模式、参考文本、选择策略。
2. 参考资产绑定区：显示已绑定 `ref_asset_ids`，支持添加/移除。
3. 列表按 `character` 分组，组内按 `emotion` 展示。

### 7.2 参考音频管理区（UI）

新增资产表格：

1. 筛选：角色、情绪、关键词。
2. 操作：上传、试听、删除、绑定到当前 voice。
3. 显示 `linked/ref_count`，避免误删仍被引用的资产。

### 7.3 脚本页左侧角色绑定

1. 现有“音色选择（timbres）”下拉改为 “voice 选择（voice_id）”。
2. 支持按角色过滤 voice（只展示 `character` 匹配项）。
3. 保留一次“从旧音色自动映射”提示。

## 8. 迁移方案（重点）

### 8.1 一次性迁移入口

新增“迁移旧音色到 v2”动作，步骤：

1. 读取 `timbres[]`。
2. 每条 timbre 尝试找到本地音频（`localFileMap`/工程包素材）。
3. 上传为 v2 asset，得到 `asset_id`。
4. 生成 voice：
   1. `character = timbre.name`（或用户确认）
   2. `emotion = default`
   3. `voice_id = character#default`
   4. `ref_asset_ids = [asset_id]`
5. 把角色绑定旧字段 `voiceFile` 映射到新字段 `voiceId`。

### 8.2 映射冲突处理

1. 若 voice 已存在：提示“覆盖/跳过/追加 asset”。
2. 若 asset 上传失败：记录失败项，允许重试。
3. 若旧 `refPath` 无文件：迁移报告中标注“缺文件”。

### 8.3 迁移完成标志

1. 工程写入 `schema_version = 2`。
2. 存档 `migration_report`（成功/失败条目）。

## 9. 分阶段实施计划

## Phase 0：基线冻结与备份

1. 备份已完成（`peiying/Unitale_backup_20260212_172643`）。
2. 冻结当前 `index.html` 可运行状态。
3. 记录最小回归脚本（单行生成 + 一键生成）。

交付物：

1. 备份目录可回滚。
2. 基线 smoke 记录。

## Phase 1：只读接入 v2 voices/assets

1. 新增数据拉取：voices 列表、assets 列表。
2. 音色页先展示后端 voices（不改保存逻辑）。
3. 增加 assets 试听能力。

验收：

1. 页面能实时显示后端 voice 变化。
2. 断网/接口异常有明确提示，不影响已有页面。

## Phase 2：写路径切换到 voice CRUD

1. 音色表单保存改为 `POST/PUT /api/v2/voices`。
2. 删除改为 `DELETE /api/v2/voices/{id}`。
3. 绑定参考音频改为写 `ref_asset_ids`。

验收：

1. 页面新增 voice 后，后端 `GET /api/v2/voices` 立即可见。
2. 刷新页面不丢失（证明后端持久化生效）。

## Phase 3：脚本绑定改为 `voice_id`

1. `characters[]` 增加 `voiceId`。
2. 生成时优先用 `voiceId` 发送 synth 请求。
3. 旧 `voiceFile` 仅作为 fallback/direct 输入。

验收：

1. 未绑定 `voiceFile` 的角色，只要绑定 `voiceId` 即可生成。
2. 多情绪 voice（同角色不同 emotion）可按绑定正确发声。

## Phase 4：迁移工具 + 旧字段下线

1. 加入“迁移旧音色”按钮。
2. 迁移后默认隐藏旧 `refPath` 编辑入口。
3. 导入旧工程时触发迁移提示。

验收：

1. 旧工程可迁移并继续生成。
2. 新工程默认不再依赖 `timbres/refPath`。

## 10. 风险与缓解

1. 风险：接口字段松散导致前端写入脏数据。  
缓解：写入前做本地 schema 校验（`voice_id/character/emotion/ref_asset_ids`）。

2. 风险：迁移时部分本地文件缺失。  
缓解：迁移报告 + 可重试队列，不阻塞其他条目。

3. 风险：用户并行改动 voices 文件造成覆盖。  
缓解：优先走 API CRUD，避免前端直接写 JSON 文件。

4. 风险：删除资产误删仍被引用。  
缓解：删除前查询 `linked/ref_count`，默认阻止硬删。

## 11. 测试与验收清单

### 11.1 API 联调

1. `GET /api/v2/voices` 返回结构可被前端解析。
2. `POST/PUT/DELETE /api/v2/voices` 全链路可用。
3. `POST /api/v2/assets/audio` 上传后可 `content` 试听。
4. `POST /api/v2/synthesize` 的 `voice_id` 模式稳定输出音频。

### 11.2 业务回归

1. 新建角色-情绪 voice -> 绑定 asset -> 合成成功。
2. 旧工程导入 -> 一键迁移 -> 一键生成成功。
3. 一键生成 20 条以上台词，失败率符合当前基线。

### 11.3 负向场景

1. voice 不存在时提示清晰，不崩溃。
2. asset 不存在时提示可修复路径（重新上传/重新绑定）。
3. 后端 401/404/500 错误可读且可定位。

## 12. 回滚方案

1. 代码回滚：恢复 `peiying/Unitale_backup_20260212_172643/index.html`。
2. 运行回滚：切回当前“local timbre + direct fallback”逻辑。
3. 数据回滚：迁移写入前导出当前工程 JSON 作为快照。

## 13. 里程碑与工期预估

1. Phase 1（只读接入）：0.5 天。
2. Phase 2（写路径切换）：1 天。
3. Phase 3（脚本绑定改造）：0.5 天。
4. Phase 4（迁移与收尾）：0.5 天。

总计：约 2.5 天（不含视觉优化与大规模 UI 重排）。

## 14. 本方案对应的执行顺序（建议）

1. 先做 Phase 1，确认页面已“看见后端事实源”。
2. 再做 Phase 2，确保创建/编辑/删除 voice 真实落库。
3. 然后做 Phase 3，让业务主链路改为 `voice_id`。
4. 最后做 Phase 4，完成旧数据迁移与入口收敛。

---

如果按这个方案落地，最终效果是：Unitale 页面上的“音色管理”就是你项目的真实音色资源管理，不再是本地影子模型。
