# Voice 参考文本不一致 Bug 修复方案与项目评估（2026-03-02）

## 1. 问题概述

现象：在语音设置页中，左侧 voice 列表的“参考文本”和右侧参考音频面板显示的文本不一致（例如 `芙宁娜#default`）。

已确认：
- `config/super_agent.json` 中 `芙宁娜#default.prompt_text = "毫无压力呢。"`
- `data/api_v2_assets.sqlite3` 中 `ref_8081002353d2` 的 `note/prompt_text = "我看看…那我就选择「艺术」和「表演」好了..."`.

因此左右展示的是两套来源，导致视觉不一致与认知混乱。

---

## 2. 当前实现链路（基于项目现状）

### 2.1 左侧表格文本来源
- 左侧“参考文本”直接使用 voice 配置中的 `prompt_text`。
- 关键位置：
  - `ui/voice_settings.py` `update_table()` 渲染第 2 列
  - `ui/voice_settings.py` `_render_prompt_text_cell()`

### 2.2 右侧面板文本来源
- 右侧参考音频表格显示资产 `note` 字段。
- 关键位置：
  - `ui/components/emotion_assets_panel.py` `_render_assets_table()`（第 3 列是 `note`）
- 选择某个 asset 后，顶部标签和左侧临时显示优先用 `note`，其次 `asset.prompt_text`：
  - `ui/voice_settings.py` `_on_selected_asset_changed()`

### 2.3 推理/编译实际使用文本来源
- 当 voice 绑定了 `ref_asset_ids`，后端会优先取资产的 `prompt_text` 或 `note` 覆盖 voice 的 `prompt_text`。
- 关键位置：
  - `core/api_legacy.py` `_v2_prepare_char_config()`：`meta.prompt_text or meta.note` 覆盖 `cfg.prompt_text`
  - `core/api_v2_routes.py` `compile_voice()`：`_pick_prompt_text_for_asset()` 同样优先资产侧文本

结论：当前不是单纯 UI bug，而是**数据语义冲突 + 展示冲突 + 推理优先级冲突**。

---

## 3. 根因分析

1. 双源并存，无明确主源：
- voice 侧有 `prompt_text`
- asset 侧也有 `prompt_text`（存于 `meta_json`）和 `note`

2. 字段语义混用：
- `note` 本应是“备注/检索信息”，但被用于推理参考文本 fallback（`meta.note`）。

3. UI 两侧展示口径不一致：
- 左侧展示 voice 文本
- 右侧展示 asset 备注

4. 写入路径扩大冲突：
- 右侧保存备注时，前端一次写入 `{"note": note, "prompt_text": note}`，进一步把备注与参考文本绑定为同一值。

---

## 4. 影响评估（结合项目）

### 4.1 用户层面
- 用户看到 A 文本，实际推理可能用 B 文本，配置不可预期。
- 角色调试和复现难度增加。

### 4.2 工程层面
- 缓存 key 包含 `prompt_text`，若选择参考音频触发资产文本覆盖，会导致命中行为与 UI认知不一致。
- voice v2 文件（`super_agent.json`）与 SQLite 资产库产生长期漂移。

### 4.3 风险范围
- 影响所有绑定了 `ref_asset_ids` 的角色。
- 当前扫描发现至少 2 条 mismatch（`芙宁娜#default`、`芙宁娜#sad`）。

---

## 5. 修复目标

1. 明确“推理参考文本”的唯一语义字段。  
2. UI 左右展示同口径，不再让用户误判。  
3. 保持向后兼容，避免一次性破坏历史数据。  
4. 迁移可回滚，可审计。

---

## 6. 方案对比

### 方案 A（最小改动，短期止血）

策略：
- 仅调整 UI 展示口径：
  - 左侧第 2 列显示“主参考 asset 的推理文本”（而不是 voice.prompt_text）
  - 或在左侧新增“来源标签”（voice/asset）并高亮冲突
- 暂不改后端优先级逻辑

优点：
- 改动小、上线快
- 立即降低“看见与实际不一致”

缺点：
- 根因未清理，数据仍双源漂移
- 后续维护成本高

