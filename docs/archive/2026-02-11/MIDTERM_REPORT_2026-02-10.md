# 项目中期报告（截至 2026-02-10）

适用范围：`CosyVoice Desktop`（GUI）+ `core/api.py`（Flask API）+ `bridge.py`（OpenAI 兼容桥接）  
目标场景：单机自用为主，局域网自用为辅；核心诉求是“同一输入秒级复用、管理可控、日常使用更顺手”。

---

## 1. 当前结论（先给判断）

### 1.1 这些重大改动是否合适？
整体方向是对的，而且对你的使用场景非常匹配：
- **v2 API + 资产(assets) + 任务(jobs) + 磁盘缓存(cache)** 这条线是“把不可控的推理变成可控的系统”的正确路线，尤其适合单机 GPU 场景（避免 OOM、避免重复推理、把峰值变平）。
- **按角色分组的情绪音色（`character#emotion`）** 把“情绪”从模型训练问题转成“参考音频资产管理 + ref 选择策略”的工程问题，可迭代、成本低、效果可控。
- **UI 侧的 Voice Library 与情绪管理页改造** 直接瞄准“可用性瓶颈”（voice 下拉难用、控件太小、按钮墙），对日常频繁操作收益很大。

### 1.2 目前有哪些明显冗余？
项目进入“v1/v2 过渡期”后自然出现冗余；当前最明显的冗余来自：
- **重复的入口/界面**：同一件事可以在网页控制台(`web_api_console.html`) / 情绪管理页(`ui/emotion_voices.py`) / API 页(`ui/api_page.py`)里做一遍。
- **重复的启动方式**：外部 `StartAPIServer.bat` 启动 API 进程 vs UI 内嵌启动 API（`ui/api_page.py`）。
- **重复的配置体系残留**：legacy `voice_config_path`（旧 `config/config.json`）仍存在，但 v2 已成为运行时主数据源。

这些冗余“不是错”，但会带来维护成本；后续要逐步收敛为“一个事实来源 + 两三个清晰入口”。

---

## 2. 已落地的关键里程碑（从工程角度复盘）

### 2.1 v2 API 工程化：错误规范 + request_id + 可观测性雏形
已落地内容（核心落点在 `core/v2/` 与 `core/api_v2_routes.py`）：
- 统一 JSON 错误结构：`{"error":{"code","message","details"},"request_id":"..."}`（`core/v2/http.py`）
- 响应头携带 `X-Request-Id`，并在日志里打点（`core/v2/request_id.py`、`core/v2/logging.py`、`core/api_v2_routes.py`）
- v2 的主要资源型路由通过 Blueprint 拆出（`core/api_v2_routes.py`），降低 `core/api.py` 的膨胀速度

意义：
- 你在排查问题时终于有“请求级定位线索”（request_id），而不是靠猜。
- 错误能被 UI/脚本稳定解析（可自动重试/提示）。

### 2.2 v2 assets 元数据迁移到 SQLite（为扩展打基础）
已落地：
- SQLite 元数据：`data/api_v2_assets.sqlite3`（运行目录下可见）
- 存储实现：`core/v2/assets_sqlite.py`（包含 legacy JSON 索引导入能力）
- 文件内容仍在磁盘：`data/assets/audio/*`

意义：
- JSON 索引在数据量增大/并发写入时很脆；SQLite 是低成本但极稳的升级。
- 为后续 UI 批量筛选/统计/清理提供基础能力（按 character/emotion/language/note 查询非常自然）。

### 2.3 统一结果缓存（跨 GUI 与 API 复用）
已落地：
- 统一磁盘缓存：`data/cache/`，带 `index.json`，LRU 裁剪，in-flight 去重（`core/cache_manager.py`）
- 统一 cache key 算法：`core/cache_keys.py`（文本规范化、voice 指纹、model 指纹、请求 hash）
- GUI 写穿缓存：`core/worker.py` 生成结果后会写入缓存
- API v2 同样读写缓存：`core/api.py` 中 v2 synth/jobs 链路会用同一套 hash

意义：
- “同一输入秒级响应”真正落地：GUI/HTTP 任意一侧先生成，另一侧都能命中。
- 对单机自用，体验提升极明显：重复试听、反复生成同一句话不再烧 GPU。

