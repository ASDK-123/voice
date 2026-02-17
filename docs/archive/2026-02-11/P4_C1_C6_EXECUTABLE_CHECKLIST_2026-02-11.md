# P4 C1-C6 可执行任务清单（严格收官版）

最后更新：2026-02-11  
适用范围：`core/`、`ui/`、`scripts/`、`tests/`  
目标：把当前 P4 改造从“部分完成”推进到“严格验收通过”。

---

## 全局执行规则（所有阶段通用）

1. 每个阶段单独开分支，单独合并，禁止跨阶段混改。  
2. 每个阶段必须经过 Gate：`Build -> Test -> Smoke -> Report`。  
3. 任何阶段失败，先回滚该阶段，不带病进入下一阶段。  
4. 禁止继续向 `core/api_legacy.py` 增加新业务逻辑，仅允许迁出/兼容薄层。

全局验收命令（每阶段结束都执行）：

```powershell
python -m py_compile core\api.py core\server\main.py core\server\app.py core\server\ctx.py
python -m unittest discover -s tests -p "test_*.py"
python scripts\p2_backend_acceptance_test.py
python scripts\m4_final_acceptance_test.py
python core\api.py --help
```

---

## C1：完成 M0 真闭环（运行链路去 legacy 驱动）

### C1 目标

1. 运行入口不再由 `runpy(core.api_legacy)` 驱动。  
2. `core/server/*` 成为真实装配层，不再是 legacy 包装层。  
3. `core/api.py` 保持薄入口并可运行。

### C1 涉及文件

1. `core/server/main.py`  
2. `core/server/app.py`  
3. `core/server/ctx.py`  
4. `core/api.py`  
5. `core/api_legacy.py`（仅兼容转发，不新增逻辑）

### C1 改动点清单

1. 在 `core/server/ctx.py` 定义真实 `AppContext`，包含：
   `app`、`logger`、`model_provider`、`voices_store`、`assets_store`、`cache`、`locks`、`metrics`、`job_queue`。  
2. `core/server/app.py` 实现真正的 `create_app(ctx)`：
   初始化 Flask、安装 middleware、注册 v1/v2 blueprint。  
3. `core/server/main.py` 改为：
   CLI 解析 -> `build_context()` -> `create_app(ctx)` -> `app.run(...)`。  
4. `core/api.py` 仅作为兼容入口，调用 `core.server.main.main()`。  
5. 运行时不再依赖 `from core import api_legacy` 或 `runpy.run_module("core.api_legacy")`。

### C1 执行命令

```powershell
rg -n "runpy\.run_module|api_legacy|_reexport_legacy_symbols|from core import api_legacy" core\api.py core\server\main.py core\server\app.py core\server\ctx.py
python -m py_compile core\api.py core\server\main.py core\server\app.py core\server\ctx.py
python core\api.py --help
```

### C1 验收门槛

1. `rg` 结果中，`core/server/main.py` 不再出现 `runpy.run_module("core.api_legacy")`。  
2. `core/server/ctx.py` 不再出现 `from core import api_legacy`。  
3. `core/api.py --help` 正常。  
4. 全局验收命令全部通过。

### C1 回滚门槛与动作

触发条件：启动失败、核心路由不可用、CLI 行为变化。  
回滚动作：恢复 `core/server/main.py`、`core/server/ctx.py`、`core/server/app.py`、`core/api.py` 到 C1 前版本。

---

## C2：完成 M1 真迁出（v2 misc 逻辑迁出 legacy）

### C2 目标

1. `v2 health/metrics/synthesize` 的业务实现迁出 `core/api_legacy.py`。  
2. `core/server/routes_v2_misc.py` 不只是转发壳，直接承载实现。  
3. `core/api_legacy.py` 对这些能力仅保留兼容入口（可选）。

### C2 涉及文件

1. `core/server/routes_v2_misc.py`  
2. `core/server/app.py`  
3. `core/server/ctx.py`  
4. `core/api_legacy.py`

### C2 改动点清单

1. 在 `routes_v2_misc.py` 完整实现：
   `GET /health`、`GET /api/v2/health`、`GET /metrics`、`GET /api/v2/metrics`、`POST /api/v2/synthesize`。  
