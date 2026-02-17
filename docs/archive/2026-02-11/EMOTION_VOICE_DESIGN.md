```markdown
# 设计文档：角色分组的多情绪参考音频管理（Emotion Voices v1）

状态：Draft（评审用）  
最后更新：2026-02-09  
范围：GUI（桌面端）+ API v2（assets/voices/synthesize/jobs）+（可选）指令控制增强  
前置设计：`CACHE_QUEUE_DESIGN.md`（音频结果缓存与 jobs 队列）

---

## 1. 背景与动机

当前项目对“同一角色的不同情绪参考音频”的管理方式不够结构化：
- 参考音频通常是单个 `prompt_audio`，无法自然表达“同一角色多个情绪、多条参考音频”的关系。
- 使用时如果想切情绪，需要手工换 voice 或换 prompt 文件，效率低。

本设计引入“角色分组 + 情绪标签 + 多参考音频（随机/可控选择）”的管理模型，并与现有 v2 的 `assets/voices/compile/synthesize/jobs` 对齐。

---

## 2. 目标与非目标

### 2.1 目标（必须满足）

1. 角色分组  
按“角色名”分组管理参考音频与音色配置；一个角色下有多个情绪。

2. 默认 8 种常见情绪 + 可扩展  
内置 8 个常见情绪标签；允许用户上传参考音频并添加任意自定义情绪标签。

3. 同情绪多参考音频（随机化）  
同一角色同一情绪可以有多条参考音频；合成时系统可自动选择（随机/可控），让生成更有多样性。

4. 情绪缺省回退  
若请求情绪没有可用参考音频，自动回退到该角色的默认参考音频（default/neutral）。

5. 指令控制可选增强  
默认优先走“参考音色缓存（更稳、更快）”；当用户显式提供指令时才启用指令控制作为增强。

6. 与音频结果缓存兼容  
在 `CACHE_QUEUE_DESIGN.md` 的“相同输入应命中同一份音频缓存”规则下，随机化必须可解释且可控，不能造成缓存错命中。

### 2.2 非目标（v1 不做）

1. 直接注入“情绪 embedding 向量”到生成过程  
当前项目的 `AutoModel`/`inference_*` API 并未暴露通用 embedding 注入能力。本设计只使用现有能力：`prompt_audio/prompt_text` 与 `add_zero_shot_spk` 相关接口。

2. 复杂的自然语言情绪理解（LLM 解析）  
v1 仅做“情绪标签匹配 + 同义词映射”的轻量解析（可选）。

---

## 3. 核心概念（零基础解释）

- 角色（Character）：比如 “Tom / 胡桃 / 旁白”。
- 情绪（Emotion）：比如 “happy / sad / angry / default”。
- 参考音频（Reference Audio）：用于“让模型学到该角色在该情绪下怎么说话”的样本。
- 多参考音频随机化：同一情绪有多条参考音频时，系统挑一条来做这次合成的参考，以获得更多变化。
- 预编译（Compile）：把“参考音频 + 参考文本”的特征提前登记到模型里（`spk_id`），减少后续首次推理延迟。
- 音频结果缓存（Audio Cache）：把“最终生成的 wav 成品”缓存起来，重复输入秒回（受 500MB 上限约束）。

---

## 4. 默认情绪标签（8 个）

默认情绪集合（建议，命名可调整为中文/英文；对外建议稳定英文 key）：

1. `default`（默认/中性）
2. `happy`（开心）
3. `sad`（悲伤）
4. `angry`（愤怒）
5. `fear`（害怕）
6. `surprise`（惊讶）
7. `disgust`（厌恶）
8. `calm`（平静）

扩展：允许用户新增任意 `emotion_tag`（字符串），例如 `shy`、`excited`、`tired` 等。

---

## 5. 数据模型（建议字段，兼容现有 v2）

本项目 v2 已有：
- 音频 assets：`/api/v2/assets/audio`
- voices：`/api/v2/voices`（目前 voice 只有单个 `prompt_audio`）

为满足“同情绪多参考音频”，建议新增/扩展以下字段（即使暂时不实现，也应先把字段定义写清楚）：

### 5.1 Reference Audio 元数据（存放在 v2 assets 索引里）

给每条参考音频增加以下元信息（随上传一起提交）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `character` | string | 是 | 角色组名，例如 `Tom` |
| `language` | string | 是 | 语言，例如 `zh`/`en`（UI 下拉选择） |
| `emotion` | string | 是 | 情绪标签，例如 `happy`（UI 输入） |
| `note` | string | 否 | 备注（可选） |

资产索引里建议保留 `sha1/size/created_at`（当前 v2 已有）。

### 5.2 Emotion Voice（一个角色 + 一个情绪 的配置实体）

Emotion Voice 是“可被选择用于合成”的配置单元。推荐把 `voice_id` 设计为稳定、可读、唯一：

`voice_id = "{character}#{emotion}"`

例如：
- `Tom#default`
- `Tom#happy`
- `Tom#sad`

