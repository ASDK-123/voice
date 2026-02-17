# 语音设置页参考音频回显与角色分组改造方案（Apple 风格）

日期：2026-02-12  
状态：方案评审稿（仅方案，不改代码）

## 1. 问题定义

你反馈的两个问题都成立：

1. 在“情绪管理”里已经绑定了参考音频，但“语音设置”页的“参考音频”列仍为空。  
2. 同一角色的不同情绪（`角色#emotion`）应被归在同一角色分组下，而不是纯平铺表格体验。

## 2. 现状核查结果（代码与数据证据）

### 2.1 数据层证据：voice 已绑定 ref_asset_ids，但 prompt_audio 为空

`config/super_agent.json` 中多个非 default voice（如 `胡桃#happy`、`胡桃#surprise`、`芙宁娜#happy`）满足：

- `ref_asset_ids` 有值
- `prompt_audio` 为空字符串 `""`

这与截图表现一致（“参考音频”列空）。

### 2.2 资产库证据：对应 asset 的 path 实际存在

`data/api_v2_assets.sqlite3`（`assets` 表）中，上述 `ref_asset_ids` 都能查到有效 `path`，例如：

- `ref_f34316d0a78b -> ...\\data\\assets\\audio\\ref_f34316d0a78b.wav`
- `ref_bea4d4fd9226 -> ...\\data\\assets\\audio\\ref_bea4d4fd9226.wav`

说明“数据没了”并非根因，路径在资产层是完整的。

### 2.3 语音设置页显示逻辑：只看 prompt_audio，不从 ref_asset_ids 反查

`ui/voice_settings.py`：

- `load_v2_voices()` 直接把 `v["prompt_audio"]` 填进 `VoiceConfig.prompt_audio`（约 765-799 行）
- `update_table()` 的“参考音频”列直接显示 `config.prompt_audio`（约 470-478 行）

也就是说：当前显示链路是旧语义（`prompt_audio`），没有走新语义（`ref_asset_ids -> assets.path`）。

### 2.4 情绪管理页写入逻辑：上传/绑定主要更新 ref_asset_ids，不保证回写 prompt_audio

`ui/emotion_voices.py`：

- 上传后会创建/绑定 asset 到 voice 的 `ref_asset_ids`（约 925-969 行）
- 保存 voice 时 patch 里不包含 `prompt_audio`（约 1217-1226 行）

因此会出现“绑定成功但语音设置页路径空”的结构性结果。

### 2.5 分组问题：语音设置页是平铺 QTableWidget，无角色分组视图模型

`ui/voice_settings.py` 当前是 6 列平铺表格，没有“角色分组容器/分区头/折叠”。

对比 `ui/voice_library_dialog.py`，它已经有按 `character` 聚合、`default` 优先排序的分组逻辑（约 134-157 行）。

## 3. 根因结论

根因不是单点 bug，而是 **两套语义并存但 UI 未完成迁移**：

- 旧语义：`prompt_audio`（单一路径）
- 新语义：`ref_asset_ids`（参考池）+ 资产库 `assets.path`

“语音设置”页还在主要消费旧语义；“情绪管理”页主要写新语义，导致展示断层。

## 4. 设计目标（Apple 风格）

对齐 Apple Human Interface Guidelines 的核心原则：

1. Clarity（清晰）：用户应一眼知道“当前 voice 使用哪个参考池、当前预览的是哪条音频”。
2. Deference（内容优先）：减少无意义字段编辑，主界面聚焦角色与情绪结构。
3. Depth（渐进层级）：主表简洁，详细绑定关系在右侧面板逐层展开。
4. Consistency（一致性）：情绪管理与语音设置对同一 voice 的解释必须一致。
5. Feedback（即时反馈）：绑定后立即回显可用路径/状态，而不是空字段。

## 5. 改造方案（不改后端协议优先）

## 5.1 数据语义统一（显示层）

