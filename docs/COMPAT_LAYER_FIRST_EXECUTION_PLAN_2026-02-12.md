# 兼容层优先实施清单（Unitale 接入）

## 1. 目标与决策

本方案采用“兼容层优先，重构后置”策略，先让 `peiying/Unitale` 在**不改前端代码**的前提下接入当前后端，再决定是否启动完整前端重构。

决策结论：

1. 第一阶段优先做协议兼容层（低风险、周期短、可快速验证业务价值）。
2. 第二阶段基于真实使用数据，评估是否进入“完全重构前端工作台”。

## 2. 成功标准（Definition of Done）

满足以下条目即视为第一阶段完成：

1. Unitale 的 TTS Base URL 指向当前服务后，可直接通过以下接口完成全链路：
   1. `GET /v1/check/audio`
   2. `POST /v1/upload_audio`
   3. `POST /v2/synthesize`
2. 不破坏现有能力：
   1. `/api/v2/synthesize` 行为不退化
   2. `/api/v2/assets/audio` 行为不退化
   3. 桌面端任务生成链路不退化
3. 有自动化测试与手工 smoke 清单，且可重复执行。

## 3. 现状与缺口

现有后端主能力：

1. `POST /api/v2/synthesize`
2. `POST /api/v2/assets/audio`
3. `GET/POST/PUT/DELETE /api/v2/voices*`

Unitale 期望协议：

1. `GET /v1/check/audio?file_name=...`
2. `POST /v1/upload_audio`（`multipart/form-data`，字段 `audio` + `full_path`）
3. `POST /v2/synthesize`（JSON 里常见字段：`text`、`audio_path`、`emo_text`、`emo_vector`）

核心缺口：

1. 路径前缀不一致（Unitale 无 `/api` 前缀）。
2. 上传与校验接口命名不一致。
3. 合成请求字段语义不一致（`audio_path/emo_*` 与 `voice_id/prompt_*`）。

## 4. 范围定义

本阶段 In-Scope：

1. 新增 Unitale 兼容端点。
2. 做请求映射与响应适配。
3. 增加最小可用的路径别名管理（`full_path` -> 实际资产）。
4. 完成测试、文档、回滚机制。

本阶段 Out-of-Scope：

1. 复刻 Unitale 全部前端能力（LLM 编排、时间轴编辑器、工程包 UI）。
2. 对 `emo_vector` 做高保真情绪建模。
3. 重写桌面端架构。

## 5. 接口兼容规范（落地版）

### 5.1 `GET /v1/check/audio`

请求：

1. Query: `file_name`（字符串）

响应（HTTP 200）：

```json
{
  "exists": true,
  "file_name": "uploaded/ref.wav",
  "asset_id": "ref_xxx",
  "path": "C:/.../data/assets/audio/ref_xxx.wav"
}
```

说明：

1. `exists=false` 时 `asset_id/path` 可为空字符串。
2. Unitale 只依赖 `exists`，其余字段用于调试。

### 5.2 `POST /v1/upload_audio`

请求：

1. `multipart/form-data`
2. 字段 `audio`（文件，必填）
3. 字段 `full_path`（字符串，选填，建议必传）

响应（HTTP 200 或 201）：

```json
{
  "ok": true,
  "file_name": "uploaded/ref.wav",
  "asset_id": "ref_xxx",
  "path": "C:/.../data/assets/audio/ref_xxx.wav",
  "size": 123456,
  "sha1": "..."
}
```

### 5.3 `POST /v2/synthesize`

输入兼容优先级：

1. 若请求含 `voice_id`，优先走现有 voice 逻辑。
2. 若请求含 `audio_path`，先解析为本地 `prompt_audio` 路径后走 direct 合成逻辑。
3. `emo_text` 先做弱映射（例如作为 `emotion` 或附加到 `instruction`），保证可用优先。
4. `emo_vector` 本阶段可忽略，但必须不报错。

建议映射表：

| Unitale 字段 | 目标字段 | 规则 |
|---|---|---|
| `text` | `text` | 直接透传 |
| `audio_path` | `prompt_audio` | 先按 `full_path` 别名解析；解析失败再按本地相对路径解析 |
| `emo_text` | `emotion` | 非空时写入 `emotion`；无对应 voice 时允许回退 |
| `emo_vector` | - | 本阶段忽略，不影响响应 |
| `speed` | `speed` | 可选透传 |

响应：

1. 成功时返回 `audio/wav`（与 Unitale 当前预期一致）。
2. 失败时返回简洁 JSON 错误，避免长栈信息泄漏。

## 6. 路径别名设计（最小可用）

目标：支持 Unitale 的 `full_path/file_name` 语义，不要求真实文件路径与客户端一致。

方案：

1. 维护一个别名索引（建议文件：`data/unitale_path_index.json`）。
2. 结构：`{ "uploaded/ref.wav": {"asset_id":"ref_xxx","path":"...","sha1":"...","updated_at":...} }`
3. 上传成功后写入索引。
4. `check/audio` 先查索引，再校验目标文件是否存在。
5. 合成时 `audio_path` 优先查索引命中；命中即转为真实 `prompt_audio`。

