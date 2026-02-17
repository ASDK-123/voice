# 技术规范与架构审查（2026-02-09）

这份文档是对当前仓库的“工程规范/可维护性/安全性/架构合理性”的一次静态审查，重点结合你最近引入的两套升级（缓存队列、情绪音色管理）后的整体情况。

> 结论先说：以“单机自用 + 局域网自用”的目标来看，当前架构能跑、功能覆盖面也够，但工程化规范明显不足，后续迭代成本会快速上升；如果你希望项目长期可维护、可复制部署、稳定扩展，建议优先补齐依赖/配置/模块拆分/错误规范/资产存储这几块。

## 1. 架构是否合理（整体评价）

### 1.1 当前架构的优点
- **分层大体清晰**：`ui/`（桌面端）、`core/`（推理与 API）、`bridge*.py`（OpenAI 兼容桥接）、`client/`（调用示例）、`data/`（v2 运行时数据）。
- **推理加速路径明确**：`core/utils.py` 统一封装 `AutoModel(load_trt=True, fp16=...)`，并通过 `app_config.json`/环境变量切换加速选项（TensorRT、FP16、可选 vLLM）。
- **“结果缓存 + 任务队列”升级方向正确**：对单机 GPU 场景，结果缓存 + 串行/限并发 worker 是最有效的稳定性手段。
- **v2 形态更适合长期维护**：assets/voices/synthesize/jobs/merge 的 API 形态比 v1 更可控（可观测、可扩展）。

### 1.2 当前架构的主要不合理点（会拖累长期迭代）
- **`core/api.py` 过度集中**：同时承载 v1/v2 路由、推理、配置、缓存、队列、资产索引、FFmpeg 等，文件已到 2800+ 行（`core/api.py`），长期必然难改难测。
- **“桌面端 voice_config” 与 “API v2 voices/assets” 双轨并行**：两套数据模型并存，会产生配置漂移、重复维护与用户困惑（UI 改了不影响 v2，反之亦然）。
- **存储层（已升级）**：v2 资产索引已迁移到 SQLite（`data/api_v2_assets.sqlite3`），历史上的 JSON 索引（`data/api_v2_assets.json`）仅作为兼容/迁移入口保留。

## 2. 工程规范符合度（Checklist）

下面按常见工程规范维度给出结论与证据点（含文件定位）。

### 2.1 版本控制与变更管理：不达标
- 当前目录不是 git 仓库（没有 `.git/`），意味着：
  - 无法可靠回滚/审查变更/做发布标记
  - 文档与代码的“版本对应关系”无法追踪
- 建议：把源码与“打包产物/运行数据”分开管理，最少做到“源码目录是 git 仓库 + 有 `.gitignore`”。

### 2.2 依赖管理与可复现部署：不达标
- 主工程缺少明确的依赖清单（没有 `requirements.txt` / `pyproject.toml` / `pixi.toml`）。
- 存在 **依赖文件与实际实现不一致**：
  - `bridge_requirements.txt` 只有 `httpx/fastapi/uvicorn`，但 `bridge.py` 实际使用的是 Flask + requests（`bridge.py:1` 起）。
- 存在“环境目录被提交”的迹象：`.pixi/envs/default/` 存在，但缺少对应的环境声明文件（例如 `pixi.toml`），导致别人难以“按声明重建环境”。

建议（优先级高）：
1. 选一种路线固化依赖：
   - 路线 A：补齐 `pixi.toml`（推荐，与你现有脚本一致）
   - 路线 B：补齐 `pyproject.toml` + `requirements.lock`（或 uv/pip-tools）
2. 统一 bridge 依赖文件：要么改成 Flask 的 requirements，要么把 bridge 升级成 FastAPI 并实际使用。

### 2.3 代码组织与模块边界：部分达标，但需要尽快重构
证据点：
- `core/api.py` 内部含大量职责与路由（路由数量 29 个），且存在 `sys.path.insert(...)` 的“路径注入”做法（`core/api.py:31-33`），这通常意味着工程未按包/模块规范组织。
- `ui/api_page.py` 存在硬编码 Python 路径启动桥接服务（`ui/api_page.py:680-683`），导致换机器/换环境直接失效。

建议（优先级高）：
- 把 v2 拆分为 `core/v2/` 子包，按资源拆：`assets.py`、`voices.py`、`synthesize.py`、`jobs.py`、`metrics.py`。
- 把推理层抽成一个清晰的 service：例如 `core/infer_service.py`，API 与 GUI 都只调用它。
- 消除 `sys.path.insert`：把 `core/` 做成真正的 python package（可 `pip install -e .` 或 pixi/uv 管理），第三方依赖用正常依赖方式安装/引用。
- `ui/api_page.py` 启动 bridge：用 `sys.executable` 或 `.pixi/envs/.../python.exe` 自动发现，不要写死本机路径。

