# P2 产品化增强方案（工业级）：未引用清理 + 一键闭环向导

最后更新：2026-02-10  
适用范围：CosyVoice Desktop（UI）+ CosyVoice API（Flask v2）  
目标用户：零开发基础的使用者 + 本地维护者

---

## 0. 背景与前置条件

本阶段（P2）不再追求“增加更多功能点”，而是把已有能力做成更像产品的体验：
- 用户不知道应该按什么顺序操作
- 资产越积越多，不敢删也不会删
- 编译/测试/合成链路缺少可视化的闭环

前置条件（当前项目已具备或已在 P0/P1 建议中明确）：
- v2 作为长期主线维护，UI 默认走 v2 API
- v2 assets 使用 SQLite：`data/api_v2_assets.sqlite3`
- v2 voices 配置文件路径统一来自 `app_config.json:v2_voices_config_path`
- UI v2 client 层已抽出：`ui/v2_client.py`

---

## 1. P2-A：情绪资产“未引用清理”（一键清理 ref 资产）

### 1.1 问题定义

参考音频（ref assets）会快速堆积：
- 用户多次上传、试错、换情绪
- 绑定到 voice 的策略调整（ref_asset_ids）后旧资产变“孤儿”
- 长期使用后 `data/assets/audio/` 会越来越大

目标：找出“不被任何 voice 引用”的 ref 资产，并支持安全的一键清理。

### 1.2 关键口径（必须先统一，避免误删）

资产范围：
- 仅清理 `kind=ref` 的 assets（情绪参考音频）
- 不清理 `kind=output/merged`（输出音频、合并音频属于结果资产，默认不动）

引用判定（Referenced）：
- voice 字段中出现以下任一情况视为“引用”：
- `prompt_audio_asset_id` == asset_id
- `ref_asset_ids` 包含 asset_id
- `prompt_audio` 为文件路径且与某个 asset 的 `path` 匹配（兼容历史数据，避免只存 path 的 voice 被漏判）

未引用（Unused）：
- 在过滤范围内的 ref asset，其 `asset_id` 不在“引用集合”中，即为候选清理对象

### 1.3 实现策略（推荐：后端提供反向引用 + UI 展示与确认）

推荐原因：
- 逻辑只写一次，UI/脚本都复用
- 可在服务端做“最终一致性校验”（删前再算一遍引用，避免竞态误删）
- 便于日志与统计（删除多少、节省多少空间）

后端建议新增 v2 端点（不改变现有端点行为）：
- `GET /api/v2/assets/audio/refs`
- `GET /api/v2/assets/audio/unused`
- `POST /api/v2/assets/audio/cleanup`

### 1.4 API 设计（工业级，带 dry-run）

`GET /api/v2/assets/audio/refs`
- 用途：返回“资产 -> 引用 voice 列表”的反向引用视图
- 查询参数（可选）：`character`、`emotion`、`kind=ref`
- 返回：
```json
{
  "items": [
    {
      "asset_id": "a1b2c3",
      "path": "data/assets/audio/...",
      "character": "胡桃",
      "emotion": "happy",
      "kind": "ref",
      "ref_count": 2,
      "voices": ["胡桃#happy", "胡桃#default"]
    }
  ],
  "count": 1
}
```

`GET /api/v2/assets/audio/unused`
- 用途：直接返回未引用候选清单（给 UI 一键展示）
- 查询参数（可选）：`character`、`emotion`、`kind=ref`
- 返回：
```json
{
  "items": [
    {
      "asset_id": "deadbeef",
      "path": "data/assets/audio/...",
      "character": "胡桃",
      "emotion": "sad",
      "kind": "ref",
      "reason": "not_referenced"
    }
  ],
  "count": 1
}
```

`POST /api/v2/assets/audio/cleanup`
- 用途：批量删除（支持 dry-run）
- 请求：
```json
{
  "asset_ids": ["deadbeef", "cafe1234"],
  "dry_run": true
}
```
- 返回：
```json
{
  "status": "ok",
  "dry_run": true,
  "requested": 2,
  "deleted": 0,
  "skipped": [
    {"asset_id": "cafe1234", "reason": "still_referenced", "voices": ["胡桃#default"]}
  ],
  "bytes_reclaimed": 0
}
```

错误码建议（沿用 v2 规范）：
- `invalid_request`：缺少 `asset_ids` 或格式错误
- `asset_not_found`：资产不存在
- `conflict`：仍被引用（返回 skipped，不建议直接 409；更像“部分成功”）
- `internal_error`：删除失败

### 1.5 UI 交互设计（中文，安全为先）

入口位置（推荐）：
- 情绪管理页（v2）增加按钮：`清理未引用参考音频`

弹窗（清理向导）：
- 标题：`清理未引用参考音频`
- 内容区域：表格（多选）
- 表格列：`勾选`、`asset_id`、`角色`、`情绪标签`、`备注`、`创建时间`、`文件大小`
- 顶部信息：`本次可清理 X 个参考音频，预计释放 Y MB`
- 筛选区：`角色` 下拉、`情绪标签` 下拉、`仅显示未引用` 开关（默认开启）

安全机制（必须）：
- 默认勾选：不自动全选；提供按钮 `全选未引用`（二次确认）
- 二次确认：点击 `删除` 后弹确认框，文案明确“不可恢复”
- 删除前再次校验引用：调用后端 cleanup 时服务端必须再次计算引用集合（避免刚刚绑定后被误删）

体验补齐：
- 支持 `试听`（对单条资产调用 `/content`）
- 支持 `定位文件`（可选，Windows 打开所在目录；若暂不做就先不提供）

### 1.6 关键实现点（便于直接开发）

