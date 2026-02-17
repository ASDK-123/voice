# P4-M1 生产指南：v2 Misc 路由迁出（health / metrics / synth）

最后更新：2026-02-10  
阶段目标：把 `core/api.py` 中剩余 v2 misc 路由（health/metrics/synthesize）迁入 `core/server` 路由模块，进一步压缩入口文件。  
前置阶段：M0 完成并稳定。

---

## 1. 里程碑定义

### 1.1 使命

1. 把 v2 非资源型路由从入口文件迁出：
   - `/api/v2/health`
   - `/api/v2/metrics`
   - `/api/v2/synthesize`
   - 兼容根路径 `/health`、`/metrics`（如现有保留）
2. 保持 v2 路由风格一致（request_id、json_error、日志语义一致）。
3. 建立 `core/server/routes_v2_misc.py` 作为后续 v2 协议演进的唯一入口。

### 1.2 非目标

1. 不改 `core/api_v2_routes.py` 的 assets/voices/jobs/merge 行为。
2. 不改 UI 代码。
3. 不改推理规范化逻辑（M2 再做）。

---

## 2. 架构与边界

### 2.1 新边界

- `core/server/routes_v2_misc.py`：承载 v2 misc route。
- `core/server/app.py`：注册 misc blueprint + v2 resource blueprint。
- `core/api.py`：不再直接定义 v2 route。

### 2.2 依赖注入约束

`routes_v2_misc.py` 不允许直接 import 全局变量，必须通过 `ctx` 注入：
1. `json_ok/json_error`
2. `get_cosyvoice()/get_character_config()`
3. `V2_METRICS` 与锁
4. synth 执行函数（可先沿用旧函数，M3 再引擎化）

---

## 3. DoD（完成标准）

1. `core/api.py` 不再包含 v2 misc route 定义（或仅留兼容转发）。
2. `/api/v2/health`、`/api/v2/metrics`、`/api/v2/synthesize` 行为与迁移前一致。
3. request_id 与错误格式一致（`X-Request-Id` + v2 error schema）。
4. `scripts/p2_backend_acceptance_test.py` 通过。

---

## 4. 执行步骤（可直接照单执行）

## Phase A：冻结协议（0.5 天）

1. 明确路由行为快照（迁移前）：
   - 请求样本（成功/失败）
   - 响应状态码、header、JSON schema
2. 记录兼容点：
   - `response_format=audio/json` 行为
   - cache_hit 字段行为
   - v2 metrics 字段含义

## Phase B：抽离与接线（1-1.5 天）

1. 新增 `core/server/routes_v2_misc.py`
   - 提供 `create_v2_misc_blueprint(ctx)`。
2. 迁移路由实现：
   - `health`
   - `metrics`
   - `synthesize`
3. 在 `core/server/app.py` 注册 blueprint：
   - `/api/v2` 前缀
   - 兼容根路径健康检查（如保留）
4. 清理 `core/api.py` 同名路由，避免重复注册冲突。

## Phase C：行为比对（0.5 天）

1. 使用录制样本做前后 diff：
   - 状态码
   - 关键字段
   - 错误码语义
2. 检查日志：
   - request_id 连贯
   - event 名称保持稳定

---

## 5. 测试矩阵（M1）

### 5.1 协议一致性测试

1. `GET /api/v2/health`
2. `GET /api/v2/metrics`
3. `POST /api/v2/synthesize`（最短文本 + 正常 voice）
4. `POST /api/v2/synthesize`（非法请求 -> 验证 `invalid_request`）

### 5.2 兼容性测试

1. `GET /health`（如保留）
2. `GET /metrics`（如保留）
3. `GET /speakers`
4. `POST /api/tts`

### 5.3 观测性测试

1. 响应 header 带 `X-Request-Id`
2. 失败响应带 `request_id`
3. 结构化日志包含 event/status/duration_ms

---

## 6. 发布计划

### 6.1 发布步骤

1. 在测试环境部署 M1 分支。
2. 执行全量 smoke 与关键回归。
3. 观察 2 小时，再合入主线。

### 6.2 关键观察指标

1. `/api/v2/synthesize` 5xx 比率
2. `/api/v2/health` 超时率
3. request_id 缺失率

### 6.3 回滚方案

1. 恢复 M1 前 `core/api.py` 路由定义。
2. 取消 `routes_v2_misc.py` 注册。
3. 重新发布并验证端点恢复。

---

## 7. 风险与对策

风险 A：路由重复注册  
对策：启动时打印已注册路由表并做断言检查。

风险 B：ctx 注入遗漏  
对策：`create_v2_misc_blueprint(ctx)` 初始化时校验必需字段（缺失即 fail fast）。

风险 C：synthesize 行为微漂移  
对策：保留旧实现调用路径，先做“函数搬运”，不做逻辑改写。

---

## 8. 评审清单

1. 是否有行为变化？若有，是否在 PR 描述明确列出？
2. 是否保留所有兼容路由？
3. 是否统一使用 v2 `json_ok/json_error`？
4. 是否引入新的全局状态耦合？
5. 是否通过回归脚本？

---

## 9. 乔布斯理念对齐（M1）

1. 简洁：同类路由集中在一处，消除巨石文件噪声。
2. 一体化：v2 协议体验统一（错误、日志、request_id 一致）。
3. 细节：保证“看不见的细节”不退化（header、错误字段、兼容路径）。

---

## 10. M1 结束后的目标状态

1. `core/api.py` 只剩极少 glue 与入口职责。
2. v2 route 结构明确分为：
   - `api_v2_routes.py`：资源路由（assets/voices/jobs/merge）
   - `routes_v2_misc.py`：协议路由（health/metrics/synthesize）
3. 后续 M2/M3 可在不触碰入口文件的前提下演进推理逻辑。

