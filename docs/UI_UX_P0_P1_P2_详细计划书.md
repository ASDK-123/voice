# CosyVoice Desktop UI 改造 P0/P1/P2 详细计划书

更新日期：2026-02-17  
范围：`ui/` 桌面端（PyQt5 + qfluentwidgets）  
关联文档：`docs/UI_UX_改造方案_线稿.md`

## 1. 项目细节检查结果（用于确定优先级）

## 1.1 当前实际主流程页面

基于 `ui/main_window.py` 导航与路由：
1. 主流程页面：`text_edit.py`、`task_plan.py`、`voice_settings.py`、`api_page.py`、`settings.py`
2. `EmotionVoicesInterface` 入口已被重定向到 `voice_settings`（`open_emotion_redirect`），不是当前主流程页面
3. 参考音频管理主链路在 `voice_settings.py` -> `components/voice_refs_sheet.py` -> `components/emotion_assets_panel.py`

结论：**P0/P1 必须优先覆盖主流程页面和组件链路；`emotion_voices.py` 作为兼容页面后置处理。**

## 1.2 代码规模与复杂度热点

按行数（近似复杂度）：
1. `ui/voice_settings.py`：2225 行（最高耦合）
2. `ui/emotion_voices.py`：1250 行（兼容页，且结构重）
3. `ui/components/emotion_assets_panel.py`：852 行（主流程资产面板）
4. `ui/api_page.py`：815 行（运维与线程状态集中）
5. `ui/main_window.py`：762 行（全局编排）
6. `ui/voice_setup_wizard.py`：716 行（流程向导）

## 1.3 UI 风险指标（已量化）

1. Emoji/符号化文案：70 处（集中于 `api_page.py`、`main_window.py`、`task_plan.py`）
2. `setFixedHeight/Width/Size`：89 处（集中于 `emotion_voices.py`、`voice_setup_wizard.py`、`emotion_assets_panel.py`）
3. 颜色硬编码：37 处（集中于 `voice_settings.py`、`voice_setup_wizard.py`、`emotion_voices.py`）

## 1.4 技术约束

1. UI 异步大量依赖 `QThread` + 信号槽，改造要避免引入线程生命周期回归
2. 已有 token 系统在 `ui/theme/tokens.py`，应继续扩展而非并行新增第二套
3. 暂无 UI 自动化测试，验收主要依赖手工回归 + 关键后端测试 (`tests/`)

---

## 2. 目标与分期原则

## 2.1 总目标

1. UI 风格统一（去 Emoji、统一视觉语义、统一状态反馈）
2. 主流程效率提升（语音设置、API 运维、文本到任务链路）
3. 减少维护成本（抽离可复用组件，降低重复样式/重复逻辑）

## 2.2 分期原则

1. `P0`：低风险高收益，尽量不动业务逻辑和数据结构
2. `P1`：布局与交互重构，允许中等规模改动但要保持行为兼容
3. `P2`：组件沉淀、遗留收敛、质量门禁

---

## 3. P0 计划（视觉统一与低风险收敛）

目标周期：3-5 个工作日  
目标结果：主流程“看起来像同一产品”，且不改变核心业务行为

## 3.1 工作包

1. `P0-WP1` 设计 token 补齐
文件：
- `ui/theme/tokens.py`
内容：
- 增加强调色/焦点色/弱文本色（例如 `ACCENT`、`FOCUS_RING`、`TEXT_MUTED`）
- 明确语义色用途注释（SUCCESS/WARNING/DANGER）
完成标准：
- 新增 token 在后续页面替换中被实际引用

2. `P0-WP2` 主流程去 Emoji 化（文案与标题层）
文件：
- `ui/api_page.py`
- `ui/text_edit.py`
- `ui/task_plan.py`
- `ui/settings.py`
- `ui/main_window.py`（日志模板与导航文案）
内容：
- 标题与按钮去 Emoji
- 日志前缀改为文本等级：`[INFO] [WARN] [ERROR] [OK]`
完成标准：
- 主流程页面不再依赖 Emoji 传达语义

3. `P0-WP3` 硬编码颜色替换
文件：
- `ui/voice_setup_wizard.py`
- `ui/settings.py`
- `ui/asset_cleanup_dialog.py`
- `ui/emotion_voices.py`（仅低风险替换）
内容：
- 替换 `gray`、`rgba(0,0,0,0.65)` 等硬编码到 `Palette.*`
完成标准：
- 明暗主题下说明文本可读性稳定（人工检查）

4. `P0-WP4` 轻量交互一致性修复
文件：
- `ui/api_page.py`
- `ui/task_plan.py`
- `ui/text_edit.py`
内容：
- 统一按钮尺寸层级（Primary/Secondary）
- 关键异步按钮执行时禁用重复点击（启停 API、桥接启停）
完成标准：
- 不出现“多次点击触发重复动作”现象

## 3.2 P0 验收清单

1. 主流程页面标题/核心按钮无 Emoji
2. 颜色硬编码问题明显减少（目标 <= 12 处）
3. 启停类按钮有 Busy/禁用保护
4. 功能无回归：文本合成、任务运行、voice 保存、API 启停可用

## 3.3 P0 风险与应对

1. 风险：日志可读性变化影响习惯  
应对：保留关键词（成功/失败/警告）和颜色等级
2. 风险：样式替换导致个别控件对比不够  
应对：逐页人工对比 Light/Dark 截图

---

## 4. P1 计划（布局重构与交互优化）

目标周期：5-8 个工作日  
目标结果：高频流程点击路径更短、布局更稳、状态反馈更一致

