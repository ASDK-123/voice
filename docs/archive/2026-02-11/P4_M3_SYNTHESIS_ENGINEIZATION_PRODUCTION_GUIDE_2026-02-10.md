# P4-M3 生产指南：推理执行引擎化（Engineization）

最后更新：2026-02-10  
阶段目标：把“生成 wav bytes + cache 读写 + 资产登记”的执行链路统一到 `core/synthesis/engine.py`，实现“一个引擎，多入口”。  
前置阶段：M2 完成并稳定。

---

## 1. 里程碑定义

### 1.1 使命

1. 新建统一执行引擎 `core/synthesis/engine.py`。
2. API v2 synth 与 v1 兼容路径改为调用统一引擎。
3. GUI worker 至少提供可切换的引擎调用通道（默认可先保旧路径，逐步迁移）。
4. 对外响应保持兼容。

### 1.2 非目标

1. 不改变模型本身。
2. 不强行删除旧 worker 推理实现（先并行验证）。
3. 不引入新框架或新服务。

---

## 2. 引擎契约（Contract）

建议标准接口：

```python
run_synthesis(
    req: NormalizedRequest,
    *,
    model_provider,
    voices_store,
    assets_store,
    cache_store,
    runtime_flags,
) -> SynthesisResult
```

`SynthesisResult` 最小字段：
1. `wav_bytes`
2. `cache_hit: bool`
3. `cache_key: str`
4. `selected_ref_asset_id: str`
5. `voice_id: str`
6. `meta: dict`

设计要求：
1. 引擎不依赖 Flask/PyQt。
2. 引擎可注入依赖，方便 test double。
3. 引擎异常统一转换为领域错误，再由 server 层映射到 HTTP error。

---

## 3. 执行流程（标准流水线）

1. 输入：`NormalizedRequest`
2. 计算 key：`cache_key.build_cache_identity(...)`
3. cache pre-check
4. inflight 去重
5. 若 miss：
   - 解析 voice
   - 选 ref
   - 调用模型推理
   - 写 cache
6. 输出 `SynthesisResult`
7. （可选）资产登记与响应格式转换由调用方决定（API/worker）

注意：
1. 引擎只负责生成与缓存，不处理 HTTP 响应封装。
2. “落盘到 data/assets/audio”与“返回 bytes”需要边界清晰，避免隐式副作用。

---

## 4. 任务拆解

## Phase A：契约定义与测试先行（0.5-1 天）

1. 定义 `SynthesisResult` dataclass。
2. 写“最小 fake model”测试：
   - 输入文本 -> 固定 wav bytes
3. 先写引擎行为测试再实现引擎。

## Phase B：引擎实现（1.5-2 天）

1. 实现 `engine.py`：
   - cache hit/miss
   - inflight
   - model 调用
   - meta 输出
2. 在 API v2 synth 中替换旧执行路径：
   - 接口层仍保持原请求/响应格式
3. 在 v1 路由中通过 compat adapter 调用同引擎。

## Phase C：worker 接入（1 天）

1. `core/worker.py` 增加引擎路径开关（例如 env 开关或配置开关）。
2. 先灰度在小范围启用 worker 引擎化。
3. 保留 fallback 到旧逻辑。

---

## 5. 测试计划

### 5.1 单元测试（引擎核心）

建议新增：
- `tests/test_synthesis_engine_cache.py`
- `tests/test_synthesis_engine_errors.py`

覆盖点：
1. cache hit/miss 分支
2. inflight 去重分支
3. model 异常 -> 领域错误
4. meta 字段完整性

### 5.2 组件测试（API 路径）

1. API v2 synth 调引擎 -> 返回 audio
2. v1 `/api/tts` 调引擎 -> 返回 audio
3. 错误场景响应仍符合 v2 error schema / v1兼容行为

### 5.3 回归测试

1. `scripts/p2_backend_acceptance_test.py`
2. bridge 端到端测试：
   - `POST /v1/audio/speech` 正常流式返回

---

## 6. 发布策略（分层灰度）

### 6.1 灰度方案

1. 第一步：仅 v2 synth 使用引擎，v1/worker 保持旧路径。
2. 第二步：v1 切换引擎。
3. 第三步：worker 切换引擎（可配置开关）。

### 6.2 指标观察

1. v2 synth 成功率
2. 首包时延
3. cache 命中率
4. bridge 超时率

### 6.3 回滚方案

1. 恢复 API 调用到旧执行函数。
2. 关闭 worker 引擎开关。
3. 保留引擎模块但不走主路径，便于后续修复。

---

## 7. 风险与对策

风险 A：引擎边界不清导致职责回流  
对策：严格禁止引擎引用 Flask 对象与 request 上下文。

风险 B：v1/v2 兼容参数映射遗漏  
对策：在 `core/server/compat.py` 统一参数映射，禁止在路由里散写。

风险 C：worker 接入引擎导致 UI 卡顿  
对策：保证 worker 线程内调用，且回调只传结果不传重对象。

---

## 8. 评审清单

1. 引擎是否真正可复用（无框架耦合）？
2. 是否有重复 cache 流程残留在路由层？
3. v1/v2 是否都走同一执行入口？
4. 异常分类是否清晰（领域错误 vs HTTP 错误）？
5. 灰度开关与回滚路径是否存在？

---

## 9. 乔布斯理念对齐（M3）

1. 一体化：同一核心能力服务多个入口，不再“每个入口一套实现”。
2. 简洁：核心路径收敛成单点，后续优化只改一处。
3. 体验一致：用户不管从 UI、API、Bridge 进入，结果与错误语义趋于一致。

---

## 10. M3 结束后的目标状态

1. 推理执行链路可被清晰描述、清晰测试、清晰回滚。
2. 后续性能优化（batch、stream、cache 策略）可在 engine 层定点演进。
3. 路由层从“执行者”退化为“协议适配器”，可维护性显著提升。

