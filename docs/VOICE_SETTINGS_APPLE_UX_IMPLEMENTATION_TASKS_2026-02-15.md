# CosyVoice Desktop 语音设置页重构可开发任务清单（按文件/函数粒度）

日期：2026-02-15  
状态：开发拆解稿（可直接排期）  
来源方案：`docs/VOICE_SETTINGS_APPLE_UX_REDESIGN_SPEC_2026-02-15.md`

## 1. 估算口径

1. 工时单位为“人时（h）”，默认 1 名熟悉当前代码的开发。  
2. 工时含开发+本地自测，不含大范围联调排队时间。  
3. 验收点以手工可验证为主；如项目后续补自动化测试，可将验收项转成用例。

## 2. 里程碑与总工时

| 里程碑 | 范围 | 预计工时 |
|---|---|---:|
| M1 安全止血 | 编辑模式、删除保护、无效入口治理、基础试听提示 | 32h |
| M2 架构重构 | 三栏布局、Inspector 行为、voice_id 语义拆分 | 54h |
| M3 稳定与打磨 | 试听链路增强、视觉统一、可访问性与回归 | 34h |
| 可选 M4 后端协同 | Content-Type 与错误信息增强 | 7h |
| **合计（不含 M4）** |  | **120h** |

## 3. 详细任务清单

