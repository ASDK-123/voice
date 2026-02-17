# Voice Library（v2 Voices 选择器）设计文档
最后更新：2026-02-10  
状态：Design / 待实现  

本设计用于把“文本页/任务页的 voice 选择”从“巨大下拉框”升级为更可用、更像苹果应用的交互：可搜索、可分组、键盘友好，并且所有用户可见文案均为中文。

---

## 1. 目标与非目标

### 1.1 目标（必须满足）
- **可用性**：当 voices 数量达到 100-500 时，仍能在 2 秒内完成“找到并应用 voice”。
- **分组**：按 `character -> emotion`（或 `character#emotion`）展示，`default` 情绪永远置顶。
- **可搜索**：支持模糊搜索 `角色/情绪/voice_id`，输入即过滤。
- **快捷不打断**：页面内仍保留少量“最近使用/收藏”的快捷入口，不强制每次弹窗。
- **中文交互**：界面按钮、提示、空状态、菜单项均为中文（内部变量/ID 可用英文）。
- **v2 单一事实源**：选择结果以 `voice_id`（即 `VoiceConfig.name`）为准；不引入新的配置文件体系。

### 1.2 非目标（本轮不做）
- 不做“播放试听/一键 compile”等声音管理能力（这些属于情绪管理页）。
- 不做复杂 NLP 指令解析（只做简单 token 规则匹配）。
- 不强制引入数据库或额外索引（本地内存构建索引即可）。

---

## 2. 数据模型与解析规则

### 2.1 输入数据（来自现有 UI）
- 输入：`Dict[str, VoiceConfig]`（key 为 `voice_id`，value 为 `VoiceConfig`）
- 约定：`VoiceConfig.name == voice_id`

### 2.2 voice_id 解析
- 标准格式：`{character}#{emotion}`
  - 例：`胡桃#default`、`胡桃#happy`
- 解析规则：
  - 若包含 `#`：`character, emotion = voice_id.split('#', 1)`
  - 若不包含 `#`：`character = voice_id`，`emotion = default`
  - 若 `emotion` 为空字符串：视为 `default`

### 2.3 展示名（用于 UI）
- 角色侧边栏显示：`character`
- 右侧列表显示：
  - 主标题：`emotion`（显示为 `default` 或用户自定义情绪）
  - 副标题：`voice_id`（用于精确确认）
  - 可选第三列：`mode`（来自 `VoiceConfig.mode`）

---

## 3. 交互结构（两层：快捷 + 正式选择）

### 3.1 快捷层（不打断编辑）
用于 `ui/task_plan.py`（表格音色列）和 `ui/text_edit.py`（右键菜单）。

- 快捷入口只展示：
  - 最近使用（MRU）：默认展示 12 个（内部最多保留 20 个）
  - 收藏角色（Favorites）：默认展示 8 个角色（内部最多保留 30 个角色）
  - “打开 Voice Library…”：进入正式弹窗
- 目的：避免把 100+ voices 全塞进 `ComboBox` 导致卡顿和难找。

### 3.2 正式层（Voice Library 弹窗）
统一弹窗，供两个页面复用：
- 任务页：点击“打开 Voice Library…”后回填该行的 `voice_id`
- 文本页：点击“打开 Voice Library…”后将 `voice_id` 应用到选中文本的格式属性

---

## 4. Voice Library 线框图（Apple 风格）

### 4.1 窗口规格
- 默认：`860 x 520`
- 最小：`720 x 460`
- 推荐：可缩放；左右分栏用 `QSplitter`，记忆分栏比例

