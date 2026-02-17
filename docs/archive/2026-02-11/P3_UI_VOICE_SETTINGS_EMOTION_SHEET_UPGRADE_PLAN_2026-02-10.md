# 方案 A（推荐）工业级落地方案：语音设置(v2) + 情绪管理(v2)融合为“右侧 Sheet 弹窗”
最后更新：2026-02-10

本文是对 `UI_VOICE_SETTINGS_EMOTION_MODAL_DESIGN_2026-02-10.md` 中“布局 A（右侧 Sheet）”的工程化落地方案。目标是让你能逐步实现，不推倒重来，并且在每个阶段都有可验收的闭环。

> 原则：本方案强调“清晰(Clarity) / 克制(Deference) / 分层(Depth)”的设计理念，并且严格以 v2 数据结构为唯一事实源：  
> - Voice（配方）：`voice_id = 角色#情绪`，存于 `v2_voices_config_path`（经 API CRUD 读写）  
> - Asset（材料）：ref 音频资产，存于 SQLite（经 `/api/v2/assets/audio` 管理）  
> - 绑定关系：`voice.ref_asset_ids[]` 引用多个 ref assets

---

## 0. 你会得到什么（落地后的用户体验）
在“语音设置/角色与音色”页里：
- 选中 `胡桃#calm` 后，右侧看到固定布局的 voice 配方编辑。
- 点击 `管理参考音频…`，右侧滑出 Sheet：标题 `参考音频（胡桃 / calm）`，里面能上传/试听/加入参考池/设为主样本/编译。
- 主界面始终不跳转、不丢上下文；Sheet 关闭即回到配方编辑。
- 用户不会再误以为“上传=可选”，因为 Sheet 的主动作就是“加入参考池”，并且主界面会显示 `参考池：N 条`。

---

## 1. 当前代码与职责现状（落地前必须统一的认知）
### 1.1 相关模块
- Voice 配置批量页：`ui/voice_settings.py`
- 情绪管理页（含 assets 表格、绑定、compile）：`ui/emotion_voices.py`
- v2 API 客户端封装：`ui/v2_client.py`
- v2 后端接口（assets/voices/compile）：`core/api_v2_routes.py`
- v2 参考池选择策略：`core/emotion_selector.py`

### 1.2 最大痛点
- `ui/voice_settings.py` 仍保留“表格编辑 prompt_audio/prompt_text”的工具页形态；而 v2 的真实运行关系是 `ref_asset_ids` 参考池。
- `ui/emotion_voices.py` 是“页面级 UI”，包含了“配方编辑 + 资产库”的双栏结构；要作为 Sheet 复用，需要拆出可嵌入组件。

落地的关键是：**把情绪页右侧“资产库 + 绑定操作”抽成一个可复用的 Panel，然后在语音设置页用 Sheet 容器承载它。**

---

## 2. 目标与非目标（工业级收敛范围）
### 2.1 目标（必须实现）
- 主界面：`语音设置(v2)` 升级为“角色与音色（v2）”主线页面，提供 `管理参考音频…` 打开 Sheet。
- Sheet：复用情绪管理逻辑，且强绑定上下文（当前 `角色/情绪/voice_id`）。
- 数据一致性：Sheet 内的上传/绑定/编译能立即反映到主界面摘要（参考池数量、主样本提示）。
- 线程安全：所有网络/IO（上传、拉取 assets、compile）必须在后台线程执行，不阻塞 UI。
- 兼容保留：保留独立的“情绪管理(v2)”侧边栏入口（高级入口），但主入口在语音设置页。

### 2.2 非目标（先不做，避免范围爆炸）
- 不引入新的前端框架；继续 PyQt5 + qfluentwidgets。
- 不引入新的后端服务；沿用现有 v2 API。
- 不做复杂的“多参考融合成一个参考音色”研究型改动；采用参考池 + 策略选择。

---

## 3. 总体架构（组件与数据流）
### 3.1 新增/重构组件（建议命名）
建议拆出以下 UI 组件，避免在 `ui/voice_settings.py` 和 `ui/emotion_voices.py` 里继续“巨石化”：

