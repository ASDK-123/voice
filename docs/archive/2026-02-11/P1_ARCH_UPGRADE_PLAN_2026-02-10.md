# P1 架构健康度升级计划（工业级）

最后更新：2026-02-10

本文件聚焦两件事：
- 继续拆薄 `core/api.py`（以 v2 为主长期维护）
- 缓存索引升级到 SQLite（更稳、更便于统计/清理）

---

## 1. 升级目标

- 降低改动半径：v2 路由/服务/存储边界更清晰，避免在巨型文件继续堆功能
- 提升可运维性：缓存可统计、可清理、可恢复；并发写更稳
- 保持兼容：URL 行为不变；v1 保留兼容入口，v2 作为长期主线

---

## 2. 现状与结论（对应 P1）

### 2.1 `core/api.py` 拆薄进度

- 已完成：v2 资源路由（`assets/voices/jobs/merge`）已拆到 `core/api_v2_routes.py`（Blueprint）
- 仍在 `core/api.py`：app 初始化、模型注入、v1 兼容入口、v2 `health/metrics/synthesize`、全局锁/缓存/队列 glue

下一阶段建议（可选）：
- 把 v2 `health/metrics` 也移入 Blueprint（仍保持 `/health`、`/metrics` 根路径兼容）
- 把 “ctx 组装” 与 “路由注册” 的 wiring 收敛到更小的模块（避免 `api.py` 继续膨胀）

### 2.2 缓存索引（Cache Index）升级到 SQLite

背景：
- 当前缓存音频存于 `data/cache/audio/{request_hash}.wav`
- 之前索引为 JSON：`data/cache/index.json`，在素材变多后会出现：统计/清理成本高、并发一致性弱、崩溃恢复差

本次升级（已落地）：
- 新增 SQLite 索引：`data/cache/index.sqlite3`
- `core/cache_manager.py` 支持两种索引后端：
  - `sqlite`（默认）
  - `json`（兼容回退）
- 环境变量开关：`CACHE_INDEX_BACKEND=json|sqlite`
- 自动导入：当使用 `sqlite` 且 DB 为空、同时存在 `index.json` 时，会做一次非破坏性的 best-effort 导入
- 迁移脚本：`python scripts/migrate_cache_index_json_to_sqlite.py`

验收点：
- 缓存命中/写入/清理逻辑行为不变
- 索引写入使用事务（WAL + busy_timeout），单机并发更稳
- 缺失音频文件会自动剔除索引项（避免索引漂移）

---

## 3. 最短闭环执行顺序（建议）

1. 先确保 v2 路由拆分稳定
- smoke：`/api/v2/health`、`/api/v2/voices`、`/api/v2/assets/audio`、`/api/v2/jobs`、`/api/v2/merge`

2. 切换缓存索引到 SQLite（已完成，默认 sqlite）
- 保留 `CACHE_INDEX_BACKEND=json` 作为回退阀门

3. 文档与现状一致
- `CACHE_QUEUE_DESIGN.md` 标注 SQLite 缓存索引与迁移方式

---

## 4. 回退策略

- 如果 SQLite 在某些环境出现异常：
  - 设置 `CACHE_INDEX_BACKEND=json` 立即回退到 `index.json`
- 索引文件可重建：
  - 删除 `data/cache/index.sqlite3` 后启动，会从现有音频逐步重新写入（或从 `index.json` 导入）

---

## 5. 下一阶段建议（P1 延伸）

- `core/api.py` 继续拆：把 v2 `health/metrics` 合并进 Blueprint（保持根路径兼容）
- Cache meta 逐步补齐：把 `model_fp/voice_fp/voice_id` 等写入 `meta`，方便做统计和“按角色/按情绪”清理策略
- 提供简易统计接口（可选）：缓存命中率、平均命中耗时、LRU 淘汰次数

