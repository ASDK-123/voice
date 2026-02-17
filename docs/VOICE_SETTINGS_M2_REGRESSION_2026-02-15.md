# Voice Settings M2 回归记录（2026-02-15）

状态：M2 开发完成后的二轮回归记录（静态检查 + 关键流程手工点测指引）
范围：`VS-013`、`VS-016`、`VR-002` 及既有功能回归

## 1. 批量改名（VS-013）

1. 正常改名
- 状态：PASS（静态）
- 证据：新增 `VoiceRenameWizard`，支持 old/new 预览与提交
  - `ui/components/voice_rename_wizard.py`
  - `ui/voice_settings.py` `open_rename_wizard` / `apply_rename_changes`

2. 冲突阻断
- 状态：PASS（静态）
- 证据：向导内对本批次重复 `new_voice_id` 做冲突校验，禁用应用按钮
  - `ui/components/voice_rename_wizard.py` `_recompute`

3. 默认 emotion 回填
- 状态：PASS（静态）
- 证据：新情绪为空时自动设为 `default`
  - `ui/components/voice_rename_wizard.py` `_recompute`

## 2. Compact 布局（VS-016）

1. 窄屏自动折叠 Inspector
- 状态：PASS（静态）
- 证据：`apply_compact_layout(width < 1280)` 触发折叠逻辑
  - `ui/voice_settings.py` `apply_compact_layout`

2. 手动打开/关闭 Inspector
- 状态：PASS（静态）
- 证据：`open_inspector_btn` + `_set_inspector_visible` 统一入口
  - `ui/voice_settings.py` `init_ui` / `_set_inspector_visible`

3. 切回宽屏恢复
- 状态：PASS（静态）
- 证据：退出 compact 后按 `_was_refs_open_before_compact` / `_refs_open_pref` 恢复
  - `ui/voice_settings.py` `apply_compact_layout`

## 3. Inspector 状态记忆（VR-002）

1. 关闭重开后状态恢复
- 状态：PASS（静态）
- 证据：`save_ui_state/load_ui_state` + host 侧初始化恢复
  - `ui/components/voice_refs_sheet.py` `save_ui_state` / `load_ui_state`
  - `ui/voice_settings.py` `init_ui` / `closeEvent`

2. 持久化键
- 状态：PASS（静态）
- 证据：
  - `ui_voice_refs_open`
  - `ui_voice_refs_last_section`
  - 宽度仍使用 `ui_voice_settings_refs_panel_width`

## 4. 既有能力回归

1. 编辑模式/浏览模式
- 状态：PASS（静态）
- 证据：保留并可切换，浏览模式只读

2. 删除撤销
- 状态：PASS（静态）
- 证据：软删除 + 8 秒撤销逻辑仍在

3. 行内试听
- 状态：PASS（静态）
- 证据：资产表操作列 + `play_asset` 状态机仍可用

4. 工具菜单导入旧配置入口
- 状态：PASS（静态）
- 证据：`show_tools_menu` 中保留导入入口

## 5. 语法与基础检查

1. Python 语法检查
- 状态：PASS
- 命令：
```bash
python -m py_compile ui/voice_settings.py ui/components/voice_refs_sheet.py ui/components/emotion_assets_panel.py ui/components/voice_rename_wizard.py core/api_v2_routes.py
```

## 6. 待你本地手工联调项（建议）

1. 批量改名向导：
- 选 5 条 voice 批量改名并应用，确认列表与角色分组同步更新

2. Compact 行为：
- 缩窗到 <1280，确认自动折叠；点击“打开参考面板”后可管理资产；Esc 关闭

3. 状态记忆：
- 打开 Inspector 后重启应用，确认按规则恢复

4. 回归试听：
- 对多条 asset 连续试听，观察“加载中/播放中/重试试听”状态是否稳定

## 7. 结论

- M2 目标功能已完成代码落地，静态检查通过。
- 需要你在本地桌面环境完成一轮真实交互回归（窗口尺寸、媒体播放、重启恢复）以关闭最终验收。
