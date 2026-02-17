# P4 后端架构重构方案（长期可维护）：拆分 api.py / 收敛规范化逻辑 / 配置单一化

最后更新：2026-02-10  
适用范围：`core/`（Flask API v1+v2、推理、缓存、资产、jobs）+ 少量 `ui/` 对齐（仅作为“需要调整点”说明）  
目标：持续产品化迭代、可测试、可演进、减少改动半径

> 约束：本方案是“可执行的重构路线图”，按阶段推进，**每阶段可独立验收、可回退**，并尽量做到“行为不变的机械重构”优先。

---

**执行指南索引（新增）**

1. 总控手册：`P4_BACKEND_REFACTOR_EXECUTION_SYSTEM_2026-02-10.md`
2. M0 指南：`P4_M0_STRUCTURAL_ASSEMBLY_PRODUCTION_GUIDE_2026-02-10.md`
3. M1 指南：`P4_M1_V2_MISC_ROUTE_EXTRACTION_PRODUCTION_GUIDE_2026-02-10.md`
4. M2 指南：`P4_M2_SYNTHESIS_NORM_UNIFICATION_PRODUCTION_GUIDE_2026-02-10.md`
5. M3 指南：`P4_M3_SYNTHESIS_ENGINEIZATION_PRODUCTION_GUIDE_2026-02-10.md`
6. M4 指南：`P4_M4_CONFIG_SINGLE_SOURCE_PRODUCTION_GUIDE_2026-02-10.md`

---

**0. 一句话结论**

当前项目能跑、功能闭环也在形成，但长期维护的最大风险是 `core/api.py` 巨石化 + UI/API/直推理三条链路的“规范化逻辑”分叉。P4 的核心是把推理与规范化抽成可复用的“领域层（synthesis）”，把 Flask 变成薄薄的“传输层（server）”，并把 voices 配置彻底收敛到 v2 结构，形成单一事实源。

---

**1. 现状问题（为什么要做 P4）**

1. `core/api.py` 既是入口又是实现：包含 v1、v2 state、assets/jobs/cache/merge/metrics、推理逻辑、并发锁、CLI 参数解析，导致改动半径大、回归成本高。
2. “规范化逻辑”存在多处来源：文本清洗/normalize、CosyVoice3 prompt/instruct 处理、ref 选择策略、cache key 规则等在 `core/api.py`、`core/worker.py`、`core/cache_keys.py`、`core/emotion_selector.py` 分散，容易行为漂移。
3. 多推理路径带来一致性成本：GUI 直推理、GUI 走 v2、外部 API v1/v2 同时存在，参数默认值、错误处理、输出落盘与资产登记容易不一致。
4. 配置体系仍处于过渡态：legacy voices（`config/config.json` 等）与 v2 voices（`app_config.json:v2_voices_config_path` 指向的 JSON）并存，用户很容易出现“UI/外部 API 各读各的”的错配。
5. 测试粒度偏粗：目前已有 `scripts/p2_backend_acceptance_test.py`（很好），但缺少可复用的“推理规范化/缓存键/选择策略”的单元测试底座，导致改规范化逻辑时风险高。

---

**2. 目标与非目标**

目标（必须达到）：
1. `core/api.py` 变“装配层”：只做 create_app/注册路由/注入依赖/启动，业务逻辑迁出。
2. 规范化逻辑唯一来源：把“文本规范化、voice 解析、ref 选择、cache key 计算、推理参数归一化”收敛到 `core/synthesis/*`，UI worker 与 API v2 synth 复用。
3. 配置单一化：v2 voices（`voice_id=角色#情绪` + `ref_asset_ids` + `selection_policy`）成为唯一事实源；legacy 只保留“一次性导入”。
4. 保持兼容：现有 v1/v2 URL、请求字段、返回类型尽量不破坏；必要变更通过“新字段可选 + 旧字段兼容”演进。
5. 可测试：推理规范化与 cache key 可单测；API v2 routes 可用 Flask test_client 做集成测。