## 4.1 工作包

1. `P1-WP1` API 页面结构重排（高优先）
文件：
- `ui/api_page.py`
内容：
- 结构重排为：服务控制 -> 运行开关 -> voices 表格 -> 日志
- 日志区支持等级 badge（文本等级 + 颜色）
- 状态展示卡片化（API/桥接）
完成标准：
- 关键运维操作不超过 2 级视线跳转
- 启停/错误定位更直接

2. `P1-WP2` 语音设置页可维护性增强
文件：
- `ui/voice_settings.py`
- `ui/components/voice_refs_sheet.py`
- `ui/components/emotion_assets_panel.py`
内容：
- 抽离 `page header / status strip` 样式片段为可复用 helper（可先内部函数）
- 统一 refs 面板操作按钮排序与层级
- 表格列宽策略优化（1280 宽不遮关键列）
完成标准：
- refs 相关交互一致（上传/绑定/备注/试听）
- 表格可读性提升

3. `P1-WP3` 兼容页策略处理（`emotion_voices.py`）
文件：
- `ui/emotion_voices.py`
- `ui/main_window.py`（如需进一步弱化入口）
内容（二选一）：
- 方案 A：做最小视觉对齐，保留可用
- 方案 B：标注 legacy，进一步导流到 `voice_settings`
完成标准：
- 团队明确该页是“主维护”还是“兼容冻结”

4. `P1-WP4` 异步反馈标准化
文件：
- `ui/api_page.py`
- `ui/voice_setup_wizard.py`
- `ui/components/emotion_assets_panel.py`
内容：
- 统一异步流程模板：开始（禁用）-> 处理中 -> 成功/失败 -> 恢复
- 统一错误文案结构（含建议动作）
完成标准：
- 超过 300ms 的操作都有可见反馈

## 4.2 P1 验收清单

1. API 页结构清晰，日志等级统一
2. refs 面板与 voice 设置交互链路清晰
3. 兼容页策略有明确结论
4. 高频异步流程无“静默等待”与重复点击问题

## 4.3 P1 风险与应对

1. 风险：重排布局影响旧习惯  
应对：保留操作入口名称与顺序语义，不做激进改名
2. 风险：`voice_settings.py` 耦合高，改动易引回归  
应对：按功能块逐段提交，分批人工回归

---

## 5. P2 计划（组件沉淀、遗留收敛、质量门禁）

目标周期：4-6 个工作日  
目标结果：形成可复用 UI 基建，后续页面迭代成本下降

## 5.1 工作包

1. `P2-WP1` 新增通用组件
建议新增文件：
- `ui/components/async_button.py`
- `ui/components/status_badge.py`
- `ui/components/page_header.py`
- `ui/components/empty_state.py`
内容：
- 将 P0/P1 中重复出现的样式与交互抽象为组件
完成标准：
- 至少 2 个页面实际接入每个核心组件（async/status/page_header）

2. `P2-WP2` 遗留样式清债
范围：
- 清理剩余硬编码颜色、魔法数字尺寸
- 统一按钮高度/间距到 `Metrics` 和 `Spacing`
完成标准：
- `setStyleSheet(\"color:...\")` 零散硬编码显著减少（目标 <= 5 处）

3. `P2-WP3` 文档与门禁
文件：
- `docs/` 新增维护指南
- 可选新增脚本：统计 emoji/硬编码颜色/固定尺寸
内容：
- 约定新增页面必须走 token 与组件规范
- 固化“提交前 UI 自检清单”
完成标准：
- 新人可按文档快速按同一风格开发页面

## 5.2 P2 验收清单

1. 通用组件落地并被主流程页面复用
2. 剩余样式债务受控，新增页面不再复制粘贴样式
3. 有明确的 UI 开发与验收规范文档

---

## 6. 质量保障与回归策略

## 6.1 手工回归矩阵（每阶段都执行）

1. 页面打开与导航：主页面全部可打开、切换无异常
2. 关键流程：
- 文本编辑 -> 一键运行
- 文本编辑 -> 转任务计划 -> 全部运行
- 语音设置：加载/保存/应用/编译
- refs 面板：上传/绑定/解绑/试听/备注
- API 页：启动/停止 API，启动/停止桥接，刷新 voices
3. 主题切换：Light/Dark 下文本可读
4. 窗口宽度：1024、1280、1400+

## 6.2 自动化建议

当前 `tests/` 主要覆盖核心合成与存储逻辑，UI 自动化为空。建议：
1. 每次 UI 改造后至少执行一次 `python -m pytest tests/`
2. 中长期引入最小 UI smoke（可先做启动/页面加载级）

---

## 7. 里程碑与交付物

1. `M1 (P0 完成)`：视觉统一基础版
交付：
- 改动 PR（样式统一 + 去 Emoji + 硬编码替换）
- P0 回归记录

2. `M2 (P1 完成)`：结构优化版
交付：
- API 页与 refs 链路改造 PR
- 交互一致性回归记录

3. `M3 (P2 完成)`：工程化版
交付：
- 通用组件 PR
- UI 规范文档 + 自检脚本（可选）

---

## 8. 建议执行顺序（落地版）

1. 先做 `P0-WP1/WP2/WP3`（风险最低，收益立刻可见）
2. 再做 `P1-WP1`（`api_page.py`，独立度高）
3. 再做 `P1-WP2`（`voice_settings` + refs 链路）
4. 最后做 `P2` 组件沉淀与遗留清债

该顺序能保证每一阶段都有可交付成果，同时把高耦合风险放在中期处理，避免一开始大范围改动导致回归难控。

