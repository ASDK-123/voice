# 本项目的“预编译参考音色(spkinfo)”是怎么做的？能否多音频合并？时长越长越好吗？
最后更新：2026-02-10

> 这份文档同时基于：
> - 本仓库源码（CosyVoice Frontend + v2 API compile 路由 + UI 预编译按钮）
> - 公开资料中对 CosyVoice/语音克隆参考音频时长与质量的建议

---

## 1. 先用一句话解释“预编译参考音色”是什么
在本项目里，“预编译参考音色”不是训练新模型，而是把“参考音频 + 参考文本”先跑一遍前端特征提取，把得到的 **speaker 条件特征** 缓存在 `spk2info.pt` 里；后续合成时如果传入同一个 `zero_shot_spk_id`，就能直接复用这些特征，减少首包延迟与重复计算。

对应本仓库里的关键文件：
- `cosyvoice/cli/cosyvoice.py`：`add_zero_shot_spk()` / `save_spkinfo()`
- `cosyvoice/cli/frontend.py`：`frontend_zero_shot()`（提取并组织“参考侧特征”）
- `core/api_v2_routes.py`：`POST /api/v2/voices/<voice_id>/compile`（v2 后端预编译接口）
- `ui/voice_settings.py`：语音设置页的“预编译并保存”按钮（批量预编译）

---

## 2. 本项目里具体是怎么“预编译并保存”的

### 2.1 UI 侧（语音设置页批量预编译）
`ui/voice_settings.py` 里 `SpeakerCompilerWorker` 会遍历满足条件的 voice（当前实现主要针对“零样本复刻/参考音色”模式），对每个 voice 做：
1. `model.add_zero_shot_spk(final_prompt_text, prompt_audio, name)`
2. 完成后调用一次 `model.save_spkinfo()` 把缓存落盘

注意点：
- `final_prompt_text` 会针对 CosyVoice3 补齐 `<|endofprompt|>` 前缀（避免 prompt 格式不符合 v3 要求）。
- 这个“预编译”发生在 UI 进程里持有的模型实例上（你选择“内嵌 API”模式时更贴近真实运行环境）。

### 2.2 v2 后端接口（对单个 voice 预编译）
`core/api_v2_routes.py` 的 `POST /api/v2/voices/<voice_id>/compile` 做的事情几乎一致：
- 读取该 voice 的 `prompt_text/prompt_audio/ref_asset_ids`
- 在模型锁 `V2_MODEL_LOCK` 内调用 `cosyvoice.add_zero_shot_spk(...)`
- 最后 `cosyvoice.save_spkinfo()` 保存到 `model_dir/spk2info.pt`

它还有一个参数：
- `?all=1`：会把 `ref_asset_ids` 里所有参考资产都编译一遍，但每条会用一个不同的 `spk_id`：`{voice_id}@{asset_id}`
  - 这等价于“为同一 voice 的多个参考音频生成多个缓存条目”
  - **这不是把多条音频合成一个 reference timbre**，而是“一条音频一个缓存 ID”

---

## 3. 原理：`add_zero_shot_spk()` 到底缓存了什么
看 `cosyvoice/cli/cosyvoice.py`：
- `add_zero_shot_spk(prompt_text, prompt_wav, zero_shot_spk_id)` 内部调用：
  - `self.frontend.frontend_zero_shot('', prompt_text, prompt_wav, self.sample_rate, '')`
  - 然后把 `text/text_len` 删除掉，仅保留“参考侧特征”，存入 `self.frontend.spk2info[zero_shot_spk_id]`

再看 `cosyvoice/cli/frontend.py` 的 `frontend_zero_shot()`，当 `zero_shot_spk_id == ''` 时，它会从参考音频里提取并组装一套条件特征，包括（字段名以源码为准）：
- `prompt_text/prompt_text_len`：参考文本 token（用于“参考侧语言内容”对齐）
- `llm_prompt_speech_token` / `flow_prompt_speech_token`：参考音频的 speech tokens
- `prompt_speech_feat`：参考音频的声学特征
- `llm_embedding/flow_embedding`：从参考音频提取的 speaker embedding（campplus）

为什么这能加速？
- 这些特征提取（ONNX 推理、fbank、whisper mel、tokenizer）是“参考侧固定成本”，预编译后复用，后续合成只需要处理 tts 文本与生成阶段。

### 3.1 一个关键硬限制：参考音频不能太长
`cosyvoice/cli/frontend.py` 的 `_extract_speech_token()` 里有断言：
- **参考音频长度必须 <= 30 秒**（否则直接报错）

所以“越长越好”在本项目实现下不成立：超过 30s 会失败；接近 30s 也会显著增加提取耗时，而且更容易混入无关内容/噪声/情绪漂移。

---

## 4. 能不能把“多个参考音频”编译成“一个参考音色”
分两种回答：**当前能不能** 与 **理论上能不能**。