非目标（本阶段不做，避免范围爆炸）：
1. 不替换 Flask/FastAPI，不引入新服务进程模型。
2. 不做“模型层大改/算法改”，只做工程分层与一致性收敛。
3. 不强制立刻删除 GUI 直推理路径；允许保留 fallback，但必须复用同一规范化层。

---

**3. 目标形态（Target Architecture）**

把 `core/` 明确分为三层：
1. `core/server/*`：HTTP 传输层（Flask 组装、blueprints、HTTP 错误/中间件）
2. `core/synthesis/*`：领域层（规范化、voice 解析、ref 选择、cache key、推理执行接口）
3. `core/storage/*`：存储层（assets sqlite、cache、文件落盘、可选 jobs 持久化）

建议的目录结构（最终形态，逐步迁移到此）：

```text
core/
  api.py                         兼容入口（保留路径），内部只做：from core.server.main import main
  server/
    main.py                      CLI 解析 + create_app + app.run（等价于现在 core/api.py 的入口部分）
    app.py                       create_app(ctx)；注册 v1/v2 blueprint；安装 middleware
    ctx.py                       AppContext（依赖注入容器：model/config/cache/assets/jobs/locks）
    routes_v1.py                 v1 兼容路由（/ /api/tts /speakers ...）
    routes_v2_misc.py            v2 health/metrics/synthesize（或拆分为多个）
    compat.py                    v1/v2 参数兼容适配（例如 speaker vs voice_id）
  synthesis/
    request.py                   SynthesisRequest/NormalizedRequest 数据结构（dataclass）
    normalize.py                 text/prompt/instruct 规范化（唯一来源）
    resolve_voice.py             voice_id 解析、emotion fallback、从 voices store 取 voice dict
    select_ref.py                ref_asset_ids 选择策略（复用 emotion_selector 逻辑）
    cache_key.py                 组装 model_fp/voice_fp/request_hash（封装 cache_keys）
    engine.py                    run_synthesis(...)（输入 NormalizedRequest，输出 wav_bytes + meta）
  storage/
    cache.py                     CacheManager 封装（可直接复用 core/cache_manager.py）
    assets.py                    AssetsSqliteStore 封装（复用 core/v2/assets_sqlite.py）
    voices_file.py               v2 voices JSON 的读写与原子保存（替代 CharacterConfig 巨石内嵌）
  v2/
    http.py errors.py request_id.py logging.py assets_sqlite.py legacy_import.py 维持现有（偏基础设施）
  worker.py utils.py cache_keys.py cache_manager.py emotion_selector.py models.py 逐步被 synthesis/storage 吸收或变薄
```

关键点：
1. `core/server/*` 不包含任何“推理细节”，只关心 HTTP 与依赖注入。
2. `core/synthesis/*` 不依赖 Flask/PyQt，只依赖 Python 标准库与可注入的 store/model 接口，方便单测。
3. `core/storage/*` 把“文件 + SQLite + cache”作为明确边界，避免散落在 `api.py` 的全局变量里。

---

**4. api.py 拆边界（拆什么、怎么拆、验收点）**

本项目已完成第一步：把 v2 的 assets/voices/jobs/merge 路由拆到 `core/api_v2_routes.py`（Blueprint）。P4 要完成的是“把剩余 glue 与推理也拆出去”，并把 `core/api.py` 变成稳定入口。

建议拆分顺序（从最安全到最核心）：

1. 把“v2 state（路径、锁、store、cache、metrics、队列）”从 `core/api.py` 抽到 `core/server/ctx.py`
2. 把 v2 的 `health/metrics/synthesize` 从 `core/api.py` 移到 v2 Blueprint 或 v2 routes 文件
3. 把推理执行（含 ref 选择、prompt/instruct 处理、cache 读写、保存资产）从 `core/api.py` 移到 `core/synthesis/engine.py`
4. 把 v1 兼容端点从 `core/api.py` 移到 `core/server/routes_v1.py`，并通过 compat adapter 调用 synthesis

每一步验收点（必须可跑）：
1. `StartAPIServer.bat` 启动后：`GET /api/v2/health`、`GET /api/v2/voices`、`GET /api/v2/assets/audio` 正常。
2. `POST /api/v2/synthesize` 输出音频与重构前一致（至少：可播放、长度合理、cache hit/miss 逻辑不退化）。
3. v1 兼容端点 `/`、`/api/tts`、`/speakers` 行为不变。

