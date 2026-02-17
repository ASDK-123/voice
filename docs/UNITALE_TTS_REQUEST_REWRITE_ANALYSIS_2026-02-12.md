# Unitale TTS 请求转写可行性分析（面向当前项目）

## 1. 问题

是否可以不做后端兼容层，而是直接把 Unitale 的 TTS 请求改写为当前项目原生可识别的请求？  
是否会更简单？

## 2. 结论（先给答案）

在你当前项目里，答案是：**可以，而且在“你自己维护 Unitale 分叉版”的前提下，通常更简单**。  

但“简单映射”只在以下条件同时满足时成立：

1. 角色名能稳定匹配你后端的 `character`。
2. 情绪名完成一层中英映射（Unitale 是中文系统情绪，你后端主要是英文 emotion）。
3. 接受 `emo_vector` 语义在当前后端中被弱化/忽略。

## 3. 证据与现状

### 3.1 Unitale 当前请求形态

Unitale 当前对 TTS 的关键请求：

1. `GET /v1/check/audio`：`peiying/Unitale/index.html:1923`
2. `POST /v1/upload_audio`：`peiying/Unitale/index.html:1937`
3. `POST /v2/synthesize`，payload 用 `audio_path + emo_vector/emo_text`：`peiying/Unitale/index.html:1907`、`peiying/Unitale/index.html:3500`

同时，Unitale 的 TTS 配置仅有 `name/baseUrl`，没有 TTS API Key 字段：`peiying/Unitale/index.html:944`、`peiying/Unitale/index.html:1452`。

### 3.2 你当前后端原生能力

你当前推荐接口：

1. `POST /api/v2/synthesize`：`API_USAGE.md:367`
2. `POST /api/v2/assets/audio`：`API_USAGE.md:347`
3. `GET /api/v2/voices`：`API_USAGE.md:355`

`/api/v2/synthesize` 支持两类主输入：

1. `voice_id`（优先）
2. direct 参数 `prompt_text + prompt_audio_asset_id`：`API_USAGE.md:371`、`API_USAGE.md:380`

后端 direct 路径中，若走 `zero_shot/reference_timbre` 且缺 `prompt_text` 会失败：`core/api_legacy.py:1667`。

### 3.3 你当前 voice 数据对“角色+情绪映射”友好

`config/super_agent.json` 里已是 `character#emotion` 结构，且包含多角色多情绪（例如 `胡桃#happy`、`芙宁娜#sad` 等）。  
当前 emotion 统计（配置实测）：

1. `default`: 12
2. `happy`: 2
3. `calm/disgust/sad/surprise`: 各 1

这意味着“按 `角色#情绪` 选 voice_id”是可行的主路径。

## 4. 为什么它“可能更简单”

相比后端兼容层（新增 3 个旧协议端点 + 服务器侧映射），“前端转写”可直接复用你现有稳定接口，不改后端核心：

1. 上传：直接调 `/api/v2/assets/audio`
2. 取 voice：直接调 `/api/v2/voices`
3. 合成：直接调 `/api/v2/synthesize`

优点：

1. 后端零新增协议债务（不引入 `/v1/*` 历史包袱）。
2. 逻辑聚焦在 Unitale 前端一侧，回归范围更可控。
3. 与你现有 v2 能力一致，长期维护方向更统一。

## 5. 但不是“纯简单映射”的三个难点

### 5.1 情绪命名体系不一致

Unitale 系统情绪是中文（如 `高兴/生气/伤心/害怕/厌恶/低落/惊喜/平静`）：`peiying/Unitale/index.html:762`。  
你当前 voices emotion 主要是英文（`default/happy/sad/...`）。

必须有映射表，例如：

1. `平静 -> default`
2. `高兴 -> happy`
3. `伤心/低落 -> sad`
4. `惊喜 -> surprise`
5. `厌恶 -> disgust`
6. `生气/害怕 -> default`（若无对应 voice）

### 5.2 角色名来自 LLM，可能不在 voices 中

Unitale 脚本角色由 LLM 结果动态生成：`peiying/Unitale/index.html:3224`。  
若角色名不在你 `v2 voices` 里，需要 fallback 策略（`角色#default` -> `旁白默认voice` -> direct）。

### 5.3 direct fallback 需要 `prompt_text`

Unitale 当前音色库核心字段是 `refPath`，并不保证有可用转写文本（`description` 不能等价替代 `prompt_text`）。  
若 fallback 到 direct 而不给 `prompt_text`，zero-shot 会失败（见上文后端限制）。

## 6. 可执行的“前端转写”设计（不改后端）

## P0：主路径只走 `voice_id`（推荐）

1. 启动时拉取 `/api/v2/voices`，构建索引：
   1. `byVoiceId`
   2. `byCharacterEmotion`
2. 逐行生成时：
   1. `role = line.role`
   2. `emotion = mapEmotion(line.emotion)`
   3. 尝试 `voice_id = role#emotion`
   4. 不存在则尝试 `role#default`
   5. 仍不存在则走全局默认 `胡桃#default`（可配置）
3. 调 `/api/v2/synthesize`：
   1. `{ text, voice_id, response_format: "audio" }`

这一步就能覆盖你现有“多角色+多情绪 voice”主能力。

## P1：补 direct fallback（可选）

当 voice 完全未命中时：

1. 将音色文件上传到 `/api/v2/assets/audio`，缓存 `refPath -> asset_id`
2. 调 `/api/v2/synthesize` direct 参数：
   1. `prompt_audio_asset_id`
   2. `prompt_text`（必须有；没有就禁止 direct 并提示用户）
   3. 可考虑 `mode: "fine_grained"` 作为无 `prompt_text` 兜底（音色效果会变）

## 7. 复杂度对比（本项目语境）

### 方案 A：前端转写（改 Unitale）

开发量：

1. 中等（约 2~4 天可出可用版）
2. 主要是 JS 层请求改写 + 映射 + fallback

维护成本：

1. 你需要维护 Unitale 分叉（上游更新需手工合并）

### 方案 B：后端兼容层（不改 Unitale）

开发量：

1. 中等偏高（约 4.5~7 天，含测试与回滚）

维护成本：

1. 你后端要长期背旧协议兼容负担

## 8. 最终建议

如果你的目标是“尽快在你自己环境里跑起来，并且你接受维护 Unitale 分叉”，优先选**前端请求转写**。  

如果你的目标是“尽量不动 Unitale、未来多客户端直接复用同一旧协议”，再选**后端兼容层**。

基于你当前已有多角色多情绪 voice 数据，建议优先走：

1. `voice_id` 映射主路径
2. direct fallback 作为二期补充

## 9. 最小验收标准（转写路线）

1. Unitale 单条台词可直接合成成功（走 `voice_id`）。
2. 一键生成时，80% 以上台词无需 direct fallback。
3. 现有 `/api/v2/synthesize` 与桌面端功能不受影响。
4. 所有失败都能提示“角色未命中/情绪未命中/缺 prompt_text”而不是静默失败。

---

一句话总结：  
在你这个项目的现状下，**“改 Unitale 请求 -> 对接你现有 v2 接口”大概率比做后端兼容层更快**，但要把“情绪翻译 + 角色兜底 + direct 的 prompt_text 约束”设计清楚。