### 4.2 布局草图（ASCII）

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  [最近|收藏|全部]   🔎 搜索角色/情绪/voice_id…        已选：胡桃 / happy  │  44-52px
├───────────────────────────────┬──────────────────────────────────────────┤
│  侧边栏（角色）                │  内容区（情绪/voices）                    │
│  ┌─────────────────────────┐  │  ┌────────────────────────────────────┐  │
│  │ ♥ 胡桃                   │  │  │ default   胡桃#default   零样本复制 │  │
│  │   雷电将军               │  │  │ happy     胡桃#happy     指令控制   │  │
│  │   芙宁娜                 │  │  │ sad       胡桃#sad       零样本复制 │  │
│  │ …                        │  │  │ …                                  │  │
│  └─────────────────────────┘  │  └────────────────────────────────────┘  │
│                               │  详情卡片（可选 P1）：prompt_text 等       │
├───────────────────────────────┴──────────────────────────────────────────┤
│  提示：Enter 选择，Esc 取消                                   [取消][选择] │  52px
└──────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Apple 风格的“观感约束”
- 行高：侧边栏 34-38px；右侧列表 36px
- 分隔：细分割线、弱阴影、卡片层次极轻
- 重点状态：选中行背景比主题背景略深，避免高饱和色块

---

## 5. 控件清单（类型、尺寸、中文文案）

说明：以下控件建议使用 `qfluentwidgets`，保证与现有 UI 风格一致。

### 5.1 顶部工具栏（高度 44-52）
- `seg_scope`：`SegmentedWidget`
  - items（中文）：`最近`、`收藏`、`全部`
  - 默认：`全部`
- `search_edit`：`SearchLineEdit`
  - placeholder（中文）：`搜索角色/情绪/voice_id`
  - clear button：启用
- `label_selected`：`BodyLabel`
  - 文案（中文）：`已选：{character} / {emotion}`（未选择时显示 `未选择`）
- `btn_clear_selection`：`ToolButton`
  - tooltip（中文）：`清除选择`

### 5.2 左侧边栏（建议宽 240-280）
- `list_characters`：`ListWidget`
  - item 文案：`character`
  - item 左侧装饰：小圆点颜色（取该角色 default voice 的 `color`，否则取该角色第一个 voice 的 `color`）
  - item 右键菜单（中文）：
    - `加入收藏` / `取消收藏`

### 5.3 右侧内容区
- `table_emotions`：`TableWidget`（或 `ListView` + 自定义 delegate）
  - 列建议（中文）：
    - `情绪`
    - `voice_id`
    - `模式`
  - 行排序：`default` 永远第一，其余按情绪名稳定排序
- `card_detail`（P1 可选）：`SimpleCardWidget`
  - `label_prompt_text`：`BodyLabel`（中文）：`参考文本：...`
  - `label_instruct_text`：`BodyLabel`（中文）：`指令文本：...`
  - `label_mode`：`BodyLabel`（中文）：`模式：...`

### 5.4 底部操作条（高度 52）
- `label_hint`：`CaptionLabel`（中文）：`提示：Enter 选择，Esc 取消`
- `btn_cancel`：`PushButton`（中文）：`取消`
- `btn_ok`：`PrimaryPushButton`（中文）：`选择`

---

## 6. 信号/槽（Signals/Slots）与键盘行为

### 6.1 信号/槽（建议接口）
- `seg_scope.currentChanged(str scope)`
  - 更新左侧角色列表的数据源：
    - `最近`：从 MRU 反推角色集合（保持 MRU 顺序）
    - `收藏`：从收藏角色列表渲染（保持收藏顺序）
    - `全部`：全量角色（稳定排序）
- `search_edit.textChanged(str q)`
  - 即时过滤左侧/右侧；无 q 时恢复 scope 对应全量
- `list_characters.currentRowChanged(int idx)`
  - 右侧刷新该角色的情绪/voice 列表
  - 若 scope=收藏：默认选中“该角色上次使用的 emotion”（见 8.2），否则选中 `default`
- `table_emotions.itemSelectionChanged()`
  - 更新 `label_selected`
  - 更新 P1 详情卡片内容
- `btn_ok.clicked()`
  - `accept()` 并返回选中的 `voice_id`
- `btn_cancel.clicked()` / `Esc`
  - `reject()`

### 6.2 键盘行为（Apple 风格：强键盘）
- `Ctrl+F` / `Cmd+F`：聚焦搜索框并全选
- `↑/↓`：在当前列表上下移动（焦点在列表时）
- `Enter`：确认选择（右侧有选中项时）
- `Esc`：取消

---

## 7. 数据流（从打开到选中）