回退策略：
1. 保留 `core/api.py` 原实现为 `core/api_legacy.py`（仅在重构期间短期存在），新入口失败时可快速切回。
2. 任何会影响 cache key 的改动，都必须通过 bump `V2_CACHE_SCHEMA_VERSION`（例如从 `cv_cache_v1` -> `cv_cache_v2`）隔离。

---

**5. 收敛“规范化逻辑”（唯一来源与不变量）**

P4 的关键是“规范化逻辑只写一份”。你现在已经有不错的基础模块：
1. `core/cache_keys.py`：text normalize、cv3 prompt/instruct normalize、fingerprint/hash
2. `core/emotion_selector.py`：ref 选择策略与 default fallback
3. `core/cache_manager.py`：cache + inflight 去重 + sqlite index

但它们在 API/worker 的调用方式仍容易分叉。建议明确 3 个不变量：

1. 不变量 A：**推理输入的规范化结果必须与 cache key 计算使用的规范化结果一致**
2. 不变量 B：**ref 选择结果必须进入 cache key**（否则不同 ref 可能复用同一个 cache，输出错配）
3. 不变量 C：**CosyVoice3 的 prompt/instruct 格式化规则只有一份**（避免 UI 与 API 对同一 voice 得到不同输出）

建议落地方式（实现时对应文件）：

1. `core/synthesis/request.py`
   - `SynthesisRequest`：来自 HTTP/UI 的原始请求
   - `NormalizedRequest`：规范化后的请求（text_norm、prompt_text_final、instruct_text_final、selected_ref_asset_id、use_instruction、variation_seed、voice_id 等）

2. `core/synthesis/normalize.py`
   - `normalize_text(text) -> text_norm`
   - `normalize_cv3_prompt(prompt_text) -> prompt_text_final`
   - `normalize_cv3_instruct(instruct_text) -> instruct_text_final`
   - `clean_text_for_inference(text) -> text_clean`（如需要保留现有 `clean_text` 行为，应迁移到这里并文档化规则）

3. `core/synthesis/resolve_voice.py`
   - `parse_voice_id(voice_id) -> (character, emotion)`
   - `resolve_voice(character, emotion, voices_store) -> voice_dict`（含 default fallback）

4. `core/synthesis/select_ref.py`
   - `pick_ref_asset_id(voice_dict, text_norm, variation_seed, override_policy) -> asset_id`（直接复用 `core/emotion_selector.pick_ref_asset_id` 的算法）

5. `core/synthesis/cache_key.py`
   - `model_fp = model_fingerprint(model_dir, fp16, load_trt, load_vllm)`
   - `voice_fp = voice_fingerprint(... selected_ref_asset_id, variation_seed ...)`
   - `req_hash = request_hash(schema_version, model_fp, voice_fp, text_norm, speed, use_instruction, instruction_text, part_index)`

6. `core/synthesis/engine.py`
   - 输入：`NormalizedRequest` + 可注入依赖（model getter、assets store、cache、save_audio_bytes）
   - 输出：`wav_bytes` + `meta`（至少含 cache_hit、cache_key、selected_ref_asset_id、voice_id）

验收点（对“收敛规范化逻辑”最关键）：
1. 同一文本同一 voice 在 UI 直推理与 API v2 synth 的 cache key 完全一致（允许输出路径不同，但缓存键一致）。
2. 选择策略 `random_per_text` 在 UI 与 API 上稳定一致。
3. 改动规范化逻辑时必须 bump schema_version，避免旧缓存污染新逻辑。

---

**6. 收敛推理路径（从“三条链路”到“一个引擎 + 多入口”）**

建议采用“一个引擎，多入口”的收敛策略：

1. 短期（兼容期）：保留三条入口
   - API v2 synth -> 调用 `core/synthesis/engine.py`
   - v1 兼容 -> 适配参数后调用 `core/synthesis/engine.py`
   - GUI 直推理 worker -> 调用 `core/synthesis/engine.py`（或至少复用 normalize/cache_key/select_ref）