适用：
- 紧急 hotfix

---

### 方案 B（推荐：语义治理 + 渐进迁移）

策略：
1. 语义拆分字段：
- `note`：仅备注/搜索，不参与推理
- `transcript_text`（或沿用 `prompt_text` 但语义固定）：仅推理参考文本

2. 后端统一规则：
- 推理只读 `asset.transcript_text`（无值时可 fallback voice.prompt_text，且记录告警）
- 移除 `meta.note` 作为推理 fallback

3. 前端统一规则：
- 右侧“备注”只写 `note`
- 新增“参考文本”编辑框只写 `transcript_text`
- 左侧“参考文本”显示主参考 `transcript_text`（无主参考则显示 voice.prompt_text）

4. 数据迁移：
- 一次性脚本对历史资产补齐 `transcript_text`
- 建议优先级：
  - 若 asset 里已有 `prompt_text`（历史值）=> 作为 `transcript_text`
  - 否则用关联 voice.prompt_text 回填
  - `note` 保持原值，不再挪作推理文本

优点：
- 彻底消除语义混用
- 兼容历史数据且可控
- 对“v2 单一配置 + 资产库”架构最稳

缺点：
- 涉及前后端+迁移+测试，工作量中等

适用：
- 本项目当前阶段最合理

---

### 方案 C（长期重构：彻底单源化）

策略：
- 只保留 asset 侧参考文本，voice 侧不再存 `prompt_text`（或仅展示缓存）

优点：
- 模型清晰，后期最简

缺点：
- 改动面大，兼容成本高，短期风险大

适用：
- 后续大版本重构

---

## 7. 推荐执行方案（B，分阶段）

### Phase 0：观测与防误导（1 天）
- 在语音设置页增加 mismatch 检测：
  - voice.prompt_text vs 主参考 transcript_text 不一致时显示 warning
- 不改变推理行为，仅暴露冲突

### Phase 1：接口与前端语义修复（1-2 天）
- API：
  - `PUT /assets/audio/<id>` 支持 `transcript_text`
  - 推理逻辑不再使用 `note` 作为 fallback
- UI：
  - 右侧拆分“备注”和“参考文本”输入
  - 左侧“参考文本”按主参考展示（缺失时回退 voice.prompt_text）

### Phase 2：历史数据迁移（0.5-1 天）
- 新增迁移脚本（可 dry-run）：
  - 输出“将变更条目数、冲突条目数、空文本条目数”
  - 支持回滚（迁移前导出 JSON 快照）

### Phase 3：验收与灰度（1 天）
- 对已有常用角色（含 `super_agent.json`）全量比对
- 验证推理文本与 UI 一致性

---

## 8. 测试建议

1. 单元测试
- asset 元数据更新：`note` 与 `transcript_text` 独立更新
- 推理入参归一化：只使用 transcript，不再吃 note

2. 集成测试
- voice 绑定多个 ref 时，选择不同 ref 后 UI 与推理文本一致
- compile/all 模式与实时 synth 模式口径一致

3. 回归测试
- 未绑定 ref 的 voice 行为不变
- 旧配置文件仍可读取，不崩溃
- 缓存命中率在预期范围（首次因 key 口径变化可接受波动）

---

## 9. 风险与回滚

### 风险
- 历史数据中部分 `note` 实际被当作“参考文本”使用，拆分后可能暴露空 transcript。
- 迁移规则若不审慎，可能覆盖少量人工修正文本。

### 缓解
- 强制先 dry-run 报告，再执行正式迁移
- 迁移前导出 `assets` 快照与 `voices_v2` 快照

### 回滚
- 回滚脚本按快照恢复 SQLite/JSON
- API 端可临时恢复旧 fallback（note -> prompt_text）开关

---

## 10. 本次结论

- 该问题不是配置文件损坏，而是系统层面的双源语义冲突。
- 推荐按“方案 B”执行：先可视化冲突，再做语义拆分与数据迁移。
- 这样能在不推翻现有 v2 架构的前提下，解决“UI 展示不一致 + 推理结果不可预期”的核心问题。