Emotion Voice 字段建议：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | voice_id（现有字段） |
| `character` | string | 是 | 角色组名（新增） |
| `emotion` | string | 是 | 情绪标签（新增） |
| `language` | string | 是 | 语言（新增） |
| `ref_asset_ids` | array[string] | 是 | 同情绪参考音频资产列表（新增，核心） |
| `prompt_text` | string | 是 | 参考文本（对于零样本复制/参考音色必须） |
| `mode` | string | 是 | 默认推理模式（现有字段） |
| `instruct_text` | string | 否 | 指令模板（指令增强用） |
| `fallback_voice_id` | string | 否 | 回退 voice（默认指向 `Character#default`） |
| `selection_policy` | string | 否 | 参考音频选择策略（见下节） |
| `emotion_aliases` | array[string] | 否 | 同义词映射（可选） |

说明：
- `ref_asset_ids` 使得“同情绪多参考音频”成为一等公民。
- `prompt_text` 如果不同参考音频对应不同参考文本，v1 可先约束“同 Emotion Voice 内 prompt_text 统一”。v2 以后再扩展为每条 ref 独立的 prompt_text。

---

## 6. 参考音频选择策略（随机化与缓存不冲突的关键）

你提出“同一情绪多参考音频随机选择，让语音更多样”，但你同时也希望“相同输入命中同一份音频缓存”。

这两者天然冲突：完全随机会导致“相同输入每次可能不同”，音频结果缓存就会变得不可预测或失效。

因此设计必须明确：随机化发生在什么层级，如何控制它对缓存的影响。

### 6.1 三种策略（建议都支持，默认选第 1 种）

1. `random_per_text`（默认推荐）
- 用确定性方法从 `ref_asset_ids` 里挑一条：  
  `pick_index = hash(character, emotion, text_normalized) % N`
- 结果：同一个文本永远挑同一条参考音频（可稳定命中音频结果缓存），不同文本会分散到不同参考音频（仍然有“多样性”）。
- 这是兼顾“多样性”和“缓存命中”的最佳默认。

2. `random_per_request`（真随机）
- 每次请求都随机挑一条参考音频。
- 结果：同一文本多次请求会得到不同声音，但音频结果缓存命中率会显著下降。
- 适合在 GUI “重Roll / 生成新版本”场景使用，而不适合默认 API 行为。

3. `fixed`（固定）
- 指定一个 `ref_asset_id` 作为固定参考音频（用于稳定播报场景）。

### 6.2 “重Roll/多版本”怎么做（兼容缓存）

当用户希望“同一文本也能变”，应显式给一个 `variation_seed`（或 `reroll` 次数）。  
缓存键（`request_hash`）必须包含 `variation_seed`，这样：
- `variation_seed=0`：默认版本（稳定命中）
- `variation_seed=1/2/3`：新版本（缓存独立，不会覆盖默认）

在 `random_per_text` 下，`variation_seed` 也参与 pick 计算：
`pick_index = hash(character, emotion, text_normalized, variation_seed) % N`

---

## 7. 情绪缺省回退规则

当请求 `character=X, emotion=E` 时：

1. 若存在 `X#E` 且其 `ref_asset_ids` 非空：使用它  
2. 否则回退到 `X#default`  
3. 若 `X#default` 也不存在：返回 `voice_not_found`（或提示需要先创建默认音色）

说明：这是你“没有对应情绪就用默认参考音频”的明确实现规则。

---

## 8. 预编译（Compile）策略（多情绪、多参考音频）

### 8.1 编译对象

对一个 Emotion Voice（例如 `Tom#happy`）而言，它可能有多条 `ref_asset_ids`。编译建议两种模式：

1. `compile_one`：只编译“默认选择的那条参考音频”（按 selection_policy + variation_seed=0 计算）
- 启动快，适合先做 PoC

2. `compile_all`：编译该情绪下所有参考音频
- 更充分利用缓存，加速更稳定
- 编译时间更长，但你说“参考音频不频繁更新”，适合离线一次性做

### 8.2 spk_id 命名建议（便于区分）

建议 spk_id 包含：
- voice_id（`Tom#happy`）
- ref_asset_id（或其短 hash）

例如：
`spk_id = "Tom#happy@ref_abcd1234"`

这样同一情绪多参考音频的缓存不会互相覆盖。

---

## 9. 与“指令控制增强”的组合策略（可选）

你选择“指令控制可选：优先参考音色缓存，指令作为增强”。建议策略如下：

1. 默认合成（无指令）
- 使用 `mode=参考音色` 或 `零样本复制 + spk_cache`  
- 目标：稳定、快、可预编译、可缓存

2. 指令增强（有指令）
- 仍然先根据 emotion 选择参考音频（按策略挑 ref）
- 再进入 `指令控制` 推理（例如 `instruct_text` = 用户指令或模板 + 用户指令）
- 预期：表达更灵活，但 compile/spk_cache 对该路径不一定显著加速（取决于模型接口），主要依赖音频结果缓存提升重复输入性能

