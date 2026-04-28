# Voice 参考文本语义治理修复计划（方案 B 执行版）

文档日期：2026-03-02  
适用范围：`config/super_agent.json` + `data/api_v2_assets.sqlite3` + v2 UI/API 全链路  
目标问题：左侧 voice“参考文本”与右侧参考音频文本不一致，且推理文本来源不可预测

---

## 1. 目标与验收标准

### 1.1 修复目标
1. 明确字段语义：
- `note` 只做备注/检索，不参与推理。
- `transcript_text` 作为参考音频的推理文本唯一字段（资产侧）。
2. 统一链路口径：
- UI 左右展示同口径。
- 编译与推理使用同一文本选择规则。
3. 历史兼容：
- 保持旧数据可读，提供一次性迁移与回滚。

### 1.2 验收标准（必须同时满足）
1. 语音设置页同一 voice 左右显示文本一致（至少在“主参考”维度一致）。
2. `POST /api/v2/synthesize` 与 `POST /api/v2/voices/{id}/compile` 对同一 `voice_id + selected_ref_asset_id` 使用同一参考文本。
3. 不再出现 `note` 影响推理文本。
4. 对现有 `super_agent.json` 与资产库执行迁移后，核心角色可正常合成。

---

## 2. 当前问题落点（文件级）

1. 后端把 `note` 当推理 fallback：
- `core/api_legacy.py` `_v2_prepare_char_config()`：`meta.prompt_text or meta.note`
- `core/api_v2_routes.py` `compile_voice()`：`meta.prompt_text or meta.note`

2. 前端把“保存备注”同时写入 `prompt_text`：
- `ui/components/emotion_assets_panel.py` `save_selected_asset_note()` 当前写 `{"note": note, "prompt_text": note}`

3. UI 展示口径不一致：
- 左侧第 2 列来自 voice `prompt_text`（`ui/voice_settings.py`）
- 右侧表格显示 asset `note`（`ui/components/emotion_assets_panel.py`）
- 右侧选中后左侧临时替换优先 `note`（`ui/voice_settings.py::_on_selected_asset_changed`）

---

## 3. 目标数据契约（修复后）

## 3.1 Asset（v2 assets）
1. `note`：备注、搜索辅助、可为空。
2. `transcript_text`：参考音频对应文本，用于编译/推理；建议必填（迁移后）。
3. 兼容字段：
- 读取时允许存在历史 `prompt_text`。
- 写入时新逻辑优先写 `transcript_text`。

## 3.2 Voice（v2 voices）
1. `prompt_text`：voice 级兜底文本（当资产侧 transcript 缺失时使用）。
2. `ref_asset_ids`：资产绑定列表，主参考仍取第一个或按策略选中项。

---

## 4. 文本选择规则（统一算法）

给定 `voice` 与已选 `asset_id`，推理文本按以下顺序解析：

1. `asset.transcript_text`（新字段，首选）  
2. `asset.prompt_text`（仅兼容历史，记录 warning）  
3. `voice.prompt_text`（兜底）  
4. 空则报错 `prompt_text is required`

明确禁止：
- 不允许 `asset.note` 进入推理文本选择。

---

## 5. 实施阶段与任务清单

## Phase 0：冻结基线与观测（0.5 天）

任务：
1. 增加诊断脚本（只读）：统计 mismatch 数量（voice.prompt_text vs 主参考 transcript_text）。
2. 导出基线报告：记录受影响 voice 列表、asset_id 列表。
3. 备份：
- `config/super_agent.json`
- `data/api_v2_assets.sqlite3`

交付：
1. `docs/` 下诊断报告 md/json。
2. 可回滚备份文件。

---

## Phase 1：后端语义修复（1 天）

### 任务 1：API 字段扩展与兼容
目标文件：
- `core/api_v2_routes.py`

改动点：
1. `PUT /api/v2/assets/audio/<id>` 支持 `transcript_text`。
2. `GET` 返回中透出 `transcript_text`（来自 meta_json；无则空）。
3. 保留 `prompt_text` 读兼容，但标注为 legacy（文档级说明即可）。

### 任务 2：推理/编译文本来源统一
目标文件：
- `core/api_legacy.py` `_v2_prepare_char_config()`
- `core/api_v2_routes.py` `compile_voice()`

改动点：
1. 从 `meta` 读取顺序改为：`transcript_text -> prompt_text(legacy) -> voice.prompt_text`
2. 删除 `note` fallback。
3. 当命中 legacy `prompt_text` 时打 warning log（便于迁移后清理）。

### 任务 3：OpenAPI/注释同步
目标文件：
- `core/api_legacy.py` 内相关注释
- `docs/API_USAGE.md`（如已有接口字段说明）

交付：
1. 后端可处理新字段。
2. 推理/编译与 `note` 解耦。

---

## Phase 2：前端口径统一（1 天）

### 任务 1：右侧面板分离“备注”和“参考文本”
目标文件：
- `ui/components/emotion_assets_panel.py`
- `ui/v2_client.py`