后端：
- 反向引用计算来源：
- voices：`/api/v2/voices` 的 `CharacterConfig.get_all_characters()`
- assets：`V2_ASSETS.list(kind="ref", ...)`
- 引用集合计算时做 path 规范化：`os.path.abspath`，避免相对路径误判
- 删除流程：
- 对每个 asset_id：校验存在 -> 校验未引用 -> 删除 sqlite 记录 -> 删除文件
- 记录 `log_event`: `asset_cleanup`，字段包含 `deleted/skipped/bytes_reclaimed`

UI：
- 复用 `ui/v2_client.py`
- 所有耗时调用走 worker 线程（避免 UI 卡死）
- 删除完成后自动刷新 assets 列表与 voice 绑定状态

验收（可执行）：
- 上传 3 个 ref，绑定其中 1 个到 voice：清理页面只显示未绑定的 2 个
- 删除后：`/api/v2/assets/audio` 不再出现对应 asset；磁盘文件消失；已绑定的那 1 个保持可用

---

## 2. P2-B：一键闭环向导（新建角色到可合成的最短路径）

### 2.1 用户目标（零基础）

用户想要的不是“配置项很多”，而是：
- 我新建一个角色，上传一段参考音频，点几下就能听到一句测试语音

向导目标：把复杂链路压缩为 5 步，且每一步都给出默认值与提示。

### 2.2 向导结构（5 步）

Step 1：连接与状态检查
- 显示：API 地址、连接状态、API Key 状态、模型是否已加载
- 按钮：`启动 API 服务`（若未运行）、`加载模型`（若未加载）

Step 2：新建角色信息
- 输入：`角色名`（中文）、`情绪标签`（默认 `default`）
- 自动生成：`voice_id = 角色名#情绪标签`
- 选择：`语言`（默认 `中文`）、`模式`（默认“零样本复制/参考音色”之一，按你项目默认）

Step 3：上传参考音频
- 上传控件：文件选择
- 自动填写：`情绪标签=default`（可改）
- 可选：`备注`
- 上传后立刻可 `试听`

Step 4：保存 voice 并绑定资产
- 保存策略（推荐）：
- `prompt_text` 必填（有模板提示）
- `prompt_audio_asset_id` = 刚上传 asset_id
- `ref_asset_ids` = [asset_id]
- `selection_policy` 默认 `random_per_text`
- 成功后提示：`已保存 voice：{voice_id}`

Step 5：compile + 合成测试句
- compile：调用 `/api/v2/voices/{voice_id}/compile`
- 测试句：默认提供中文示例（可编辑），调用 `/api/v2/synthesize`
- 合成结果：可播放 + 可保存（如果你当前支持 save_output）

### 2.3 UI 形态（推荐：独立 Dialog，Apple 风格）

入口位置：
- 情绪管理页右上角：`一键闭环向导`
- 语音设置页也可放入口（但先放 v2 情绪页更聚焦）

交互风格（建议）：
- 大标题 + 解释性副标题（中文）
- 主要按钮固定右下：`继续`、`上一步`、`取消`
- 每一步有清晰的“完成条件”，未满足时 `继续` 按钮禁用，并给出原因提示

关键 UI 文案（示例）：
- `你只需要 2 分钟就能创建一个可用角色`
- `如果你不知道填什么，保持默认即可`

### 2.4 API 调用与数据流（实现时可直接照做）

调用序列（成功路径）：
- `GET /api/v2/health`（确认服务可用）
- `POST /api/v2/assets/audio`（上传 ref）
- `POST /api/v2/voices`（创建 voice，并绑定 ref_asset_ids/prompt_audio_asset_id）
- `POST /api/v2/voices/{voice_id}/compile`
- `POST /api/v2/synthesize`（测试句）

失败处理（必须明确）：
- API 不通：提示“请先启动 API 服务”，并提供一键启动按钮
- 模型未加载：提示“请先加载模型”，并提供加载按钮
- 上传失败：提示原因，允许重试，不丢失已填字段
- compile 失败：仍可继续合成（可选），但提示“建议先 compile 可降低首包延迟”

### 2.5 验收（用户视角）

最小验收：
- 新用户从 0 开始，按向导操作能得到一条可播放的测试音频
- 生成的 voice 在 voices 列表中可见
- 生成的 ref asset 在资产列表中可见，并显示“已绑定”

---

## 3. 开发执行计划（最短闭环顺序）

阶段 P2.1：后端能力（1-2 天）
- 增加 unused/refs/cleanup 端点（或至少在 UI 侧完成同等逻辑）
- 日志 `asset_cleanup` 打点

阶段 P2.2：UI 清理弹窗（1-2 天）
- 列表展示 + 试听 + dry-run + 删除确认

阶段 P2.3：一键闭环向导（2-4 天）
- Wizard Dialog（Step1-5）
- 完整链路的线程化与错误提示

阶段 P2.4：打磨与回归（1-2 天）
- 文案、默认值、异常提示
- 回归：情绪管理页、voices CRUD、assets 上传/删除、compile、synthesize

---

## 4. 风险与对策

- 误删风险：必须“删前再算引用”，并提供 dry-run 预览
- 数据不一致风险：voice 只存 path 不存 asset_id 时，用 path 反查补齐引用判定
- 性能风险：大量资产时需要分页或后台计算（单机自用通常问题不大，但要留好接口）

---

## 5. 交付物清单

- 文档：本文件 `P2_PRODUCTIZATION_PLAN_2026-02-10.md`
- （建议）后端：
- `core/api_v2_routes.py` 增加 unused/cleanup 端点
- （建议）UI：
- `ui/emotion_voices.py` 增加清理弹窗入口
- 新增向导：`ui/voice_setup_wizard.py`（或 `ui/wizard/voice_setup_wizard.py`）