把“语音设置页的参考音频显示值”定义为：

`display_prompt_audio =`

1. 首选：`ref_asset_ids[0]` 在 assets 表中的 `path`（如果存在）
2. 其次：`prompt_audio`
3. 否则：`<未绑定参考音频>`

说明：

- 不强制改后端存储结构即可修复主要体验。
- `prompt_audio` 保留兼容字段，但不再作为唯一来源。

## 5.2 写回策略统一

在“语音设置”保存时：

- 若 `ref_asset_ids` 非空，自动把首个 ref 对应 path 回写到 `prompt_audio`（兼容老链路）。
- 若 `ref_asset_ids` 为空，允许 `prompt_audio` 保留手工路径（兼容极端场景）。

这样旧功能继续可用，新功能不再丢显示。

## 5.3 角色分组信息架构

将“语音设置”从单平铺表改为 **分组式双栏结构**：

- 左栏：角色列表（Character）
- 右栏：该角色下 emotion 子表（default/happy/sad...）

排序规则：

- 角色：按名称排序（可加最近使用）
- 情绪：`default` 固定第一，其余按字母序

交互规则：

- 选择角色后，只显示该角色的情绪行
- 情绪行中展示“参考池数量、当前主参考、最后更新时间”

这与 Apple 的“先主导航，再细节编辑”的层级一致。

## 5.4 字段与控件语义调整

“参考音频”列建议从“可手工输入路径”改为“可读主参考预览 + 选择按钮”：

- 文本框默认只读（防止用户误认为应手输绝对路径）
- 通过“管理参考音频”面板进行绑定
- 提供“设为主参考”动作（从 ref 池中指定展示/兼容用主路径）

## 5.5 状态可视化

每个 emotion 行新增状态芯片（Tag）：

- `已绑定 n 条` / `未绑定`
- `主参考可用` / `主参考缺失`

并在底部状态栏显示：

- 当前 voice id
- 当前主参考 asset_id 与路径

## 6. 实施分期建议

### Phase A（低风险，先修体验断层）

- 仅修“显示路径空”的问题：在 `load_v2_voices()` 或 `update_table()` 中从 `ref_asset_ids` 反查 path。
- 保存时补回 `prompt_audio` 兼容值。

收益：立刻解决你当前看到的“不合理空白”。

### Phase B（结构升级）

- 引入角色分组视图（可复用 `voice_library_dialog.py` 的分组/排序思路）。
- 将情绪子行与右侧参考池面板联动。

收益：实现“同角色同组”的核心体验目标。

### Phase C（一致性打磨）

- 增加“主参考”概念及状态芯片。
- 清理历史空 `prompt_audio` 并做一次性回填。

收益：长期可维护，一致性最强。

## 7. 验收标准

1. 任意 voice 只要 `ref_asset_ids` 非空，语音设置页“参考音频”列不再空白。  
2. `胡桃#default/happy/surprise/disgust` 在同一角色分组下展示。  
3. 在情绪管理页绑定/解绑后，返回语音设置页可立即看到一致结果（无需手工补路径）。  
4. 旧工程（仅 `prompt_audio`、无 `ref_asset_ids`）仍可正常显示和合成。

## 8. 风险与回滚

风险：

- 旧逻辑可能依赖手工输入路径；改为只读需保留“高级模式”入口。
- 分组改造涉及较多 UI 事件联动，需防止选择态错乱。

回滚策略：

- 先以 Feature Flag 启用分组视图（默认关）
- Phase A 与 Phase B 分开上线，先保守修复显示问题

## 9. 结论

当前行为“不合理”的根因已确认：**语音设置页仍以 `prompt_audio` 为唯一显示源，而情绪管理页主要维护 `ref_asset_ids`。**

建议按 Phase A -> B -> C 落地，先修显示一致性，再做分组升级。这样风险最小、收益最大，也最符合 Apple 风格的“清晰、渐进、一致”。