### 2.4 v2 jobs（后台队列）把峰值并发变成可控
已落地：
- 统一 worker + `PriorityQueue` 的任务调度（`core/api.py` / `core/api_v2_routes.py`）
- 202 Accepted + job_id 的异步返回路径（v2 jobs 路由中可见）

意义：
- 这类“系统层限流”比在 UI 里硬等、或在 GPU 上直接 OOM，工程上更健康。

### 2.5 情绪音色体系：按角色分组 + 多 ref + 可控随机
已落地：
- voice_id 约定：`{character}#{emotion}`（例如 `Tom#happy`）
- 多参考音频绑定：`ref_asset_ids=[...]`
- 选择策略：`random_per_text / fixed / random_per_request`（`core/emotion_selector.py` + v2 synth key 逻辑）
- UI 情绪管理页走 v2：上传/试听/删除/绑定/解绑/compile（`ui/emotion_voices.py`）

意义：
- 你提出的“预生成多情绪缓存 + 指令增强”的核心落点已经具备：情绪侧主要靠 ref 资产体系，指令侧可以作为 voice 指纹的一部分进入缓存 key。

### 2.6 UI 易用性：Voice Library（voice 选择器）落地 + 接入文本/任务页
已落地：
- 新增可搜索/分组/收藏/最近的选择器：`ui/voice_library_dialog.py`
- 统一配置持久化：`core/config_manager.py`（`ui_recent_voice_ids`、`ui_favorite_characters`、`ui_last_emotion_by_character` 等）
- 接入文本页与任务页：`ui/text_edit.py`、`ui/task_plan.py`

意义：
- 从“巨型下拉框不可用”升级为“可搜索、可收藏、可最近”，对日常操作收益非常大。

### 2.7 情绪管理页 UI（Apple 风格）P0/P1/P2 已落地
已落地（`ui/emotion_voices.py`）：
- P0：字号/控件高度统一放大；按钮墙收敛为主操作 + 更多菜单；表格中文化；搜索 + 过滤
- P1：情绪切换从 Tab 改为 `SegmentedWidget`；情绪来源从 voices + assets 合并；记忆每角色上次情绪
- P2：拖拽上传；表格右键菜单（试听/绑定/解绑/删除/复制ID/打开位置）

意义：
- 直接解决你截图里反映的“字体小、控件小、操作入口过多且分散、资产难找”的痛点。

---

## 3. 架构是否合理（以“单机自用 + v2 长期维护”为标准）

### 3.1 合理点（应该保留并继续强化）
- **v2 作为主线**：assets/voices/jobs/synthesize 的资源化 API 结构更适合长期演进（`core/api_v2_routes.py`）。
- **缓存与队列属于系统能力，不是业务逻辑**：放在 core 层，并让 UI/bridge/client 都共享，是正确的“平台化”路线（`core/cache_manager.py`、`core/cache_keys.py`、`core/api.py`、`core/worker.py`）。
- **SQLite 作为 v2 assets 索引**：对未来扩展（清理、统计、批量操作、并发写入）非常关键（`core/v2/assets_sqlite.py`）。

### 3.2 不合理点（短期可跑，长期会拖累）
- **`core/api.py` 仍然过大**：虽然有了 `core/api_v2_routes.py`，但 `core/api.py` 仍承担太多职责（推理/缓存/队列/资产/兼容路由/工具函数等）。这会让后续迭代越来越慢、bug 越来越难定位。
- **UI 内部存在多处“各写一份 v2 HTTP 调用”**：`ui/emotion_voices.py` 自带 `V2Client`，`ui/api_page.py` 也有一套 requests 调用；未来会产生不一致（超时/鉴权/错误处理/字段兼容）。
- **多启动路径容易造成“同一台机器两个真相”**：外部 API 进程与 UI 内嵌 API 若读取不同 voices 配置文件，会出现“UI 看到 A、API 看到 B”的割裂（文档里已提示这一风险）。

---

## 4. 改动后有哪些“冗余功能/重复实现”