| ID | 优先级 | 文件 | 目标类/函数 | 开发任务 | 预计工时 | 依赖 | 验收点 |
|---|---|---|---|---|---:|---|---|
| VS-001 | P0 | `ui/voice_settings.py` | `VoiceSettingsInterface.init_ui` | 增加“浏览/编辑模式”切换按钮与状态变量，默认浏览模式 | 3h | 无 | 页面默认不可直接改文本；切到编辑模式后才可编辑 |
| VS-002 | P0 | `ui/voice_settings.py` | `update_table`、`update_config_*` | 在浏览模式下将 `LineEdit` 置只读、`ComboBox` 置禁用；阻断 `textChanged` 直接写入 | 5h | VS-001 | 浏览模式点击/输入不会修改配置；编辑模式行为保持可用 |
| VS-003 | P0 | `ui/voice_settings.py` | `on_child_context_menu` | 右键菜单降级：默认仅保留复制/打开/定位；删除移至“更多操作” | 3h | VS-001 | 任意输入框右键不再直接看到“删除配置” |
| VS-004 | P0 | `ui/voice_settings.py` | `delete_config` | 删除改为确认弹窗（显示 voice_id） | 2h | VS-003 | 删除前出现二次确认；取消后数据不变 |
| VS-005 | P0 | `ui/voice_settings.py` | 新增 `soft_delete_config`、`undo_delete` | 实现 8 秒撤销机制（InfoBar 按钮 + 延迟提交删除） | 6h | VS-004 | 删除后 8 秒内可恢复，超时后真正删除 |
| VS-006 | P1 | `ui/voice_settings.py` | `keyPressEvent`、新增 `undo/redo` | 增加 `Ctrl+Z`/`Ctrl+Shift+Z` 编辑撤销栈（至少覆盖文本修改） | 8h | VS-002 | 连续编辑后可撤销/重做；切换行不丢状态 |
| VS-007 | P0 | `ui/voice_settings.py` | `init_ui` | 主按钮区移除“导入旧配置到 v2”，迁移入口转入工具菜单触发 | 3h | 无 | 主按钮区仅保留添加/加载/保存/应用/预编译 |
| VS-008 | P1 | `ui/voice_settings.py` | 新增 `show_migration_entry_if_needed` | 仅检测到 legacy 文件时显示迁移提示卡，支持“今日不再提示” | 4h | VS-007 | 无 legacy 文件时不出现迁移入口；有 legacy 时可见提示卡 |
| VS-009 | P0 | `ui/voice_settings.py` | `_parse_voice_id`、`_normalize_voice_name` | 新增 `compose_voice_id(character, emotion)` 与 `validate_voice_parts` | 4h | 无 | 空 emotion 自动归一到 default；非法字符提示明确 |
| VS-010 | P0 | `ui/voice_settings.py` | `update_table` | 将“名称”编辑拆分为 `character` + `emotion` 输入，新增只读 `voice_id` 显示列 | 10h | VS-009 | 修改角色/情绪后，voice_id 实时预览为 `角色#情绪` |
| VS-011 | P0 | `ui/voice_settings.py` | `update_config_name`、保存链路 | 禁止直接手写覆盖 `voice_id`，统一通过 character/emotion 生成 | 5h | VS-010 | 用户无法在 UI 中直接输入破坏性 voice_id |
| VS-012 | P1 | `ui/voice_settings.py` | `load_v2_voices`、`_save_v2_voices_to` | 兼容旧数据：读取 name 反拆分 character/emotion；保存时回写 name | 5h | VS-010 | 导入旧 JSON 后字段自动拆分且保存不丢数据 |
| VS-013 | P2 | `ui/components/voice_rename_wizard.py`（新建） | `VoiceRenameWizard` | 批量改名向导（预览 old->new，冲突检测） | 10h | VS-012 | 批量改名可预览冲突并阻止提交 |
| VS-014 | P1 | `ui/voice_settings.py` | `open_refs_sheet_for_current_row`、`close_refs_sheet` | 抽屉式 sheet 改为 Inspector 工作模式；保留 ESC 关闭 | 4h | 无 | Inspector 打开后主区不出现突兀抖动，ESC 正常收起 |
| VS-015 | P1 | `ui/voice_settings.py` | `main_splitter` 相关 | 记忆右栏宽度（config key）并恢复 | 3h | VS-014 | 重启页面后右栏宽度保持上次值 |
| VS-016 | P2 | `ui/voice_settings.py` | 新增 `apply_compact_layout` | 窄窗口自动切换覆盖式侧栏（不挤压主表） | 8h | VS-014 | 窄屏下主表仍可读，右栏以覆盖形式出现 |
| VR-001 | P1 | `ui/components/voice_refs_sheet.py` | `set_context`、`open_sheet` | Inspector 顶部固定上下文：角色/情绪/voice_id，增加状态区 | 4h | VS-014 | 切换行后右栏上下文即时刷新且一致 |
| VR-002 | P2 | `ui/components/voice_refs_sheet.py` | 新增 `save_ui_state/load_ui_state` | 保存开关状态、最后活动分段（如筛选状态） | 3h | VR-001 | 重新打开右栏后保持上次状态 |
| EA-001 | P0 | `ui/components/emotion_assets_panel.py` | `_render_assets_table` | 资产表增加“操作”列：行内试听按钮（不依赖先选中） | 8h | 无 | 点击任意行“试听”即可播放对应资产 |
| EA-002 | P0 | `ui/components/emotion_assets_panel.py` | `play_selected_asset`、新增 `play_asset(aid)` | 播放状态机：加载中/播放中/失败，状态回写行内 UI | 6h | EA-001 | 播放时行内状态变化可见，失败后状态可恢复 |
| EA-003 | P1 | `ui/components/emotion_assets_panel.py` | 新增 `_preview_cache_path`、`_pick_ext` | 试听缓存增强：保留扩展名、缓存复用、清理策略 | 5h | EA-002 | 同一 asset 二次试听明显更快，不重复下载 |
| EA-004 | P1 | `ui/components/emotion_assets_panel.py` | `_toast_err` 调用点 | 错误提示映射为可执行建议（路径缺失/格式不支持/服务不可达） | 3h | EA-002 | 失败提示包含“下一步怎么修复”而不是仅异常文本 |
| EA-005 | P1 | `ui/components/emotion_assets_panel.py` | `_show_more_menu`、`_show_assets_context_menu` | “删除/解绑”动作加入确认与影响说明（影响当前 voice） | 4h | VS-004 | 删除资源前能看到影响对象并确认 |
| EA-006 | P2 | `ui/components/emotion_assets_panel.py` | `_init_ui` | 上传区、筛选区、危险区分组重排，减少拥挤 | 6h | 无 | 右栏视觉层次更清晰，操作区域不再挤在同一行 |
| EA-007 | P1 | `ui/components/emotion_assets_panel.py` | `bind_selected_assets`、`unbind_selected_assets` | 批量绑定/解绑后给出成功数、失败数和失败原因摘要 | 4h | EA-005 | 批处理反馈可直接定位失败 asset |
| UI-001 | P2 | `ui/voice_settings.py`、`ui/components/*.py` | 样式常量定义点 | 提取 Apple 风格设计 token（间距、圆角、字体、色阶） | 6h | 无 | 关键界面样式参数集中管理，改一处可全局生效 |
| UI-002 | P2 | `ui/voice_settings.py`、`ui/components/*.py` | 所有主要控件布局 | 应用 token 到主页面、Inspector、资产表 | 8h | UI-001 | 视觉一致性提升，控件间距与层级统一 |
| UI-003 | P2 | `ui/voice_settings.py` | 焦点/键盘导航相关 | 增强可访问性：Tab 顺序、焦点高亮、快捷键提示 | 5h | VS-001 | 可仅键盘完成核心流程，焦点位置清晰 |
| VC-001 | P2 | `ui/v2_client.py` | `_raise_for_status`、`V2HttpError.short` | 错误文案增加 endpoint/请求上下文，便于 UI 显示 | 2h | 无 | 报错可定位到具体接口 |
| API-001 | P2 | `core/api_v2_routes.py` | `get_audio_content` | 基于文件扩展返回正确 `Content-Type` | 3h | 无 | wav/mp3/flac 响应头类型正确 |
| API-002 | P2 | `core/api_v2_routes.py` | 错误返回路径 | 统一补充 `code/details` 字段 | 2h | API-001 | UI 可根据 code 给出可执行错误提示 |
| QA-001 | P0 | 手工回归文档 | 新增 `docs/...` 回归记录 | 覆盖误删保护、命名规则、试听、迁移入口、窄屏布局 | 4h | M1-M3 | 回归记录逐项 PASS/PARTIAL，有证据截图或日志 |

## 4. 建议开发顺序（可并行）