改动点：
1. 现有“保存备注”仅写 `note`。
2. 新增“参考文本”输入与保存按钮，仅写 `transcript_text`（兼容期可同时写 `prompt_text`，但仅后端决定）。
3. 资产表格第 3 列建议显示“参考文本摘要”（而不是备注），备注可放 tooltip/副列。

### 任务 2：左侧列表显示规则统一
目标文件：
- `ui/voice_settings.py`

改动点：
1. 左侧“参考文本”显示主参考的 `transcript_text`；若无则回退 voice.prompt_text。
2. `_on_selected_asset_changed()` 不再优先 `note`。
3. 冲突状态可用颜色/标签提示“voice 文本与主参考文本不一致”。

### 任务 3：兼容页面同步（避免隐性回归）
目标文件：
- `ui/emotion_voices.py`（该页存在同类 `note/prompt_text` 绑定写法）

改动点：
1. 同步拆分 `note` 和 `transcript_text` 语义。
2. 禁止“保存备注”回写 `prompt_text`。

交付：
1. UI 不再制造新的语义污染。
2. 用户看到的文本与后端推理文本一致。

---

## Phase 3：历史数据迁移（0.5~1 天）

### 任务 1：新增迁移脚本（支持 dry-run）
建议脚本：
- `scripts/migrate_asset_prompt_text_to_transcript_text.py`

迁移规则（按优先级）：
1. 若 `asset.transcript_text` 已有值：不覆盖。
2. 否则若 `asset.prompt_text`（legacy）有值：复制到 `transcript_text`。
3. 否则用绑定 voice 的 `voice.prompt_text` 回填。
4. `note` 保持原值，不改动。

### 任务 2：输出迁移报告
报告字段：
1. 总资产数、已补齐数、冲突数、空文本数
2. 每条变更前后摘要（asset_id, old/new transcript_text 来源）

### 任务 3：回滚工具
1. 迁移前自动导出 SQLite 快照（文件复制）
2. 提供 `--rollback <snapshot>` 参数恢复

交付：
1. 可重复执行的迁移工具。
2. 可审计的迁移结果与回滚能力。

---

## Phase 4：联调、回归与发布（1 天）

### 任务 1：测试补齐
新增测试建议：
1. `tests/test_assets_transcript_semantics.py`
- 更新资产时 `note` 与 `transcript_text` 独立。
- `note` 不参与推理选择。
2. `tests/test_synthesis_normalization.py` 增加 case
- 选中 asset 时文本选择顺序正确。
3. UI 手工回归用例（文档化）
- 语音设置页左右一致性
- 备注修改不影响推理文本

### 任务 2：灰度发布
1. 先在单机/测试集执行迁移 + smoke。
2. 观察日志 24h：legacy `prompt_text` fallback 命中次数逐步趋近 0。
3. 稳定后再清理 legacy 兼容。

交付：
1. 回归报告（通过/失败列表）。
2. 发布说明与已知限制。

---

## 6. 任务分工建议

1. 后端负责人：
- `core/api_legacy.py`
- `core/api_v2_routes.py`
- 迁移脚本

2. 前端负责人：
- `ui/components/emotion_assets_panel.py`
- `ui/voice_settings.py`
- `ui/emotion_voices.py`
- `ui/v2_client.py`

3. 测试负责人：
- 单元/集成测试补齐
- 迁移前后数据一致性校验

---

## 7. 风险清单与缓解

1. 风险：历史数据 `prompt_text` 缺失，迁移后 transcript 仍为空。  
缓解：迁移报告列出空文本资产；发布前人工补录关键角色。

2. 风险：多个 voice 绑定同一 asset，回填来源冲突。  
缓解：迁移脚本对多绑定冲突标记为 `conflict`，不自动覆盖，需人工确认。

3. 风险：旧 UI 页面（如 `emotion_voices.py`）继续写脏数据。  
缓解：同批修复，至少先禁用“note -> prompt_text”联动写入。

4. 风险：缓存 key 行为变化导致短期命中下降。  
缓解：发布说明中声明“首轮缓存重建预期”，观察 1~2 天恢复。

---

## 8. 时间评估（保守）

1. Phase 0：0.5 天  
2. Phase 1：1.0 天  
3. Phase 2：1.0 天  
4. Phase 3：0.5~1.0 天  
5. Phase 4：1.0 天  

总计：约 4~4.5 天（含迁移与回归，不含额外 UI 美化）。

---

## 9. 发布后成功指标（KPI）

1. 线上 mismatch 数量：下降到 0（或仅剩人工标记例外）。
2. `note` 触发推理文本的日志计数：0。
3. 用户反馈“左右不一致”问题：0。
4. 关键角色（含芙宁娜）回归合成通过率：100%。

---

## 10. 执行顺序（建议）

1. 先做后端语义修复（Phase 1），防止继续产生脏数据。  
2. 再做前端口径统一（Phase 2），消除展示偏差。  
3. 然后做历史迁移（Phase 3），一次性修复存量。  
4. 最后回归与灰度（Phase 4），确保可持续稳定运行。  