2. `routes_v2_misc.py` 所有依赖从 `ctx` 注入，不读取全局变量。  
3. `app.py` 注册 misc blueprint。  
4. `api_legacy.py` 删除重复 v2 misc 主实现，避免双实现漂移。

### C2 执行命令

```powershell
rg -n "def v2_health|def v2_metrics|def v2_synthesize|v2_health_handler|v2_synthesize_handler" core\api_legacy.py core\server\routes_v2_misc.py
python -m py_compile core\server\routes_v2_misc.py core\server\app.py
python scripts\p2_backend_acceptance_test.py
```

### C2 验收门槛

1. `core/server/routes_v2_misc.py` 存在完整实现逻辑。  
2. `core/api_legacy.py` 不再承载 v2 misc 主实现。  
3. `/api/v2/health`、`/api/v2/metrics`、`/api/v2/synthesize` 行为不退化。  
4. 全局验收命令通过。

### C2 回滚门槛与动作

触发条件：v2 synth 错误率上升、响应 schema 漂移。  
回滚动作：恢复 `api_legacy.py` 的 v2 misc 实现与旧注册路径。

---

## C3：完成 M2 严格收敛（规范化逻辑单一化）

### C3 目标

1. 规范化逻辑只有一份实现来源（`core/synthesis/normalize.py` 等）。  
2. API 与 worker 使用同一规范化与 key 生成路径。  
3. 删除并行规范化代码。

### C3 涉及文件

1. `core/synthesis/normalize.py`  
2. `core/synthesis/cache_key.py`  
3. `core/synthesis/request.py`  
4. `core/api_legacy.py`  
5. `core/worker.py`  
6. `tests/test_synthesis_normalization.py`  
7. `tests/test_synthesis_key_parity.py`

### C3 改动点清单

1. 把 `clean_text`、mode normalize、instruction override 迁移或对齐到 `core/synthesis/normalize.py`。  
2. API 与 worker 统一调用 `build_cache_identity()`。  
3. 删除 `api_legacy.py` 中重复规范化逻辑。  
4. 若 key 语义变化，更新 schema version（例如 `cv_cache_v2 -> cv_cache_v3`）并记录理由。

### C3 执行命令

```powershell
rg -n "clean_text\(|_normalize_inference_mode|normalize_prompt_and_instruct|build_cache_identity" core\api_legacy.py core\worker.py core\synthesis\normalize.py core\synthesis\cache_key.py
python -m unittest tests\test_synthesis_normalization.py
python -m unittest tests\test_synthesis_key_parity.py
```

### C3 验收门槛

1. 同一输入，API 与 worker 的 `request_hash` 一致。  
2. ref 选择结果纳入 key（`selected_ref_asset_id`、`variation_seed` 改变时 key 改变）。  
3. 不再存在重复规范化实现。  
4. 全局验收命令通过。

### C3 回滚门槛与动作

触发条件：cache 命中率异常下降、同输入输出漂移。  
回滚动作：恢复旧 normalize 路径并保持新测试，定位后再重做。

---

## C4：完成 M3 严格收敛（一个引擎，多入口）

### C4 目标

1. v1/v2/worker 的推理执行链统一进入 `core/synthesis/engine.py`。  
2. 流式路径不再绕开 engine。  
3. route 层仅做协议适配。

### C4 涉及文件

1. `core/synthesis/engine.py`  
2. `core/api_legacy.py`（或迁移后的新 server 路由文件）  
3. `core/worker.py`  
4. `tests/test_synthesis_engine_cache.py`  
5. `tests/test_synthesis_engine_errors.py`

### C4 改动点清单

1. 将 v1 `/`、`/api/tts`、v2 synth 全部接入 `_v2_run_engine`/统一 engine 调用。  
2. 重构或封装流式分支，避免直接调用独立 `_inference` 主链。  
3. 清理 route 层 cache/inflight 逻辑，只保留引擎调用与响应封装。  
4. 修复已知运行时风险（例如未定义变量、死分支）。

### C4 执行命令