### 4.1 当前实现：不能“直接合并”，只能“多条缓存 + 选择策略”
当前 CosyVoice 的 `add_zero_shot_spk(prompt_text, prompt_wav, id)` 入参只有一条 `prompt_wav`，因此：
- 你可以为多条参考音频分别 `add_zero_shot_spk`，得到多个 `spk_id`
- 但它们仍然是多个独立“参考音色条目”，不是融合成一个 embedding

在本项目 v2 的设计里，多参考通常应理解为：
- 一个 `voice_id=角色#情绪` 维护 `ref_asset_ids`（参考池）
- 后端在合成时按策略选 1 条（如 `random_per_text`），并保证“同文本稳定选择”

这正是 `core/emotion_selector.py` 的设计目标：多样性来自“参考池 + 稳定选取”，而不是“融合成一个向量”。

### 4.2 理论上可行的两种“合并思路”（但需要额外约束/或改代码）
1. **把多条音频拼接成一条音频，再当作单条 reference 来编译**
   - 本项目已经有 `POST /api/v2/merge` 可以把多段 wav 合并成一个新的音频资产（merged asset）。
   - 然后把该 merged 音频作为 `prompt_audio` 去 `compile`。
   - 风险：拼接会把不同句子/不同情绪/不同录音条件混在一起，可能让模型学到“更平均但更不稳定”的条件。
   - 还要确保长度 < 30s，并且 prompt_text 与合并音频的语义关系可能变得很难保持一致。
2. **把多个参考的 speaker embedding 做聚合（例如平均/加权），构造一个新的 spkinfo**
   - 这在一些系统里是可做的，但对 CosyVoice 来说，`spk2info` 里不止 embedding，还有 prompt_speech_token/feat 等多路条件，是否能“平均融合”并没有现成接口保证正确。
   - 如果要走这条路，需要深入修改 `frontend_zero_shot` 的数据组织与模型侧消费方式（属于“研究型改动”，不建议作为产品化第一步）。

结论建议：就你这个项目的目标（可控、可复现、缓存友好）而言，**更推荐“多参考池 + 稳定选择策略”**，而不是“强行融合成一个参考音色”。

---

## 5. 参考音频时长：越长越好吗？到底多长合适？
结论：**不越长越好**，需要在“足够信息量”和“干净稳定”之间取平衡。

### 5.1 本项目/模型实现侧的硬约束
- 单条参考音频 > 30 秒：本项目当前实现会在提取 speech token 时直接报错（见 `cosyvoice/cli/frontend.py`）。

### 5.2 公开资料中对“参考音频时长/质量”的建议（用于经验参考）
- 阿里云（CosyVoice v3 语音克隆 API）的参考建议：样本应为单人声、清晰、无噪声，且给出了“至少连续朗读 5 秒、推荐 10-20 秒”等要求（更偏工程实践）。  
  链接：
  ```text
  https://help.aliyun.com/zh/model-studio/cosyvoice-voice-cloning-api
  ```
- SiliconFlow 的“CosyVoice3 参考音频”建议（更偏平台经验）：推荐 8-10 秒、单人声、少噪声、少长停顿。  
  链接：
  ```text
  https://docs.siliconflow.cn/cn/api-reference/audio/voice#%E4%BC%98%E5%8C%96%E5%8F%82%E8%80%83%E9%9F%B3%E9%A2%91
  ```

### 5.3 针对本项目的建议区间（更可控）
给你一个“更像产品”的可执行建议：
- 单条参考音频：**6-15 秒**（大多数情况下够用）
- 上限：**尽量不超过 20 秒**（即便 30 秒可用，也会更慢、更容易混入不稳定因素）
- 质量优先级：清晰单人声 > 时长
- 每个 `角色#情绪` 的参考池：**2-4 条高质量**通常比“8 条一般质量”更稳

---

## 6. 和你当前前端设计最相关的落地建议（不改后端就能做的）
如果你的目标是“更高质量体验 + 不牺牲可复现/缓存命中”，建议 UI 把下面几件事讲清楚并可视化：
- 解释“预编译”的含义：减少首包延迟，避免每次重复提取参考侧特征
- 展示每个 voice 的参考池规模：`参考音频：N`
- 给用户一个明确的策略选项（中文）：`固定主样本 / 按文本随机（稳定）/ 每次随机（更丰富）`
- 给高级用户一个“变化种子 variation_seed”的入口：在稳定随机下实现“可控多样”

---

## 7. 你问到的三个问题的直接回答（TL;DR）
- 本项目怎么预编译并保存参考音色？
  - 用 `add_zero_shot_spk(prompt_text, prompt_wav, spk_id)` 把参考侧特征缓存到内存 `spk2info`，再 `save_spkinfo()` 保存为 `model_dir/spk2info.pt`。
- 能否同时处理多个音频编译成一个参考音色？
  - 当前实现不支持“多音频融合成一个”；支持“多音频各自编译成多个 spk_id”，或作为 `ref_asset_ids` 参考池由后端选取。
- 音频时间越长越好吗？
  - 不是。实现上 >30 秒会失败；经验上推荐 8-20 秒的清晰单人声更稳定。