约束：

1. `full_path` 仅作为逻辑 ID，不作为直接写盘路径。
2. 禁止目录穿越（拒绝 `..`、盘符跳转、UNC 注入等危险模式）。

## 7. 里程碑执行清单

## M0 - 基线冻结（0.5 天）

- [ ] 记录现有 API baseline：`/api/v2/health`、`/api/v2/synthesize`、`/api/v2/assets/audio`
- [ ] 保存一组当前可复现 smoke 输入输出（文本、voice、响应码）
- [ ] 明确开关策略：兼容层默认关闭或默认开启（建议先开关可控）

验收：

1. 有 baseline 记录文档和命令清单。

## M1 - 路由脚手架（0.5~1 天）

- [ ] 新增兼容层路由模块（建议独立 blueprint，便于回滚）
- [ ] 注册 `GET /v1/check/audio`
- [ ] 注册 `POST /v1/upload_audio`
- [ ] 注册 `POST /v2/synthesize` 兼容入口

验收：

1. 三个兼容路由可访问，未接入映射逻辑也要返回可识别错误码。

## M2 - 上传/校验闭环（1 天）

- [ ] 实现 `upload_audio` 文件校验（大小、后缀、空文件）
- [ ] 上传后复用现有资产保存能力，拿到 `asset_id/path/sha1`
- [ ] 写入路径别名索引
- [ ] 实现 `check/audio` 查询（`exists` 准确）
- [ ] 单测覆盖上传成功、重复上传、缺字段、非法路径

验收：

1. Unitale 的“检查存在 -> 上传 -> 再检查存在”链路通过。

## M3 - 合成映射闭环（1.5~2 天）

- [ ] 实现 `audio_path` 到 `prompt_audio` 解析
- [ ] 实现 `text`、`speed` 映射
- [ ] 实现 `emo_text` 弱映射（可配置）
- [ ] 兼容 `emo_vector`（忽略但不报错）
- [ ] 复用现有引擎输出 `audio/wav`
- [ ] 单测覆盖：正常合成、缺 `audio_path`、路径不存在、空文本

验收：

1. Unitale 单句测试可直接播音，HTTP 200 且返回 `audio/wav`。

## M4 - 稳定性与发布（1 天）

- [ ] 增加兼容层日志前缀（例如 `compat_unitale`）
- [ ] 增加关键指标计数（请求数、失败数、路径未命中数）
- [ ] 更新 `API_USAGE.md`（新增兼容层章节）
- [ ] 增加回滚开关与发布说明
- [ ] 完成回归测试（现有 tests + 新增 compat tests）

验收：

1. 兼容层开关关闭后，系统行为恢复为现状。
2. 兼容层开启后，Unitale 与现有桌面端可并存。

## 8. 测试清单（可直接执行）

接口 smoke（建议写入 `scripts/smoke_unitale_compat.ps1`）：

1. `GET /v1/check/audio?file_name=uploaded/ref.wav`（初始应 `exists=false`）
2. `POST /v1/upload_audio` 上传一个 wav（应返回 `ok=true`）
3. 再次 `GET /v1/check/audio`（应 `exists=true`）
4. `POST /v2/synthesize` with `text + audio_path`（应返回 `audio/wav`）
5. `POST /api/v2/synthesize` with `voice_id`（现有链路不退化）

自动化建议新增测试文件：

1. `tests/test_unitale_compat_routes.py`
2. `tests/test_unitale_compat_mapping.py`
3. `tests/test_unitale_compat_security.py`

## 9. 风险与对策

风险 1：`emo_text/emo_vector` 与现有情绪模型语义不等价。  
对策：本阶段以“可用优先”，先弱映射；情绪保真在第二阶段优化。

风险 2：`audio_path` 逻辑 ID 与真实文件路径混淆。  
对策：强制走别名索引，不允许把 `full_path` 直接用于写盘。

风险 3：新增入口影响现有路由。  
对策：独立 blueprint + 开关控制 + 明确回滚步骤。

## 10. 回滚方案

1. 通过环境变量关闭兼容层路由注册（建议名：`ENABLE_UNITALE_COMPAT=false`）。
2. 保留新增代码但不对外暴露路由，确保 1 分钟内恢复。
3. 路径别名索引文件可保留，不影响主流程。

## 11. 工期评估（单人）

1. 开发与联调：3.5 ~ 5.5 天
2. 测试与文档：1 ~ 1.5 天
3. 合计：4.5 ~ 7 天

## 12. 第二阶段触发条件（是否进入完全重构）

满足任意两条可进入重构立项：

1. 兼容层上线后，7 天内活跃使用稳定且需求持续增长。
2. 用户明确要求浏览器工作台替代桌面主流程。
3. 兼容层无法承载新增高级能力（复杂时间轴、工程资产协作等）。

---

本清单目标是先把“能用、稳用、可回滚”做到位，再决定是否投入完整重构。