1. `ui/components/emotion_assets_panel.py`
- 职责：只负责“参考音频库（assets）”与“绑定到当前 voice（ref_asset_ids）”相关交互。
- 可嵌入：既可作为独立页的一部分，也可作为 Sheet 内容。

2. `ui/components/voice_refs_sheet.py`
- 职责：右侧 Sheet 容器（打开/关闭/动画/固定宽度/键盘 Esc 关闭）。
- 内容：承载 `EmotionAssetsPanel`，并显示上下文标题与摘要。

3. `ui/voice_manager_v2.py`（或逐步重构 `ui/voice_settings.py`）
- 职责：主界面（角色列表 + 情绪分段 + voice 配方编辑 + 摘要 + 打开 Sheet）。
- 仍可保留 `ui/voice_settings.py` 的表格视图作为“批量模式”子视图（Phase 2 再做）。

### 3.2 数据流（必须可解释）
主界面选择 `voice_id=角色#情绪`：
- 主界面读取 voice（优先 API `GET /api/v2/voices/<id>`，失败再读本地 `v2_voices_config_path`）。
- 主界面显示 `参考池：N 条`（从 voice 的 `ref_asset_ids` 计算）。
- 用户点击 `管理参考音频…`：
  - Sheet 打开，Panel `set_context(character, emotion, voice_id, v2_client)`
  - Panel 拉取 assets：`GET /api/v2/assets/audio?character=...&emotion=...&kind=ref`
  - Panel 拉取 voice：`GET /api/v2/voices/<voice_id>`，用于显示当前参考池与绑定状态
- 用户在 Panel 中“加入参考池/设为主样本”：
  - `PUT /api/v2/voices/<voice_id>` 更新 `ref_asset_ids`
  - Panel 发出信号 `ref_pool_changed(voice_id, ref_asset_ids)`，主界面更新摘要

---

## 4. 关键 API 依赖（落地前必须确认已存在）
你当前后端已经具备以下接口（用于本方案）：
- voices：
  - `GET /api/v2/voices`
  - `GET /api/v2/voices/<voice_id>`
  - `POST /api/v2/voices`
  - `PUT /api/v2/voices/<voice_id>`（含 `ref_asset_ids` 更新）
  - `POST /api/v2/voices/<voice_id>/compile`（支持 `?all=1`）
- assets：
  - `GET /api/v2/assets/audio`
  - `POST /api/v2/assets/audio`（上传 ref）
  - `GET /api/v2/assets/audio/<asset_id>/content`（试听）
  - `DELETE /api/v2/assets/audio/<asset_id>`
  - `PUT /api/v2/assets/audio/<asset_id>`（改备注/提示词等）

结论：前端只需“调用 + 组合”，不需要新后端能力即可落地方案 A。

---

## 5. UI 设计细节（把设计理念落到控件与行为）
### 5.1 清晰（Clarity）：用户永远知道自己在编辑什么
主界面必须始终显示：
- 当前 voice：`胡桃 / calm`（或 `胡桃#calm`）
- v2 配置路径：`v2_voices_config_path = ...`（只读展示）
- 参考池摘要：`参考池：3 条`，以及主样本 `主样本：ref_xxx…`（如果有）

Sheet 标题必须携带上下文：
- `参考音频（胡桃 / calm）`
- 副标题：`参考池：3 条  |  选择策略：按文本随机（稳定）`

### 5.2 克制（Deference）：主动作永远可见，次动作收起来
Sheet 内主动作（始终可见）：
- `上传` `试听` `加入参考池` `设为主样本`
次动作放在 `更多…`：
- `从参考池移除`
- `复制 asset_id`
- `打开文件位置`
- `删除资产`
- `编译当前 voice`
- `编译全部参考`

### 5.3 分层（Depth）：新手与高级用户都不被打扰
主界面默认只暴露“能闭环”的字段：
- 模式、策略、参考文本、指令文本、保存/应用、管理参考音频
高级字段（例如 variation_seed、prompt_text per asset）放在折叠区或“更多…”里。

---

