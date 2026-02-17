# CosyVoice API 全功能升级方案与评估

## 1. 目标与范围

目标：把当前 API 从“基础 TTS 接口”升级为“覆盖 GUI 主要能力的服务化接口”，重点支持：

1. 通过 API 上传参考音频并执行克隆。
2. 通过 API 完成全部推理模式：
   - `零样本复制`
   - `参考音色`
   - `精细控制`
   - `指令控制`
3. 通过 API 完成配置管理、任务编排、版本管理、音频合成导出。
4. 保持现有端点兼容（`/`, `/api/tts`, `/api/tts_direct`, `/v1/audio/speech`）。

---

## 2. 现状盘点（基于当前代码）

当前已有能力：

1. 推理端点：
   - `/api/tts`：按角色配置推理
   - `/api/tts_direct`：支持 `multipart/form-data` 上传参考音频，或 base64 音频
   - `/`：酒馆兼容
2. 运行参数端点：
   - `/api/toggle_stream`
   - `/api/toggle_spk_cache`
3. 角色查询：
   - `/api/characters`
   - `/speakers`

当前缺口：

1. 缺少“资产管理”API：
   - 无音频文件上传生命周期管理（保存、复用、删除、索引）
   - 无角色配置 CRUD（创建、修改、删除、版本）
2. 缺少“任务编排”API：
   - 无批量段落任务提交、进度查询、失败重试
   - 无版本选择、回滚、重跑（seed 控制）服务化能力
3. 缺少“合成导出”API：
   - GUI 可合并输出，API 没有对应异步流程
4. 缺少“服务治理”：
   - 鉴权、并发控制、请求幂等、审计日志、限流、存储配额均未标准化

结论：当前 API 已具备“底层推理能力”，但未形成“完整生产 API”。

---

## 3. 升级总体设计

建议采用四层结构：

1. `Gateway`（Flask 路由层）
2. `Service`（业务服务层）
3. `Worker`（异步任务执行层）
4. `Storage`（文件与元数据存储层）

建议引入模块（按最小改动）：

1. `core/api_v2.py`：新版本路由（不破坏旧路由）
2. `core/services/`：
   - `voice_profile_service.py`
   - `asset_service.py`
   - `synthesis_service.py`
   - `job_service.py`
3. `core/repo/`：
   - JSON 文件仓储（第一阶段）
   - 可选 SQLite 仓储（第二阶段）
4. `core/jobs/queue.py`：内存队列或轻量线程池

数据目录建议：

1. `data/assets/audio/`：上传的参考音频
2. `data/voices/`：角色配置
3. `data/jobs/`：任务结果与中间产物
4. `output/`：最终导出音频

---

## 4. API 设计（v2）

版本建议：新增前缀 `/api/v2`。

### 4.1 资产管理

1. `POST /api/v2/assets/audio`
   - `multipart/form-data` 上传音频
   - 返回 `asset_id`, `path`, `duration`, `sample_rate`
2. `GET /api/v2/assets/audio/{asset_id}`
3. `DELETE /api/v2/assets/audio/{asset_id}`
4. `GET /api/v2/assets/audio`
   - 支持分页和关键字

### 4.2 角色配置管理

1. `POST /api/v2/voices`
   - 字段：`name`, `mode`, `prompt_text`, `prompt_audio_asset_id`, `instruct_text`, `color`
2. `PUT /api/v2/voices/{voice_id}`
3. `GET /api/v2/voices/{voice_id}`
4. `GET /api/v2/voices`
5. `DELETE /api/v2/voices/{voice_id}`
6. `POST /api/v2/voices/{voice_id}/compile`
   - 触发 `add_zero_shot_spk + save_spkinfo`

### 4.3 推理执行

1. `POST /api/v2/synthesize`
   - 同步短任务接口
   - 支持传入 `voice_id` 或 direct 模式参数
2. `POST /api/v2/synthesize/direct`
   - 上传音频 + prompt_text + text
3. `POST /api/v2/synthesize/stream`
   - 流式输出音频

统一请求结构（建议）：

1. `mode`
2. `text`
3. `speed`
4. `voice_id` 或 direct 参数（`prompt_audio_asset_id` / file）
5. `seed`
6. `stream`

