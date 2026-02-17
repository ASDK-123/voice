```markdown
# 设计文档：统一缓存与任务队列（Cache + Jobs v1）

状态：Draft  
最后更新：2026-02-09  
适用范围：CosyVoice Desktop（GUI）+ CosyVoice API（Flask v1/v2）+ OpenAI Bridge

---

## 1. 背景（现状概览）

本仓库当前包含三条主要链路：

1. GUI 直推理链路  
- `main.py` 启动桌面应用  
- `ui/` 负责文本分段、角色配置、任务计划、音频合并  
- `core/worker.py` 在后台线程中调用模型推理并把音频写入 `output/{ProjectName}/...`

2. Flask API 服务链路  
- `core/api.py` 提供 v1 兼容端点与 v2 管理端点  
- v2 已支持 assets/voices/synthesize/jobs/merge，并提供可选 API Key 鉴权

3. OpenAI Bridge 链路  
- `bridge.py` 对外提供 `POST /v1/audio/speech`，并转发到后端 TTS

当前“加速能力”已存在雏形（TensorRT/FP16、参考音色缓存 compile、v2 jobs），但缺少“统一的音频结果缓存”，导致重复输入仍会重复跑推理。

---

## 2. 目标与非目标

### 2.1 目标（必须满足）

1. 同一输入命中缓存时，直接返回已生成音频，不再推理  
- 同一输入定义：同一文本 + 同一 voice 配置（包含 prompt/instruct/mode）+ 同一参数（speed 等）+ 同一模型身份

2. voice 配置更新后，旧缓存必须失效  
- 失效定义：后续请求不再命中旧缓存  
- 是否立即删除旧缓存文件：可选（默认由 LRU 自然淘汰）

3. 缓存磁盘上限为 500MB，自动清理  
- 清理策略对零基础用户可解释  
- 清理不会破坏用户导出的 `output/` 文件

4. 同一套缓存同时加速 GUI 与 API  
- GUI 生成过的结果可被 API 复用  
- API 生成过的结果可被 GUI 复用

5. 并发下避免重复生成同一份音频  
- 同一个 request_hash 同时到达时，只生成一次

### 2.2 非目标（本设计 v1 不做）

1. 分布式队列（Redis/Celery）  
2. 在线模型上传与大模型版本分发  
3. 强确定性推理（deterministic）

---

## 3. 术语表（零基础解释）

- voice：一个“角色音色配置”，包含参考音频、参考文本、模式等  
- voice_id：voice 的标识，例如“默认音色”  
- prompt_audio：参考音频（用于零样本复制/参考音色等）  
- prompt_text：参考音频对应的文本（用于零样本复制）  
- instruct_text：指令文本（用于指令控制）  
- request_hash：一次合成请求的唯一指纹（用于查缓存）  
- voice_fingerprint：一个 voice 配置的唯一指纹（配置一变就变）  
- model_fingerprint：当前模型身份指纹（模型目录、精度开关等）  
- cache：可删除的加速区，存放可复用的“成品音频”  
- assets：用户上传参考音频与系统输出音频的“资源库”（v2 已存在）  
- job：后台任务（v2 已存在）

---

## 4. 总体设计（从用户视角理解）

用户合成时系统执行：
1. 标准化输入（保证文本一致）  
2. 计算指纹（voice_fingerprint + request_hash + model identity）  
3. 查缓存：命中返回音频，未命中推理并写缓存

---

## 5. 目录结构与存储

### 5.1 缓存目录
- `data/cache/audio/{request_hash}.wav`  
- `data/cache/index.sqlite3`（默认，SQLite 索引）  
- `data/cache/index.json`（兼容：仅用于首次导入或回退）  
- `data/cache/state.json`（可选）

说明：
- `data/cache/` 为“加速缓存”，可随时删除，不影响配置
- 索引后端可选：环境变量 `CACHE_INDEX_BACKEND=json|sqlite`（默认 `sqlite`）
- 使用 `sqlite` 时，首次启动会尝试从 `index.json` 自动导入（非破坏性）
- 手动迁移脚本：`python scripts/migrate_cache_index_json_to_sqlite.py`

### 5.2 v2 assets（保持不变）
- `data/assets/audio/`：参考音频与输出音频  
- `data/api_v2_assets.sqlite3`：资产索引（SQLite，v2 读写都走这里）  
- `data/outputs/`：合并等中间输出

迁移说明：
- 若你之前使用过旧版 JSON 索引（`data/api_v2_assets.json`），可以运行一次性脚本把数据导入 SQLite：
  - `python scripts/migrate_v2_assets_json_to_sqlite.py`
  - 导入后 JSON 不再作为主存储（仅保留兼容迁移用途）

---

## 6. 指纹算法（字段定义）

### 6.1 文本规范化
- `strip()` + 统一换行 + 把连续空白合并 -> `text_normalized`

### 6.2 prompt_text / instruct_text
- 需要符合最终进入推理的字符串（包含 `<|endofprompt|>` 等），用于 `voice_fingerprint`

### 6.3 prompt_audio_hash
- 优先用 asset 的 `sha1`，否则读取文件计算 sha1（可用 size/mtime 做快速判断）

### 6.4 model_fingerprint
- 包含 `model_dir`, `fp16`, `load_trt`, `load_vllm` （JSON 后 hash）

### 6.5 voice_fingerprint
- JSON(`voice_id`, `mode`, `prompt_text_normalized`, `instruct_text_normalized`, `prompt_audio_hash`) 后 hash

### 6.6 request_hash
- JSON(`cache_schema_version`,`model_fingerprint`,`voice_fingerprint`,`text_normalized`,`speed`) 后 hash

---

## 7. 缓存索引结构

记录内容（当前实现）：
- `request_hash`,`path`,`size_bytes`,`created_at`,`last_access`,`meta`

索引存储：
- JSON：`data/cache/index.json`
- SQLite：`data/cache/index.sqlite3`（表 `cache_entries`，`meta` 存为 JSON 字符串）

---

## 8. 清理策略（500MB LRU）

规则：写入后检查总大小；超限按 `last_access` 删除；只清 `data/cache/audio/`

---

## 9. 并发与去重

维护 `inflight[request_hash]`；若碰撞等待 `sync_wait_ms`（3-5s）；超时返回 202 or 409

---

## 10. API 规范

### 10.1 认证
- 设置 `API_KEY` 则所有入口要求 `X-API-Key` 或 `Authorization: Bearer`

### 10.2 Request ID
- 响应头 `X-Request-Id` + JSON 字段

### 10.3 错误格式
- `{"error":{"code":"invalid_request","message":"...","details":{...}},"request_id":"..."}`  
- 常用 code：`invalid_request`,`unauthorized`,`conflict`,`payload_too_large`,`model_not_loaded`,`voice_not_found`,`asset_not_found`,`job_not_found`,`internal_error`

补充：
- v2 的 JSON 成功响应也会携带 `request_id` 字段；音频响应（`audio/wav`）只在响应头携带 `X-Request-Id`

---

## 11. 接口行为

### 11.1 POST `/api/v2/synthesize`
- 请求：`text`, `voice_id`, `speed`, `prompt_text`, `prompt_audio_asset_id`, `response_format`, `save_output`, `prefer_async`, `sync_wait_ms`
- 命中：200 `audio`/`json`，头 `X-Cache:HIT`
- 未命中同步：推理写 cache，返回 200 `audio`/`json`
- miss + `prefer_async`: 202 + `job_id`
- 状态码：400/401/404/409/429/500/503

### 11.2 POST `/api/v2/jobs`
- 请求包含 `segments` + `merge`
- Worker 按 segment 查 cache -> 推理 -> 写 cache -> 记录结果
- 合并时调用 ffmpeg concat
- 返回 202 `job_id`

### 11.3 GET `/api/v2/jobs/{job_id}`
- 返回 status/results/merged_asset_id/error

### 11.4 POST `/api/v2/jobs/{job_id}/cancel`

### 11.5 POST `/api/v2/jobs/{job_id}/retry`

### 11.6 POST `/api/v2/voices/{voice_id}/compile`
- 调用 `add_zero_shot_spk`，可 `save_spkinfo`

### 11.7 Health 与 Metrics
- 新增 `/health` 返回 model_loaded/gpu/queue/cache stats
- `/metrics` JSON（请求数、延迟、hit率）

---

## 12. v1/bridge 兼容策略

- `/` `/api/tts` `/api/tts_direct` `/bridge`：共用缓存管理

---

## 13. 流程图（文字版）

### v2 synthesize
```
Client -> Normalize -> compute hashes -> Cache HIT? -> yes: return HIT
                              -> no: inflight? wait -> inference -> write cache -> return 200
```

### v2 jobs
```
POST /api/v2/jobs -> enqueue -> worker per segment -> cache HIT reuse -> cache MISS inference
```

### GUI
```
Segment -> compute hash -> cache HIT link to output -> MISS inference+cache
```

---

## 14. FAQ

1. 改颜色为什么没失效？颜色不影响声音；
2. 改 prompt_audio 旧缓存失效；旧文件由 LRU 清理；
3. 删除 `data/cache/` 只是变慢；
4. 同一句话不同 speed 视为不同输入；
5. 缓存不会超 500MB；
6. 设置 key 后要求鉴权；
7. jobs 即使单机也有用，避免 OOM。

---

## 15. 验收清单

1. 相同输入 2 次：一次 miss+一次 hit  
2. 修改 prompt/audio/speed：必须 miss  
3. cache 超 500MB 自动清理  
4. GUI 生成后 API hit，API 生成后 GUI hit  
5. 并发同 hash 只生成一次

---

``` 