### 2.4 错误处理/状态码规范：已基本达标（仍建议持续收敛一致性）
证据点：
- 已修复：v2 端点已统一走结构化错误返回（`{"error":{"code":...,"message":...},"request_id":...}`），并对常见异常映射状态码（400/404/409/413/500 等）。

建议（优先级高）：
- 建立统一错误规范：
  - 400：参数错误/缺字段/非法值
  - 401/403：鉴权失败
  - 404：资源不存在（voice/asset/job）
  - 409：冲突（同名 voice 已存在）
  - 429：限流
  - 500：服务端内部错误（含推理失败、依赖缺失、存储异常）
- 返回结构统一为：
  - `{"error": {"code": "...", "message": "...", "details": {...}}}`
- 对 500 级错误必须写日志（带 request_id/cache_key/voice_id/asset_id）。

### 2.5 安全性与资源治理：部分达标（单机自用可接受，但需要防踩坑）
风险点：
- **上传接口大小限制**：当前已设置 Flask `MAX_CONTENT_LENGTH`（默认 50MB，可用 `MAX_UPLOAD_MB` 调整），超限返回 413（v2 风格 JSON）。
- **CORS 策略**：项目中有 CORS 支持（`core/api.py` 引入 `flask_cors`），若对局域网开放建议限制来源或至少提供开关。
- **多进程一致性（部分已解决）**：v2 assets 索引已走 SQLite（事务一致）；但仍不建议同时运行两份 API 进程并对同一份 voices JSON（`--config` / `v2_voices_config_path`）做写入，否则会产生覆盖风险。

建议（中高优先级）：
- 增加上传大小上限 + 友好错误（413 Payload Too Large）。
- v2 资产索引已改为 SQLite（`data/api_v2_assets.sqlite3`）；如存在旧 JSON 索引，可用脚本一次性迁移后再停用旧文件。
- 生产形态下，明确只允许运行一个 API 进程；或把资产/缓存索引升级为多进程安全存储。

### 2.6 可观测性：起步了，但还不够
现状：
- 有 `/health`、`/metrics`、`/api/v2/metrics`（`core/api.py:1554`、`core/api.py:1571`、`core/api.py:1576`）。
- 有 cache hit/miss、队列深度等指标（v2）。
- 已有 `request_id`：服务端会生成/回传 `X-Request-Id`，v2 JSON 成功/失败响应体也会带 `request_id` 字段。

建议（中优先级）：
- metrics 增加耗时分布：总耗时、推理耗时、cache IO 耗时、merge 耗时（至少 avg/p95）。
- 日志结构化：输出 `cache_key`、`selected_ref_asset_id`、`character/emotion`、`job_id`、`segment_index`。
- 在关键业务日志里补齐 `request_id` 相关字段（例如 `cache_key/voice_id/asset_id`），并确保异常路径也能稳定落日志（便于排障）。

### 2.7 测试与质量门禁：不达标
现状：
- 有一些脚本（`latency_test.py`、`api_stress_test.py`），但没有自动化测试套件与回归保障。

建议（中优先级）：
- 加最小单测：
  - `core/cache_manager.py`：LRU 淘汰、原子写入、in-flight 去重
  - `core/cache_keys.py`：同输入 hash 稳定、voice 更新导致 hash 变化
  - `core/emotion_selector.py`：fallback、random_per_text 的稳定性
- 加最小集成测试脚本：assets 上传 -> voice 创建 -> synth 两次命中 -> voice 更新 -> miss。

## 3. 针对“情绪管理 + 多 ref + 指令增强”的专项建议

### 3.1 方案本身是可行的（你现在的实现方向正确）
- 情绪“不是训练而是选择不同参考音频/缓存”是正确路线：成本低、效果可控。
- 默认策略用 `random_per_text`（稳定随机）能兼顾“多样性”与“缓存命中一致性”。

### 3.2 需要补齐/明确的设计细节（避免未来踩坑）
- **voice schema 需要固化**：建议明确以下字段语义，并在 API 中做校验：
  - `character`、`emotion`（emotion 默认 `default`）
  - `ref_asset_ids[]`（只能引用 kind=ref 的资产）
  - `selection_policy`（枚举）
- **缓存键版本升级策略**：你现在有 `V2_CACHE_SCHEMA_VERSION`（`core/api.py:378`），后续每次变更 key 组成要 bump，避免旧缓存被误用。
- **随机化的“可控重掷”**：建议把 `variation_seed` 暴露到 UI，并明确：
  - `variation_seed=0`：稳定
  - `variation_seed++`：重新挑选同情绪下的 ref（reroll）

## 4. 下一步建议（按“性价比最高”排序，结合你的选择已更新）