对外说明（面向用户）：
- 参考音色：更稳定、更快  
- 指令控制：更灵活、但可能更慢（除非命中结果缓存）

---

## 10. API v2 设计（不改代码版本的目标接口合同）

本设计基于已有 v2 端点，建议“最少新增、最多复用”。

### 10.1 上传参考音频（复用 assets 上传）

在上传接口上扩展表单字段：
- `language`（下拉）
- `emotion`（文本）
- `character`（可选：若 UI 已在角色分组页内，可由服务端推导）

返回资产 meta 中要能追溯这些字段。

### 10.2 Emotion Voice 管理（复用 voices CRUD）

扩展 voice schema 支持：
- `character`, `emotion`, `language`
- `ref_asset_ids`（数组）
- `selection_policy`
- `fallback_voice_id`

### 10.3 合成接口（复用 synthesize）

支持两种调用方式：

1. 直接指定 voice：
```json
{
  "text": "...",
  "voice_id": "Tom#happy",
  "speed": 1.0,
  "variation_seed": 0,
  "selection_policy": "random_per_text",
  "use_instruction": false,
  "instruction": ""
}
```

2. 指定角色与情绪（由服务端解析到 voice_id）：
```json
{
  "text": "...",
  "character": "Tom",
  "emotion": "happy",
  "speed": 1.0
}
```

并明确回退规则：emotion 不存在 -> default。

### 10.4 与音频结果缓存的 key（必须包含）

为了与 `CACHE_QUEUE_DESIGN.md` 一致，request_hash 至少应包含：
- `model_fingerprint`
- `voice_fingerprint`（必须包含 selected_ref_asset_id，而不是仅 emotion）
- `text_normalized`
- `speed`
- `variation_seed`
- `use_instruction` + `instruction`（若启用指令）

---

## 11. GUI 交互设计（与图一致）

你提供的截图包含上传参考音频的最小 UI：
- 语言（下拉）
- 情感标签（文本输入）
- 音频文件（选择文件 + 上传）

建议 GUI 页面结构：

1. 角色列表（Character）
- 左侧选择角色（或创建角色）
- 显示该角色下所有情绪与每个情绪的参考音频数量

2. 情绪分组视图（Emotion）
- 默认 8 个情绪固定展示（允许隐藏无数据的）
- 自定义情绪以标签形式追加

3. 参考音频管理（Reference Audios）
- 每个情绪下可上传多条参考音频
- 支持试听、删除、设置权重（可后置）

4. 生成时的选择
- 角色下拉 + 情绪下拉
- 随机化开关：
  - 默认：`random_per_text`
  - 可选：`random_per_request`（重Roll）
  - 可选：`fixed`
- “生成新版本”按钮：实际上是 `variation_seed += 1`

---

## 12. 风险与约束（必须写在文档里）

1. 完全随机与结果缓存冲突  
默认应使用 `random_per_text`，否则缓存命中率下降且行为不可预测。

2. 同情绪多参考音频的 prompt_text 问题  
v1 建议先约束为“同 emotion 共享 prompt_text”；后续再升级为 per-ref prompt_text。

3. 指令控制路径不一定吃到 spk_cache 的收益  
应在产品说明中明确“指令增强可能更慢”，并引导用户依赖结果缓存与批量 jobs。

---

## 13. 测试与验收清单（建议）

1. 分组管理
- 同一角色下可创建默认 8 情绪，并可添加自定义情绪
- 每个情绪可上传多条参考音频，元信息正确保存

2. 回退规则
- 请求某情绪无数据 -> 自动使用 default

3. 随机化
- `random_per_text`：同一文本多次选择同一 ref；不同文本分散到不同 ref
- `random_per_request`：同一文本多次可能选择不同 ref（配合 variation_seed）

4. 缓存兼容
- 同一输入（含 selected_ref_asset_id 与 variation_seed）重复请求命中结果缓存
- 改动 emotion voice 的 ref 列表后，相关 voice_fingerprint 变化导致旧缓存不再命中

5. compile
- `compile_all` 对多 ref 生成多 spk_id，不互相覆盖

---

## 14. FAQ（面向用户）

### Q1：为什么同一句话每次不一定一样？
如果你选择“生成新版本/重Roll”或开启“真随机”，系统会挑不同参考音频或不同 variation_seed，因此会变。

### Q2：为什么我改了情绪参考音频后，之前的结果不复用了？
因为 voice 配方变了（voice_fingerprint 变化），旧缓存会逻辑失效，这是预期行为。

### Q3：没有“悲伤”参考音频时会怎样？
会自动使用该角色的 `default` 参考音频。

---

## 15. 下一步落地建议（不涉及实现细节）

Phase A（最小闭环）：
1. 先实现数据结构：character/emotion/ref_asset_ids
2. 选择策略默认 `random_per_text`
3. 回退到 `default`

Phase B（增强）：
4. `variation_seed` + 重Roll
5. `compile_all` 批量编译
6. 指令增强（可选开关）

```