2. 中期（产品化期）：UI 默认走 v2 jobs/synthesize
   - 把 GUI 直推理降级为 fallback（API 不可用或用户显式选择“离线模式”）
   - 这样缓存/资产/队列/合并行为统一在服务端，UI 只做编排与展示

3. 长期（工业化期）：推理只存在服务端路径
   - worker 变成“HTTP client + job poller”
   - UI 不再直接 import cosyvoice 推理依赖，减少桌面端复杂度

每阶段可验收指标：
1. 短期：cache key 一致性、输出一致性、错误码一致性（v2 结构化错误）
2. 中期：任务页批量生成完全走 `/api/v2/jobs`，并能显示 cache hit/miss
3. 长期：UI 安装体积与依赖显著下降（可选目标）

---

**7. 配置单一化路线（从 legacy -> v2 事实源）**

你已经在 P2/P3 文档中明确了“v2 voices 为唯一事实源”，P4 需要把这件事工程化为“不可误用的系统”。

建议明确 3 类配置与其职责：

1. `app_config.json`（用户偏好与 UI 状态）
   - 主题、输出目录、模型路径、API host/port/key、`v2_voices_config_path`、MRU/收藏等
   - 不再承载“业务 voices 内容”

2. v2 voices 文件（业务事实源）
   - 由 `app_config.json:v2_voices_config_path` 指向
   - 默认建议固定为 `config/super_agent.json` 或 `config/voices_v2.json` 之一
   - Schema 以 v2 为准：`name/character/emotion/mode/prompt_text/instruct_text/color/selection_policy/ref_asset_ids/prompt_audio_asset_id(optional)/prompt_audio(path optional)`

3. v2 assets（参考音频资产事实源）
   - SQLite：`data/api_v2_assets.sqlite3`
   - 文件：`data/assets/audio/*`

推进步骤（推荐）：

1. 明确弃用 legacy voices 的写路径
   - UI 仍可读取 legacy（用于导入提示），但不再把 legacy 当运行时来源
   - 所有运行时操作（绑定 ref、compile、synthesize）只以 v2 voices 为准

2. 将 `--config` 参数语义固定为“v2 voices 路径”
   - 允许继续兼容旧文件，但内部需要做一次 migrate/normalize 到 v2 结构

3. 把 `CharacterConfig` 替换为“v2 voices store”（可持久化、线程安全、接口完整）
   - 必须实现：`get_voice/get_all/upsert/delete/save/reload`
   - UI 内嵌 server 注入的 config_manager 也必须满足此接口（否则 v2 voices CRUD 会炸）

验收点：
1. 外部 `StartAPIServer.bat` 与 UI 内嵌 server 必定读取同一份 v2 voices（路径可见、可打印、可在 UI 顶部展示）。
2. legacy voices 的存在不会影响运行时（只会触发“建议导入”提示）。

---

**8. 测试与验收（保证可持续演进）**

建议把测试分成三层，每层都有可自动跑的最小集合：

1. 单元测试（纯函数/纯逻辑）
   - `core/synthesis/normalize.py`：normalize 规则、cv3 prompt/instruct 规则
   - `core/synthesis/select_ref.py`：策略 `fixed/random_per_text/random_per_request` 的可重复性
   - `core/synthesis/cache_key.py`：同输入同 key；variation_seed 改变 key；selected_ref_asset_id 改变 key

2. 组件测试（不跑真实模型）
   - `core/server/routes_v2_misc.py` 的 synth 路径可注入 dummy model（返回固定 wav bytes），验证 cache hit/miss、assets 落盘、错误码结构
   - 复用你已有的 `scripts/p2_backend_acceptance_test.py` 方式（Flask test_client + temp data_root）

3. 冒烟测试（真实环境）
   - `StartAPIServer.bat` 启动后跑一个最短请求（curl/httpx）
   - `bridge.py` 对 `/api/v2/synthesize` 的流式转发仍可工作

最低验收门槛（每次重构都必须过）：
1. `scripts/p2_backend_acceptance_test.py` 通过
2. `/api/v2/health`、`/api/v2/voices`、`/api/v2/assets/audio`、`/api/v2/synthesize` 可用
3. v1 `/speakers`、`/api/tts` 可用