### 4.1 第一优先级（强烈建议马上做）
1. 把“本地维护”做成可回滚、可追踪
   - 即使你是一个人用，也强烈建议初始化 git 仓库，并补齐 `.gitignore`
   - 建议忽略：`data/`、`output/`、`__pycache__/`、日志、临时文件、`data/cache/audio/*.wav`
2. 固化依赖与启动方式（以 v2 为主）
   - 你当前脚本与说明都在用 `.pixi`，但缺少 `pixi.toml` 这类“环境声明文件”，别人或未来的你很难复现
   - 建议走 pixi 路线：补齐 `pixi.toml`（并明确 Python 版本、torch/torchaudio、flask、flask-cors、requests、httpx 等）
   - 立即修正 `bridge_requirements.txt` 与 `bridge.py` 的不一致：二选一
     - 用 Flask：requirements 改成 Flask + requests
     - 用 FastAPI：代码改成 FastAPI（并删除/废弃 flask bridge）
3. 修复明显的可移植性问题
   - 去掉 `ui/api_page.py:680-683` 的硬编码 python 路径，改用 `sys.executable` 或自动探测 `.pixi/envs/*/python.exe`
4. 错误码与状态码规范化（优先改 v2）
   - `v2_synthesize` 的兜底异常不应返回 400；改为 500，并记录日志（`core/api.py:2214-2219`）
   - 给 v2 端点补齐统一错误结构：`{"error": {"code": "...", "message": "...", "details": {...}}}`
5. 上传与资源治理的底线保护
   - 为 Flask 设置 `MAX_CONTENT_LENGTH`，避免大文件直接把内存打爆（v2 assets/audio、v2 synth multipart）
6. 把“未来扩展”的存储底座先铺好：把 v2 资产索引从 JSON 升级到 SQLite
   - 已完成：v2 assets 元数据已迁移到 SQLite `data/api_v2_assets.sqlite3`
   - 兼容：如存在旧 `data/api_v2_assets.json`，可运行 `python scripts/migrate_v2_assets_json_to_sqlite.py` 一次性导入
   - 同步建议：cache 的 `index.json` 未来也可以迁移到 SQLite（可选，第二阶段做）

### 4.2 第二优先级（稳定性与可维护性显著提升）
1. 拆分 `core/api.py`（按 v2 资源拆模块，v1 放到 legacy）
   - 目标：v2 成为主路径；v1 只保留兼容（并在文档/代码里标记 legacy）
2. jobs/缓存/指标的工程化
   - 增加耗时指标（avg/p95）、request_id、结构化日志字段（cache_key/job_id/asset_id/character/emotion）
3. 更严格的输入校验
   - voice schema 校验（character/emotion/ref_asset_ids/selection_policy）
   - ref_asset_ids 只能引用 kind=ref 的资产（避免误绑 output/merged）

### 4.3 第三优先级（体验与生态）
1. 把 PyQt 的 voice 设置与 v2 voices/assets 打通（做“角色分组 + 情绪标签 + ref 多选”）
   - 已完成基础版：语音设置页默认读写 v2 voices；情绪管理页按角色分组管理 ref assets，并支持绑定 `ref_asset_ids`
2. bridge/client 全面迁移到 v2
   - bridge 直接对接 `/api/v2/synthesize`（拿到缓存收益、情绪选择收益、jobs/metrics 能力）
   - client 示例优先用 v2（保留 v1 示例但标注 legacy）
3. Prometheus 格式 metrics（你未来若接 Grafana/Prometheus 更方便）

## 5. 已确认的实现路线（基于你的选择）
你已经做出的选择如下，我会按这个路线给后续建议“落地化”：
1. 源码仓库与一键包：你当前以“本地维护、自用”为主
   - 这不影响我们把工程规范补齐；相反更建议加 git，因为你只有一个人时更容易“改着改着忘了怎么改的”
2. 长期维护方向：以 v2 为主（v1 只保留兼容）
   - 后续所有新能力只加在 v2；v1 不再加功能，只做必要的兼容修补
3. 存储底座：v2 资产索引/（未来可含 cache index）升级到 SQLite
   - 这将显著降低“资产数量上来后 JSON 不可控”的风险，并为后续 UI/批量预生成/统计打基础

### 5.1 结合路线的“最短可执行”落地清单（建议你按这个顺序做）
1. v2 先规范：错误码/状态码 + request_id + 日志字段（已落地）
2. SQLite 迁移 v2 assets（已落地）
   - 当前读写都走 SQLite；旧 `api_v2_assets.json` 仅用于兼容迁移（见 `scripts/migrate_v2_assets_json_to_sqlite.py`）
3. bridge/client 迁移到 v2（已落地）
   - bridge 已改为调用 v2 synth（保持 OpenAI 兼容输入输出不变）
4. 再拆 `core/api.py`（未做，仍建议尽快做，避免在巨型文件上继续加功能）