```powershell
rg -n "_inference\(|_v2_run_engine\(|run_synthesis\(|stream_response=True|STREAM_MODE" core\api_legacy.py core\worker.py core\synthesis\engine.py
python -m unittest tests\test_synthesis_engine_cache.py
python -m unittest tests\test_synthesis_engine_errors.py
python scripts\p2_backend_acceptance_test.py
```

### C4 验收门槛

1. v1/v2/worker 三入口执行主链一致。  
2. cache/inflight/model 调用逻辑在 engine 层唯一。  
3. 全局验收命令通过。

### C4 回滚门槛与动作

触发条件：流式退化、v1/v2 行为断裂。  
回滚动作：先仅回滚入口绑定，保留 engine 与测试，二次迭代再切换。

---

## C5：完成 M4 严格收口（配置单源制度化）

### C5 目标

1. 运行时 voices 只读写 `v2_voices_config_path`。  
2. legacy voices 只允许导入，不允许运行时写。  
3. UI 内嵌 API 与外部 API 同源可验证。

### C5 涉及文件

1. `core/storage/voices_file.py`  
2. `core/api_legacy.py` 或新 server voices 管理层  
3. `ui/api_page.py`  
4. `ui/main_window.py`  
5. `scripts/import_legacy_voice_config_to_v2.py`  
6. `scripts/m4_final_acceptance_test.py`  
7. `tests/test_voices_store_m4.py`

### C5 改动点清单

1. 继续强化 legacy 写保护日志与错误语义。  
2. UI 显示当前 voices 文件绝对路径与一致性状态。  
3. 启动时检测“v2 空 + legacy 有数据”只提示导入，不自动混用。  
4. 固化导入链路为唯一迁移入口。

### C5 执行命令

```powershell
python scripts\m4_final_acceptance_test.py
python -m unittest tests\test_voices_store_m4.py
rg -n "legacy voices file is read-only|v2_voices_config_path|import_legacy_voice_config_to_v2" core\storage\voices_file.py core\api_legacy.py ui\api_page.py ui\main_window.py scripts\import_legacy_voice_config_to_v2.py
```

### C5 验收门槛

1. voices CRUD 重启后一致。  
2. legacy 写入被阻断。  
3. UI/API 同源路径一致。  
4. 全局验收命令通过。

### C5 回滚门槛与动作

触发条件：voices 持久化异常、路径错配。  
回滚动作：保留 `VoicesFileStore`，仅回滚绑定路径，确保系统可运行。

---

## C6：最终交付与严格验收封版

### C6 目标

1. 形成可审计、可发布、可回滚的 P4 收官包。  
2. 明确“严格通过/不通过”结论和证据。

### C6 涉及文件

1. `P4_STRICT_FINAL_ACCEPTANCE_REPORT_2026-02-11.md`（新建）  
2. `PROJECT_OVERVIEW.md`（更新 P4 状态）  
3. `README.md`（更新启动与配置单源说明）

### C6 改动点清单

1. 记录每阶段 Gate 结果和命令输出摘要。  
2. 输出最终架构边界图（server/synthesis/storage）。  
3. 输出“遗留风险清单 + 下一轮计划”。  
4. 给出灰度与回滚 SOP。

### C6 执行命令

```powershell
python -m unittest discover -s tests -p "test_*.py"
python scripts\p2_backend_acceptance_test.py
python scripts\m4_final_acceptance_test.py
python core\api.py --help
```

### C6 验收门槛

1. 所有测试命令通过。  
2. 报告中每个阶段有证据链（文件、命令、结果）。  
3. 明确结论为“严格通过”才可封版。

### C6 回滚门槛与动作

触发条件：封版前仍有阻断项。  
动作：停止封版，回到对应阶段重开缺陷单。

---

## 建议执行节奏（工期）

1. C1：1-2 天  
2. C2：1 天  
3. C3：1-2 天  
4. C4：2-3 天  
5. C5：1 天  
6. C6：0.5 天

总计：6.5-9.5 天（含回归与修复缓冲）。

---

## 每日站会最小汇报模板

1. 今日阶段：C?  
2. 已完成任务编号：  
3. 阻塞点：  
4. 今日验收命令结果：  
5. 是否可进入下一阶段：是/否  