---

**9. 里程碑计划（可执行拆分）**

Milestone M0（0.5-1 天）：只做结构化装配，不动业务
1. 新增 `core/server/app.py` 与 `core/server/ctx.py`（仅搬运现有全局 state 的组装）
2. `core/api.py` 改为 thin wrapper（或新增 `core/server/main.py` 并由 `core/api.py` 调用）
验收：服务行为完全一致

Milestone M1（1-2 天）：v2 misc 路由迁出
1. `v2 health/metrics/synthesize` 从 `core/api.py` 移出到 `core/server/routes_v2_misc.py`
2. `core/api_v2_routes.py` 继续作为 v2 主 Blueprint（assets/voices/jobs/merge）
验收：`rg "^@app.route" core/api.py` 只剩 v1 与少量 glue

Milestone M2（1-3 天）：引入 synthesis 领域层（先不改推理实现）
1. 落地 `core/synthesis/normalize.py`、`select_ref.py`、`cache_key.py`
2. 让 API v2 synth 与 UI worker 同时调用这些模块（至少 cache key 与 ref 选择一致）
验收：同输入同 cache key，UI/API 互相可命中缓存

Milestone M3（2-4 天）：推理执行引擎化
1. 落地 `core/synthesis/engine.py`，把“生成 wav bytes”与“缓存读写/落盘”统一入口
2. v1/v2 synth 都调用 engine
验收：删除/修改 v1 参数适配不影响 v2 行为；错误码 v2 不变

Milestone M4（持续）：配置单一化与 legacy 收口
1. 把 voices 的读写抽成 `core/storage/voices_file.py`（原子写、reload、schema normalize）
2. legacy import 作为唯一入口（你已具备 `core/v2/legacy_import.py`）
验收：任何新功能都只读写 v2 voices，不再写 legacy voices

---

**10. 可能踩坑与对策（写在前面，少走弯路）**

1. 规范化逻辑调整导致缓存污染
   - 对策：任何影响 key 的改动必须 bump `cv_cache_v1`；并在响应 meta 中带 `schema_version`

2. UI 内嵌 server 的 CharacterConfig 接口不完整
   - 对策：server 注入的 voices store 必须实现完整 CRUD + save；不要直接读写 UI 内存列表

3. Windows 路径规范化导致“仍被引用”的误判
   - 对策：在引用计算与资产清理时统一做 `normcase + abspath`（你已在 v2 routes 中做过类似处理）

4. 并发锁粒度过粗影响吞吐
   - 对策：保持“模型调用锁”与“assets/index 锁”分离；jobs 队列单独锁；不要把整个请求都锁住

5. 重构阶段回归难
   - 对策：先做 M0/M1（纯搬运），把改动压到结构层；等测试底座建立后再动 engine

---

**11. 与现有 P1/P2/P3 的关系（避免重复建设）**

1. P1 已完成“v2 routes 拆分 + cache sqlite index”，P4 在其基础上继续把 `api.py` 变薄，并把推理从 server 层剥离。
2. P2 的“未引用清理 + 一键闭环向导”已经在 UI/后端形成闭环，P4 不改其业务，只保证其依赖的 voices/assets/cache 边界更清晰。
3. P3 的“右侧 Sheet/组件化”会受益于 P4 的配置单一化：UI 只需依赖 v2 voices/assets，不必处理 legacy 分叉。

---

**12. 最终交付标准（你可以用它判断 P4 是否完成）**

1. `core/api.py` 不再包含 v2 state 与推理实现，读起来像一个 100-300 行的入口文件。
2. 推理规范化与 cache key 计算只有一条代码路径（`core/synthesis/*`），UI/API 都复用。
3. voices 的事实源唯一且可见（UI 顶部可展示路径，API 启动日志可打印路径），用户不再困惑“到底用哪份配置”。
4. 最小测试集可稳定跑通，并能在不加载真实模型的情况下验证 v2 routes 的关键行为（cache、assets、refs、cleanup、jobs）。
