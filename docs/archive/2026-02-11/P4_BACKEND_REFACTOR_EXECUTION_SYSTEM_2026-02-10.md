# P4 后端重构执行系统（工业级总控手册）

最后更新：2026-02-10  
关联主方案：`P4_BACKEND_REFACTOR_PLAN_2026-02-10.md`  
适用范围：M0-M4 全阶段

---

## 1. 文档目的

本手册定义 P4 的统一执行标准，确保每个里程碑都符合：
1. 工业级生产质量（可观测、可回滚、可验收、可审计）。
2. 持续产品化迭代（低风险增量、兼容优先、可持续维护）。
3. 乔布斯设计理念（简洁、聚焦、一体化体验、细节极致、端到端掌控）。

---

## 2. 执行哲学（乔布斯理念 -> 工程落地）

### 2.1 Focus（聚焦）

- 每个里程碑只解决一个核心问题，不混入“顺手优化”。
- PR 拆分遵循“单一责任”：结构搬迁 PR 与行为变化 PR 分开。

### 2.2 Simplicity（简洁）

- API 层只做传输与协议；推理规则只在 synthesis 层实现一次。
- 任何新增抽象都必须减少复杂度，否则不引入。

### 2.3 End-to-End（端到端体验）

- 用户视角结果一致：UI/API/Bridge 对同请求输出一致、错误语义一致。
- 统一事实源：v2 voices + v2 assets，杜绝配置分叉。

### 2.4 Craftsmanship（细节与工艺）

- 命名、日志、错误码、注释、文档必须统一风格。
- 每次改动都附带可复现验证步骤与回退路径。

### 2.5 Ruthless Prioritization（狠抓优先级）

- 先保稳定和兼容，再谈性能与新特性。
- 阻塞上线的问题优先级高于“理想结构”问题。

---

## 3. 工业级质量基线（所有里程碑共享）

### 3.1 兼容性基线

- 现有端点必须可用：`/`、`/api/tts`、`/speakers`、`/api/v2/*` 核心端点。
- 现有脚本必须可用：`StartAPIServer.bat`、`bridge.py`、`scripts/p2_backend_acceptance_test.py`。

### 3.2 可观测性基线

- 所有新增关键路径输出结构化日志，至少包含：
  - `request_id`
  - `event`
  - `duration_ms`
  - `status`
  - `error.code`（失败时）
- 必须保留 v2 的 `X-Request-Id` 传递链路。

### 3.3 回滚基线

- 每阶段都要具备 30 分钟内回滚能力。
- 回滚脚本/步骤必须写进该阶段生产指南（不可口头约定）。

### 3.4 测试基线

- 最低门禁：
  - `scripts/p2_backend_acceptance_test.py` 通过。
  - 手工 smoke：`/api/v2/health`、`/api/v2/voices`、`/api/v2/assets/audio`、`/api/v2/synthesize`。
  - v1 smoke：`/speakers`、`/api/tts`。

---

## 4. 治理模型（角色与职责）

### 4.1 角色

- Tech Lead（TL）：确认边界、签署架构变更。
- Feature Owner：负责该里程碑实现与联调。
- Reviewer（至少 1 人）：关注兼容性、测试充分性、日志/错误码一致性。
- Release Owner：负责上线、灰度、回滚执行。

### 4.2 责任边界

- TL 负责“做什么、不做什么”。
- Owner 负责“怎么做、如何验收”。
- Reviewer 负责“是否可安全上线”。
- Release Owner 负责“上线结果与恢复”。

---

## 5. 变更流程（统一门禁）

### Gate A：设计冻结（Design Freeze）

通过条件：
1. 明确 In Scope / Out of Scope。
2. 变更文件清单与接口影响清单完整。
3. 回滚策略明确（操作步骤 + 触发条件）。

### Gate B：开发完成（Build Complete）

通过条件：
1. 代码实现完成并自测通过。
2. 日志、错误码、配置项文档同步更新。
3. 单测/组件测覆盖关键路径。

