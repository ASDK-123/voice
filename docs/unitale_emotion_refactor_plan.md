# Unitale 情绪控制重构执行说明（Schema v3）

## 1. 改造目标
- 移除旧的 `8维情绪向量 + 强度` 机制。
- 统一情绪控制为：`角色 + 情绪标签 + v2参考音频(voices/assets)`。
- 工程存档升级到 `schema_version: 3`，不兼容旧工程（`schema < 3`）。

## 2. 核心变更

### 2.1 数据结构变更
- `schema_version`: `2 -> 3`
- 导出 `version`: `2.0 -> 3.0`
- 删除 `libraries.emotions`
- 删除 `scriptLines[].intensity`
- 保留 `scriptLines[].emotion`，语义改为“v2情绪标签”

### 2.2 前端能力变更
新增：
- `normalizeEmotionTag(tag)`
- `emotionCatalogByCharacter`（从 `v2Voices + v2Assets` 动态聚合）
- `globalEmotionCatalog`
- `getEmotionOptionsForRole(role)`
- `normalizeLineEmotion(line, opts)`
- `normalizeScriptLineV3(line, opts)`

移除：
- `SYSTEM_EMOTIONS`
- `emotionPresets / emotionForm / isEditingEmotion`
- `isSystemEmotion / saveEmotion / editEmotion / deleteEmotion / resetEmotionForm / resetEmotionsToDefault`
- `mapEmotionToVoiceEmotion`
- `intensityMap`

### 2.3 UI 变更
- 删除“情绪描述预设”整块页面。
- 删除脚本台词中的“强度”下拉框。
- 情绪下拉改为 `getEmotionOptionsForRole(line.role)` 动态候选。

## 3. 合成与匹配策略

### 3.1 情绪规范化
- 所有情绪先经过 `normalizeEmotionTag`：空值回退 `default`。
- 不做中英语义映射（不再有硬编码翻译）。

### 3.2 Voice 选择顺序
1. 角色显式绑定 `voiceId` 且存在 -> 直接命中。
2. 自动匹配 `${role}#${emotion}`。
3. 自动匹配 `${role}#default`。
4. 匹配 `voice.character === role` 的第一项。
5. 未命中 voice -> direct reference（`prompt_audio_asset_id`）。

### 3.3 v2 请求规则
- 命中 voice：发送 `voice_id + character + emotion`。
- 未命中 voice：发送 `mode=zero_shot + prompt_audio_asset_id + prompt_text`。
- 上传参考音频时 `emotion` 使用同一规范化结果。

## 4. Prompt 与解析规则
- 默认 Prompt 已移除强度相关描述和示例字段。
- `${emotionList}` 由 `globalEmotionCatalog` 生成。
- 解析 LLM 结果时忽略 `item.intensity`。
- 每条 dialogue 行都会做 `normalizeLineEmotion(..., notify=true)`：
  - 不在可用目录时自动回退（优先 `default`）
  - 一次性告警，避免静默错配

## 5. 导入导出与兼容策略
- 导出仅写入 schema v3 格式。
- 导入仅接受 `schema_version >= 3` 且需包含 `project + libraries`。
- `schema < 3` 直接拒绝导入，并提示“请升级到 schema v3”。
- 启动时若 IndexedDB 中存在旧 schema 缓存，提示不兼容并清除旧 `currentState`。

## 6. 验收清单

### 6.1 静态检查
- 关键旧标识应全部清零：
  - `emotionPresets`
  - `SYSTEM_EMOTIONS`
  - `line.intensity`
  - `libraries.emotions`
  - `mapEmotionToVoiceEmotion`

### 6.2 功能检查
1. v2 中创建 `角色A#happy`、`角色A#sad` 并绑定不同参考音频。
2. 脚本行切换 emotion 后可命中不同 voice/asset。
3. 无 voice 命中但有 `voiceFile` 可 direct reference 合成。
4. 无 voice 且无 reference 给出明确报错。
5. LLM 返回未知 emotion 会自动回退并告警。
6. 导出 JSON 不含 `libraries.emotions` / `line.intensity`。
7. 导入旧 schema 工程会被拒绝。
8. 导入 schema v3 工程可正常恢复并继续生成音频。

## 7. 风险与回滚
- 风险：历史脚本中的旧情绪标签可能无法在 v2 目录命中。
  - 处理：统一回退到可用情绪（优先 `default`）并提示。
- 风险：旧工程不可直接导入。
  - 处理：导入时明确提示升级需求。
- 回滚：保留当前版本文件备份，必要时整体回退 `peiying/Unitale/index.html`。

## 8. 生效说明
- 本次改造自 `schema v3` 起生效。
- `schema v2` 及以下工程不支持直接导入。