### 7.1 打开弹窗
输入：
- `voices: Dict[voice_id, VoiceConfig]`
- `recent_voice_ids: List[str]`（来自 `ConfigManager`）
- `favorite_characters: List[str]`（来自 `ConfigManager`）
- `last_emotion_by_character: Dict[str, str]`（来自 `ConfigManager`）

流程：
1. 构建内存索引 `character -> emotion -> voice_id`
2. 初始化 scope=全部、搜索为空
3. 选中：
   - 若有 `preselect_voice_id`：定位 character/emotion 并高亮
   - 否则选中最近使用的 voice 对应角色；没有则选第一个角色

### 7.2 确认选择
输出：
- `selected_voice_id: str`

副作用（更新配置）：
- 更新 MRU：把 `selected_voice_id` 推到队首，去重后裁剪到 20
- 更新 `last_emotion_by_character[character] = emotion`

---

## 8. 持久化（ConfigManager keys）

### 8.1 推荐配置项（写入 `app_config.json`）
- `ui_recent_voice_ids: string[]`
  - 默认：`[]`
  - 上限：20（内部），UI 展示 12
- `ui_favorite_characters: string[]`（收藏“角色”，不是收藏 voice）
  - 默认：`[]`
  - 上限：30（内部），UI 展示 8
- `ui_last_emotion_by_character: { [character: string]: emotion: string }`
  - 默认：`{}`
  - 用途：收藏页/全部页切换角色时，优先回到该角色最近使用的 emotion
- `ui_voice_library_splitter_ratio: number`（可选）
  - 例：0.32（左栏占比）

### 8.2 收藏角色的交互语义（关键）
- 收藏的是 `character`：
  - 好处：同一角色新增情绪后自动出现在收藏视图，不需要重新收藏每个情绪 voice
- 收藏视图里：
  - 左侧只显示收藏角色
  - 右侧显示该角色全部情绪 voices
  - 默认高亮 emotion：
    - 若 `ui_last_emotion_by_character[character]` 存在且仍有该 voice：选它
    - 否则选 `default`

---

## 9. 与现有页面的集成点

### 9.1 任务计划页（`ui/task_plan.py`）
- 现状：音色列是 `ComboBox`，若 voices 多会难找
- 升级：
  - `ComboBox` 只放 MRU + Favorites（角色级展开为最近 voice 或 default）+ “打开 Voice Library…”
  - 选择器返回 `voice_id` 后，回填到该行，并更新 `TaskSegment.voice_config`

### 9.2 文本编辑页（`ui/text_edit.py`）
- 现状：右键菜单列出全部 voice（多时很长）
- 升级：
  - 右键菜单顶部显示“最近使用前 9 个”（保留 Ctrl+1..9）
  - 增加“打开 Voice Library…”用于搜索/分组
  - 选择后，把 `voice_id` 写入 `QTextCharFormat.UserProperty`

---

## 10. 实施计划（最短闭环）

### P0（能用，1-2 天）
- 新增 `ui/voice_library_dialog.py`（弹窗 + 索引构建 + 搜索 + 返回 voice_id）
- 在 `ui/task_plan.py` 接入 “打开 Voice Library…”
- 在 `ui/text_edit.py` 接入 “打开 Voice Library…”
- 在 `ConfigManager` 增加 `ui_recent_voice_ids/ui_favorite_characters/ui_last_emotion_by_character` 的读写（只要 get/set 即可）

### P1（好用，1-2 天）
- 弹窗加入右键“加入收藏/取消收藏”
- “最近/收藏/全部”三段视图完善（空状态、默认选中、键盘操作）
- 右侧增加 `模式` 列与可选详情卡片

### P2（像苹果，0.5-1 天）
- 统一间距/行高/分隔线与暗色主题可读性
- 记忆 splitter 比例与上次 scope

---

## 11. 验收清单
- voices=200 时：
  - 打开选择器 < 300ms（构建索引 + 渲染）
  - 搜索响应 < 60ms（输入即过滤，不闪烁）
  - 键盘全程可完成选择（Ctrl/Cmd+F、上下、Enter）
- 收藏角色：
  - 新增情绪 voice 后自动出现
  - 默认回到该角色最近使用 emotion；否则 default
- 所有用户可见文案均为中文（按钮/提示/空状态/菜单）