### Gate C：发布就绪（Release Ready）

通过条件：
1. 所有必测项通过。
2. 兼容性检查通过（v1/v2/bridge/UI）。
3. 监控与告警规则已配置。

### Gate D：发布验证（Post Release）

通过条件：
1. 发布后 24h 无 P0/P1 级事故。
2. 关键指标稳定（错误率、响应时延、cache 行为）。
3. 没有新增“配置分叉”类问题。

---

## 6. 指标体系（SLO/SLA 参考）

### 6.1 功能指标

- v2 synth 成功率（2xx）>= 99%（非模型硬件故障场景）。
- v2 voices CRUD 成功率 >= 99.9%。

### 6.2 性能指标

- `/api/v2/health` p95 < 100ms（本机）。
- `/api/v2/voices` p95 < 200ms（本机，小规模配置）。
- 首包时延与总时延以“重构前基线”为参照，不允许明显回退（>10% 需解释）。

### 6.3 稳定性指标

- 无配置错配事故（UI 与外部 API 指向不同 voices 文件导致行为不一致）。
- 无缓存污染事故（schema 变化未 bump 导致旧缓存误命中）。

---

## 7. 代码与配置规范

### 7.1 目录与模块

- 新增后端模块必须放在 `core/server`、`core/synthesis`、`core/storage` 三层之一。
- 禁止把新业务逻辑继续堆回 `core/api.py`。

### 7.2 配置规范

- `app_config.json` 只存应用设置，不存业务 voices 内容。
- v2 voices 只允许一个运行时事实源路径。
- legacy 配置只允许导入，不允许继续写入。

### 7.3 错误与日志规范

- 对外错误（v2）统一 `{"error":{"code","message","details"},"request_id":"..."}`。
- 结构化日志字段命名统一 snake_case。

---

## 8. 发布与回滚策略

### 8.1 发布策略

- 推荐“小步快跑”：
  - 先结构搬迁（行为不变）
  - 再逻辑收敛（有限行为变化）
  - 最后配置收口（用户可见行为变化）

### 8.2 回滚触发条件

满足任一条件立即回滚：
1. v1 或 v2 核心端点不可用。
2. 输出行为明显错误（音频为空、错误码错乱、路径错配）。
3. 新增异常导致 bridge/GUI 主流程不可用。

### 8.3 回滚动作模板

1. 切回上一稳定 tag/commit。
2. 恢复旧入口文件（若本阶段替换了 `core/api.py`）。
3. 若涉及 cache key 变化，恢复 schema_version 或清理新缓存索引。
4. 发布回滚公告并记录 RCA。

---

## 9. 风险分级与应急

- P0：服务不可用、核心链路中断 -> 立即回滚。
- P1：功能可用但关键行为错误（错配 voice/ref）-> 限时修复或回滚。
- P2：非核心功能异常（文档/日志不足）-> 下一个小版本修复。

---

## 10. 文档集索引（本次新增）

1. `P4_M0_STRUCTURAL_ASSEMBLY_PRODUCTION_GUIDE_2026-02-10.md`
2. `P4_M1_V2_MISC_ROUTE_EXTRACTION_PRODUCTION_GUIDE_2026-02-10.md`
3. `P4_M2_SYNTHESIS_NORM_UNIFICATION_PRODUCTION_GUIDE_2026-02-10.md`
4. `P4_M3_SYNTHESIS_ENGINEIZATION_PRODUCTION_GUIDE_2026-02-10.md`
5. `P4_M4_CONFIG_SINGLE_SOURCE_PRODUCTION_GUIDE_2026-02-10.md`

建议阅读顺序：总控手册 -> M0 -> M1 -> M2 -> M3 -> M4。

---

## 11. 每个里程碑必须交付的产物模板

1. 设计简报（范围、接口影响、风险清单）。
2. 变更清单（文件列表 + 关键 diff 摘要）。
3. 测试报告（命令、结果、失败项与处理）。
4. 发布记录（上线时间、版本、观察窗口）。
5. 回滚记录（如触发）。