### 4.4 任务编排（覆盖 GUI TaskPlan）

1. `POST /api/v2/jobs`
   - 提交批量段落任务（segments）
2. `GET /api/v2/jobs/{job_id}`
   - 任务状态、失败原因、各段输出
3. `POST /api/v2/jobs/{job_id}/retry`
4. `POST /api/v2/jobs/{job_id}/cancel`
5. `GET /api/v2/jobs/{job_id}/artifacts`

### 4.5 音频合成与版本

1. `POST /api/v2/merge`
   - 输入段落音频列表
   - 输出合成文件 `merged_asset_id`
2. `POST /api/v2/segments/{segment_id}/select-version`
   - 切换版本与片段

---

## 5. 实施路线图（分阶段）

## 阶段 A：可用版（1-2 周）

范围：

1. 新增 `/api/v2/assets/audio` 上传与读取
2. 新增 `/api/v2/voices` CRUD
3. 新增 `/api/v2/synthesize`，统一四种模式
4. 保持旧接口不变

验收标准：

1. 通过 API 完成“上传参考音频 -> 创建 voice -> 克隆生成”
2. 四种模式都可走统一接口

## 阶段 B：任务版（1-2 周）

范围：

1. 新增 `jobs` 异步任务
2. 新增批量段落提交、状态查询、重试
3. 新增合并音频接口

验收标准：

1. API 可完整替代 GUI 的批量生成主流程

## 阶段 C：生产版（1-2 周）

范围：

1. 鉴权（API Key/JWT）
2. 限流与并发控制
3. 结构化日志与审计
4. 存储配额与过期清理

验收标准：

1. 在局域网多客户端并发下稳定运行

---

## 6. 风险评估

## 6.1 技术风险

1. 模型推理线程安全风险（中高）
   - 当前模型对象全局共享，需串行化关键区或做队列调度
2. 流式与变速功能耦合风险（中）
   - 当前代码已提示 stream 与 speed 组合存在限制
3. TensorRT 环境差异风险（中）
   - 需在 API 错误码中显式返回 “加速不可用” 原因

## 6.2 业务风险

1. 文件膨胀风险（高）
   - 音频上传、任务中间文件、版本文件将快速增长
2. 非法输入风险（中高）
   - 需严格校验音频格式、大小、时长、文本长度
3. 兼容性风险（中）
   - 旧客户端依赖旧接口，必须维持兼容至少一个版本周期

## 6.3 运维风险

1. Windows 本地部署可观测性弱（中）
2. 无鉴权时暴露到局域网存在滥用风险（高）

---

## 7. 性能与容量评估

假设环境：Windows + RTX 4060。

1. 单实例推理建议并发：
   - 同步接口：`1-2` 并发
   - 超过后进入任务队列
2. 上传限制建议：
   - 单文件 `<= 20 MB`
   - 时长 `<= 60s`
3. 存储策略建议：
   - 原始音频保留 `7-30` 天可配置
   - 中间文件默认不持久化，或定时清理

---

## 8. 成本与工期评估

按 1 名开发估算：

1. 阶段 A：5-8 人日
2. 阶段 B：5-8 人日
3. 阶段 C：5-8 人日

总计：15-24 人日（不含大规模压测与前端改造）。

---

## 9. 推荐优先级

优先做：

1. `assets + voices + synthesize`（先打通完整克隆链路）
2. `jobs + merge`（覆盖批量生产）
3. `auth + rate limit + cleanup`（生产稳定性）

延后做：

1. 完整多租户
2. 复杂权限系统
3. 跨主机分布式调度

---

## 10. 关键决策建议

1. 是否引入 SQLite：
   - 建议引入，替代纯 JSON 元数据，减少并发写冲突
2. 是否保留旧端点：
   - 建议保留，设置废弃窗口（如 2 个小版本）
3. 是否先做异步任务：
   - 建议是。若只做同步接口，无法稳定覆盖“全部功能”

---

## 11. 最小可执行版本（MVP）定义

MVP 交付内容：

1. 上传参考音频 API
2. 角色配置 CRUD API
3. 单条与批量推理 API
4. 任务状态查询 API
5. 合并音频 API
6. 基础鉴权（API Key）

只要完成以上六项，即可满足“通过 API 实现模型主要功能”的业务目标。