## 6. 工程实现细节（你要怎么写代码）
### 6.1 `EmotionAssetsPanel`（可嵌入的资产库 Panel）
建议对 `ui/emotion_voices.py` 做“剥离式重构”：

做法：
- 从 `EmotionVoicesInterface` 中把“右侧 assets 区域”抽到新类 `EmotionAssetsPanel(QWidget)`。
- 让 `EmotionVoicesInterface` 变成：
  - 左侧：voice 配方（可保留或逐步弱化）
  - 右侧：直接嵌入 `EmotionAssetsPanel`

Panel 对外接口（建议）：
```python
class EmotionAssetsPanel(QWidget):
    ref_pool_changed = pyqtSignal(str, list)  # voice_id, ref_asset_ids
    request_toast = pyqtSignal(str, str, str) # level, title, message

    def set_client(self, client: V2Client) -> None: ...
    def set_context(self, *, character: str, emotion: str, voice_id: str) -> None: ...
    def refresh(self) -> None: ...
```

Panel 内部状态：
- `self.character`, `self.emotion`, `self.voice_id`
- `self.assets: list[dict]`
- `self.voice: dict | None`（用于 ref_asset_ids）
- `self.selected_asset_id`

线程模型（必须）：
- `list_assets/get_voice/upload/delete/compile/update_voice` 全部用后台线程或 `QThreadPool`。
- UI 线程只做：禁用按钮、显示 loading、渲染表格、弹 InfoBar。

关键行为（必须实现）：
- 上传成功后：
  - 立即刷新 assets 表格
  - 自动确保 `voice_id` 存在（如果缺失，提示“创建该情绪 voice”或自动创建）
  - 自动把新 asset 加入 `ref_asset_ids`（最佳体验）
- “设为主样本”：
  - 把 asset_id 移动到 `ref_asset_ids[0]`
  - 刷新绑定列与摘要

### 6.2 `VoiceRefsSheet`（右侧 Sheet 容器）
实现方式建议（最稳）：
- 主界面使用 `QSplitter`（或固定布局 + 右侧容器 `QFrame`）承载主内容与 Sheet。
- Sheet 默认宽度：主窗口宽度的 35%-45%，最小 420px，最大 640px。
- 关闭方式：右上角 `×` + `Esc`。
- 动画：`QPropertyAnimation` 作用于 `maximumWidth`，模拟侧滑。

Sheet 对外接口（建议）：
```python
class VoiceRefsSheet(QWidget):
    def open(self, *, character: str, emotion: str, voice_id: str) -> None: ...
    def close(self) -> None: ...
    def is_open(self) -> bool: ...
```

### 6.3 主界面（语音设置升级为 Voice Manager v2）
落地策略建议分阶段，不要一口气推翻 `ui/voice_settings.py`。

Phase 1（最短闭环，低风险）：
- 保留现有表格 `ui/voice_settings.py`。
- 增加一个“工具栏按钮” `管理参考音频…`：
  - 只有当前选中行（voice）时可点
  - 点击打开 `VoiceRefsSheet`，传入 `voice_id`（解析角色/情绪）
- 表格下方新增摘要行：`参考池：N 条`（从 v2 rows 的 `ref_asset_ids` 推出），并显示 `selection_policy` 当前值（中文映射）。
- 在选择行变化时，如果 Sheet 打开，自动刷新 Sheet 上下文（让它跟随当前行）。

Phase 2（体验升级，苹果风格）：
- 将表格视图改为“列表 + 详情编辑”：
  - 左：角色列表（收藏/最近/搜索）
  - 中：情绪分段
  - 右：Voice 配方编辑卡片（固定布局）
  - `管理参考音频…` 在“参考池摘要”旁
- 表格视图保留为“批量模式”切换（高级用户仍可用）

---

## 7. 数据一致性策略（工业级必须写清楚）
### 7.1 单一事实源
Voice 的最终事实源是 `v2_voices_config_path` 指向的 JSON 文件，但 UI 的读写优先走 API：
- API 可用：用 `/api/v2/voices` CRUD 读写（服务器负责保存到同一份 JSON）
- API 不可用：主界面允许离线编辑（写本地 JSON），但 Sheet（资产库）必须提示“需要 API 服务运行”