按“对你单机自用”的角度，当前可以认为冗余或需要收敛的点：
- `web_api_console.html` 与 `ui/emotion_voices.py` 的功能重叠较多（都能做 assets/voices 的管理操作）
- `StartAPIServer.bat` 与 UI 内嵌启动 API 的方式二选一即可（长期建议以 UI 内嵌为主、bat 为备用）
- legacy voices 配置体系仍残留入口（`app_config.json:voice_config_path`、`ui/voice_settings.py` 的导入逻辑），建议后续把“导入/导出/备份”与“运行时配置”明确分离，避免用户误用
- `bridge_draft.py` 属于历史草稿，可考虑标记为 deprecated 或移动到 `scripts/`（避免读代码时干扰）

---

## 5. 推荐优化的组件清单（按投入产出排序）

### 5.1 P0：立刻能降低维护成本（建议尽快做）
- **统一 UI 的 v2 client 层**：抽一个 `ui/v2_client.py`（或 `core/v2/client.py`）封装：base_url/api_key/timeout/request_id/错误解码；`ui/emotion_voices.py` 与 `ui/api_page.py` 复用。
- **收敛 voices 配置文件来源**：明确“UI 内嵌 API”与“外部 API 进程”必须指向同一个 `v2_voices_config_path`（并在 UI 上显示当前配置路径，降低踩坑概率）。
- **修复/清理乱码与历史日志文本**：例如 `core/worker.py` 有明显乱码字符串，会直接污染 UI 日志与用户体验（属于低成本高收益）。

### 5.2 P1：提升架构健康度（建议下一阶段做）
- **继续拆薄 `core/api.py`**：至少把 v2 资源路由全部留在 `core/api_v2_routes.py`，`core/api.py` 只保留：app 初始化、模型注入、v1 兼容入口、全局锁/缓存/作业调度 glue code。
- **缓存索引升级到 SQLite（可选）**：当前 cache index 用 JSON 足够单机，但如果你后续会批量生成很多素材，SQLite 会更稳、更易做统计/清理策略。

### 5.3 P2：提升“像产品”的完成度（按需）
- **情绪资产“未引用清理”**：找出未被任何 voice 引用的 ref 资产，一键清理（需要后端提供反向引用或 UI 侧扫描 voices）。
- **一键闭环向导**：新建角色 -> 上传 default ref -> 保存 voice -> compile -> 合成测试句（对零基础更友好）。

---

## 6. 这些改动是否真的优化使用体验？

对你的实际使用（单机自己用 + 局域网自己用），体验提升是确定的，主要体现在：
- **重复生成的“秒级响应”**：磁盘缓存让大量重复试听/重复句子生成几乎不再消耗推理时间。
- **更少的 OOM/卡死**：jobs/锁/队列把并发与资源使用变得可控，出问题也更可诊断。
- **voice 选择与情绪管理的“可用性跃迁”**：Voice Library（搜索/收藏/最近）+ 情绪管理页（大字号/主次操作/搜索过滤/右键/拖拽）是直击痛点的改造。

需要注意的“体验回退风险”也存在：
- 如果 UI 与外部 API 进程使用了不同的 voices 配置文件，会出现“我明明设置了但另一个页面看不到”的错觉（这是目前最常见的用户困惑来源）。

---

## 7. 下一阶段建议（2 周内的最短闭环）

建议按这个顺序推进，最稳、返工最少：
1. 统一 UI 的 v2 client 层（减少重复实现与不一致）
2. 统一 voices 配置文件来源（避免 UI/服务端割裂）
3. 继续拆薄 `core/api.py`（至少做到 v2 资源路由完全迁出）
4. 清理历史草稿与重复入口（`bridge_draft.py`、`web_api_console.html` 是否保留按你习惯决定）

---

## 8. 验收指标（中期阶段“算做成功”的客观标准）
- 同一文本 + 同一 voice（含 ref_asset_ids/策略/指令）重复生成：第二次命中缓存，体感延迟显著下降
- 情绪管理页：拖拽上传 -> 绑定 -> 保存 voice -> 编译 -> 试听/合成测试句，全流程无需离开 GUI
- 文本页/任务页：能在 2 秒内通过搜索/收藏/最近完成 voice 选择，不再依赖长下拉框
- 出错时：能通过 request_id 在日志里定位一次请求的失败点（而不是“只知道失败”）

