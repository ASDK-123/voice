# P4-M2 生产指南：推理规范化逻辑统一（Normalization Unification）

最后更新：2026-02-10  
阶段目标：把文本规范化、voice/ref 解析、cache key 计算统一到单一实现，确保 UI/API 输出与缓存行为一致。  
前置阶段：M1 完成并稳定。

---

## 1. 里程碑定义

### 1.1 使命

1. 建立 `core/synthesis/*` 的规范化子层：
   - `request.py`
   - `normalize.py`
   - `resolve_voice.py`
   - `select_ref.py`
   - `cache_key.py`
2. API v2 synth 与 GUI worker 使用同一规范化入口（至少先在 cache key/ref 选择层统一）。
3. 建立 cache schema 版本管理策略（防污染）。

### 1.2 非目标

1. 暂不改变实际模型推理执行位置（M3 再统一 engine）。
2. 不改变 HTTP 协议。
3. 不优化性能，只保一致性与可维护性。

---

## 2. 关键不变量（必须写进测试）

不变量 A：同一请求输入，规范化结果唯一且稳定。  
不变量 B：`selected_ref_asset_id` 与 `variation_seed` 必须进入 cache key。  
不变量 C：CosyVoice3 prompt/instruct 规则在全系统只有一份实现。  
不变量 D：UI 与 API 对同请求生成同一 cache key（路径可不同，key 必须相同）。

---

## 3. 模块设计（落地接口）

## 3.1 `core/synthesis/request.py`

定义：
1. `SynthesisRequest`（原始输入）
2. `NormalizedRequest`（标准化后输入）

最小字段建议：
1. `text_raw/text_norm`
2. `voice_id/character/emotion`
3. `mode/prompt_text_final/instruct_text_final`
4. `selected_ref_asset_id/ref_selection_policy/variation_seed`
5. `speed/use_instruction`

## 3.2 `core/synthesis/normalize.py`

职责：
1. 文本 normalize（空白、换行、边界处理）
2. cv3 prompt/instruct 规范化
3. （可选）从旧 `clean_text` 迁移清洗逻辑

约束：
1. 不依赖 Flask
2. 不依赖 UI
3. 纯函数可测

## 3.3 `core/synthesis/resolve_voice.py`

职责：
1. `voice_id` 解析（`character#emotion`）
2. default fallback
3. 与 voices store 交互得到最终 voice dict

## 3.4 `core/synthesis/select_ref.py`

职责：
1. 复用 `emotion_selector` 的策略逻辑
2. 输出 `selected_ref_asset_id`
3. 支持 override policy

## 3.5 `core/synthesis/cache_key.py`

职责：
1. 组装 model_fp / voice_fp / request_hash
2. 统一 schema_version 管理入口
3. 对外提供 `build_cache_identity(normalized_request, runtime_config)` 一站式函数

---

## 4. 执行步骤（分阶段）

## Phase A：抽象冻结（0.5 天）

1. 盘点现有实现来源：
   - `core/api.py` 里的 synth 请求处理
   - `core/worker.py` 的 GUI 推理路径
   - `core/cache_keys.py`、`core/emotion_selector.py`
2. 输出“字段映射表”（API 输入字段 -> NormalizedRequest 字段）。
3. 明确 schema 版本策略：
   - 默认 `cv_cache_v1`
   - 变更 key 语义时 bump 到 v2

## Phase B：模块落地（1.5-2 天）

1. 新建 `core/synthesis/request.py` 与 `normalize.py`
2. 新建 `resolve_voice.py` 与 `select_ref.py`
3. 新建 `cache_key.py`
4. 在 API v2 synth 路径接入新模块（先替换“规范化 + key 计算”）
5. 在 `core/worker.py` 接入同模块（至少 key 计算与 ref 选择）

## Phase C：一致性验证（1 天）

1. 同请求样本在 API 与 worker 上生成 key 比对。
2. 验证 `random_per_text` 稳定性。
3. 验证 variation_seed 改变时 key 必变。

---

## 5. 测试计划（M2 核心）

### 5.1 单元测试（必须新增）

建议新增 `tests/test_synthesis_normalization.py`：
1. 文本 normalize case
2. cv3 prompt/instruct case
3. voice_id 解析与 fallback case
4. ref 选择策略 case
5. cache key 稳定性 case

### 5.2 组件测试

建议新增 `tests/test_synthesis_key_parity.py`：
1. 构造固定请求
2. 分别调用 API-side normalize pipeline 与 worker-side normalize pipeline
3. 断言 key 相同

### 5.3 回归测试

1. 运行 `scripts/p2_backend_acceptance_test.py`
2. 手工请求 `/api/v2/synthesize` 正常返回

---

## 6. 发布与回滚

### 6.1 发布策略

1. 先发布“只生成日志比对不生效”的暗桩版本（可选）
2. 再切换为正式使用新规范化模块

### 6.2 观察指标

1. cache hit 率异常波动（大幅下降需排查）
2. synth 失败率变化
3. 结果行为差异反馈

### 6.3 回滚策略

1. 恢复 API/worker 到原 key 计算路径
2. 若 key 语义变化已上线，保留新旧 schema 双读（短期）或直接回退版本

---

## 7. 风险与对策

风险 A：规范化统一后暴露历史“隐式行为”  
对策：为“历史行为差异”保留兼容开关（临时），并记录淘汰计划。

风险 B：cache 污染  
对策：严格执行 schema version 策略，必要时清理新 cache 分区。

风险 C：UI worker 接入不完全  
对策：先统一 key 与 ref 逻辑，再逐步统一全部请求结构。

---

## 8. 代码评审清单

1. 新模块是否纯函数优先、低依赖？
2. 是否存在重复 normalize 实现？
3. 是否把 ref 选择结果纳入 key？
4. 是否有 schema version 管控？
5. 是否补齐了测试样例？

---

## 9. 乔布斯理念对齐（M2）

1. 简洁：一套规则，不再多处重复。
2. 端到端：用户不再遇到“UI 和 API 同请求结果不同”的割裂体验。
3. 工艺：把隐式规则写成显式模块与测试，细节可验证。

---

## 10. M2 结束后的目标状态

1. 规范化逻辑成为独立层，可测试、可复用。
2. UI/API 缓存键一致性建立，跨表面命中成为可依赖能力。
3. M3 可以在低风险条件下进行推理引擎统一。