### 7.2 多进程一致性（避免“看起来不一致”）
主界面顶部显示：
- `当前 API：http://{host}:{port}`，以及连通状态（小圆点/文字）
- `当前 v2 voices：{v2_voices_config_path}`

并提供一个“刷新 voices”动作：
- 优先 `GET /api/v2/voices`
- 回落读本地 `v2_voices_config_path`

---

## 8. 关键边界与错误处理（必须避免 UI 卡顿/大退）
必须覆盖这些失败场景并做到“不崩溃、不中断”：
- API 不可用（WinError 10061）：Sheet 显示空态，提供“去启动 API 服务”的按钮或提示。
- voice 已存在（HTTP 409）：提示“已存在，无需创建”，不视为错误；继续后续绑定。
- 上传失败/文件过大/格式不支持：提示明确错误码与 request_id（如果有）。
- compile 失败：显示失败原因（prompt_text 为空、音频不存在、音频过长 >30s 等）。

UI 层面统一错误呈现：
- 用同一套 `InfoBar` 样式输出：`标题 + 简短原因 + request_id`（可复制）。

---

## 9. 具体实施步骤（可执行里程碑）
### Milestone M1（1-2 天）：抽 Panel，保持现有情绪页功能不回归
- 新增 `ui/components/emotion_assets_panel.py`
- `ui/emotion_voices.py` 改为复用 Panel（先做到功能一致）
- 验收：独立“情绪管理(v2)”页面行为不变（上传/试听/绑定/删除/compile）

### Milestone M2（0.5-1 天）：引入 Sheet 容器与最短闭环
- 新增 `ui/components/voice_refs_sheet.py`
- `ui/voice_settings.py` 加按钮 `管理参考音频…` 并能打开 Sheet
- Sheet 能对当前选中 voice 做：上传 -> 自动绑定 -> 参考池数量回显
- 验收：用户无需离开语音设置页即可完成“添加参考 -> 绑定 -> 编译”

### Milestone M3（1-2 天）：打磨上下文一致性与固定布局
- 主界面增加“参考池摘要”与“策略显示”
- Sheet 与主界面双向同步：切换 voice 自动刷新 Sheet 上下文
- 固定多行输入高度，避免长文本改变布局
- 验收：连续操作 10 分钟无卡顿、无布局跳动、无“看起来没生效”

### Milestone M4（2-4 天）：把语音设置升级为苹果风格主界面（列表 + 详情）
- 引入左侧角色列表 + 中间情绪分段 + 右侧配方卡片
- 旧表格保留为“批量模式”开关（可选）
- 验收：从角色定位到绑定参考池 < 10 秒完成

---

## 10. 验收清单（工业级 QA）
功能闭环：
- 新建 `角色#情绪` voice -> 上传 ref -> 自动加入参考池 -> 保存/应用 -> compile -> 合成测试句

一致性：
- Sheet 里加入/移除 ref 后，主界面 `参考池：N 条` 立即更新
- 声音库弹窗刷新后能看到新增的 `角色#情绪` voice（若创建了）

性能：
- assets 列表 200 条以内：刷新 < 500ms（本地 API）
- 上传时 UI 不冻结，按钮有 loading 状态

鲁棒性：
- API 未启动时：Sheet 不崩溃，有明确空态与提示
- 409 conflict：不弹“错误”，弹“已存在”
- compile all refs：进度可见、失败可追踪

---

## 11. 风险与对策（提前写清）
风险：UI 重构期间容易出现“状态不同步/按钮可用性错误/线程访问 Qt 控件崩溃”  
对策：
- 所有后台线程在启动前捕获 UI 值（禁止在线程里读 Qt 控件）
- 引入统一的“状态机”变量：`current_voice_id/current_character/current_emotion`
- 每个 API 调用都加超时与异常兜底，避免卡死 UI

风险：外部 API 与 UI 写本地文件双写导致覆盖  
对策：
- 优先用 API CRUD 修改 voices
- 离线编辑必须在 UI 显示“离线模式：仅写本地，未同步到运行中 API”