| 顺序 | 任务组 | 并行建议 |
|---|---|---|
| 1 | VS-001~VS-008 | 一人主改 `voice_settings.py`；一人可并行准备 UI token |
| 2 | VS-009~VS-013 | 先完成语义拆分与保存兼容，再做批量改名向导 |
| 3 | VS-014~VS-016 + VR-001~VR-002 | 同步推进三栏与 Inspector 行为 |
| 4 | EA-001~EA-007 | 专注参考音频体验，建议单独分支开发 |
| 5 | UI-001~UI-003 | 在功能稳定后统一视觉与可访问性 |
| 6 | VC-001 + API-001~API-002 | 可选后端协同，最后联调 |
| 7 | QA-001 | 每个里程碑结束执行一次 |

## 5. 里程碑验收门槛

| 里程碑 | 必过任务 | 通过标准 |
|---|---|---|
| M1 | VS-001~VS-008、EA-004、QA-001(首轮) | 不再出现高风险误删误改；迁移入口不打扰主流程 |
| M2 | VS-009~VS-016、VR-001~VR-002、EA-001~EA-002、QA-001(二轮) | voice_id 语义稳定；三栏与 Inspector 可用；行内试听可用 |
| M3 | EA-003~EA-007、UI-001~UI-003、QA-001(三轮) | 试听稳定可恢复；视觉一致；键盘操作可完成核心链路 |
| M4(可选) | VC-001、API-001~API-002 | 错误可诊断性与媒体类型兼容进一步提升 |

## 6. 交付物清单

1. 代码改动（按任务 ID 提交）。  
2. 手工回归记录（至少 3 轮，按里程碑）。  
3. 更新后的用户说明（迁移入口位置、编辑模式说明、试听失败处理）。

## 7. 风险与工时缓冲建议

1. `VS-010/VS-012`（字段语义拆分）建议预留 20% 缓冲。  
2. `EA-001~EA-003`（行内试听+缓存）建议预留 25% 缓冲。  
3. 若要控制周期，可先不做 `VS-013`、`VS-016`、`UI-003`、`API-*`。

---

建议先执行 M1 + M2 的必过任务，完成后再决定是否推进 M3/M4。这样能最快把“误操作风险”和“核心可用性”问题压下去。

## 8. M2.6 升级收口任务（右栏挤压 + 文本可读性 + 主参考去路径化）

| ID | 优先级 | 文件 | 目标类/函数 | 开发任务 | 预计工时 | 依赖 | 验收点 |
|---|---|---|---|---|---:|---|---|
| VS-017 | P0 | `ui/voice_settings.py` | `apply_compact_layout`、`_set_inspector_visible` | 在 `<1280` 断点外新增“左侧最小可用宽度”保护，空间不足自动收起 Inspector | 4h | VS-014~VS-016 | 1366/1440 窗口下主表不再被明显挤压 |
| VS-018 | P0 | `ui/theme/tokens.py`、`ui/components/voice_refs_sheet.py` | `Metrics`、`open_sheet` | Inspector 宽度收敛到 400~640，默认 480 | 1h | VS-017 | 右栏展开后主表仍保持可读宽度 |
| VS-019 | P0 | `ui/voice_settings.py` | `update_table` | `角色/情绪` 列压缩：边距/间距缩小、emotion tag 限宽、省略号、compact 隐藏 voice_id 次行 | 3h | VS-010 | 第一列视觉密度明显提升，空白减少 |
| VS-020 | P0 | `ui/voice_settings.py` | 新增 `_render_prompt_text_cell` | `参考文本` 改为两行可读：浏览模式换行显示，编辑模式多行输入 | 5h | VS-002 | 长文本不再单行拥挤，编辑仍可实时保存 |
| VS-021 | P0 | `ui/voice_settings.py` | 新增 `_render_main_ref_cell`、`_open_main_ref_folder` | `主参考` 列改为“状态 + 文件名 + 打开目录”，移除路径正文常驻展示 | 5h | VS-014 | 不显示完整路径，能一键打开参考音频目录 |
| VS-022 | P1 | `ui/voice_settings.py` | 新增 `_open_main_ref_context_menu` | 主参考列补低频操作：选择主参考/复制完整路径 | 2h | VS-021 | 排障时仍能获取完整路径 |
| VS-023 | P1 | `ui/voice_settings.py` | `closeEvent` | 持久化 M2.6 新状态键（min width/auto collapse/wrap lines/show full path） | 1h | VS-017 | 重启后布局策略保持一致 |
| QA-002 | P0 | 回归文档 | 新增 M2.6 回归节 | 按 1366/1440/1600 + 长文本 + 路径缺失场景手工回归 | 3h | VS-017~VS-023 | M2.6 用例逐条 PASS/PARTIAL 并记录证据 |

### M2.6 验收补充清单
1. 右栏展开时主表最小宽度不低于配置阈值（默认 1040）。  
2. 角色/情绪列在 compact 下不再出现大面积无效留白。  
3. 参考文本列两行可读，超长内容 tooltip 可见全文。  
4. 主参考列默认只显示状态与文件名，不显示完整路径正文。  
5. 文件夹按钮可打开参考音频目录；路径缺失时提示明确。  
