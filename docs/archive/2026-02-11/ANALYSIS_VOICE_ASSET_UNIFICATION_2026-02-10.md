# v2 角色/情绪/参考音频“数据不一致”分析报告（中期）
最后更新：2026-02-10

## 0. 结论摘要（先说结论）
你截图里的现象本质上不是“同一情绪有多个参考音频却只显示 default”，而是“声音库弹窗展示的是 v2 voices（角色配置），不是 v2 assets（参考音频资源）”。  
在当前架构里：
- “同一情绪多个参考音频”会体现在某个 `voice_id=角色#情绪` 的 `ref_asset_ids` 列表里，运行时按策略从列表里挑 1 个作为参考音频。
- 声音库弹窗只会显示“有哪些 voice（角色配置）存在”，不会因为 assets 里多了音频，就自动多出新的 `角色#情绪` voice 选项。
- 如果 `config/super_agent.json`（`app_config.json:v2_voices_config_path`）里只有 `胡桃#default`，那声音库就只会显示 `default` 这一行，即便情绪管理页里 default 标签下已经上传了多条参考音频。

## 1. 现象复盘（对应你的两张图）
- 情绪管理页（v2）右侧 default 情绪标签下有 2 条参考音频资产（assets）。
- 声音库弹窗里，角色“胡桃”只有一行 `胡桃#default`，情绪列只有 `default`。

这两者在当前实现中“看起来像不一致”，但从数据模型角度是“两个不同实体被分别展示”。

## 2. 当前 v2 的数据实体到底是什么
为了把话说清楚，需要区分 v2 的两个核心实体：`Voice` 和 `Asset`。

### 2.1 v2 Voice（“角色配置/音色配置”）
- 存储位置：`app_config.json:v2_voices_config_path` 指向的 JSON 文件。
- 代表含义：一个“可被选择用于合成”的 voice 配置。
- 关键字段（概念上）：`name(voice_id)`、`mode`、`prompt_text`、`instruct_text`、`ref_asset_ids` 等。
- voice 的粒度：项目约定是 `voice_id = 角色#情绪`，例如 `胡桃#default`、`胡桃#happy`。

### 2.2 v2 Asset（“参考音频资源/素材”）
- 存储位置：SQLite（见 `core/api.py` 的 `data/api_v2_assets.sqlite3`，由 `core/v2/assets_sqlite.py` 管理）。
- 代表含义：一条参考音频文件及其元信息（语言、情绪标签、备注、路径、sha1 等）。
- asset 的粒度：每上传一个音频就是一个 asset（同一情绪可有多个）。

### 2.3 两者关系（为什么你会觉得混乱）
在 v2 中，**Asset 不等于 Voice**。
- Asset 只是“材料”。
- Voice 是“配方”，它通过 `ref_asset_ids` 去引用若干材料。

如果你只上传 Asset，但不创建/更新 Voice（让 Voice 引用这些资产），那系统仍然只有原来的 Voice 可选。

## 3. 为什么“同一情绪多个参考音频”，声音库里还是只看到 default
因为声音库弹窗展示的是“Voice 列表”，它只看 v2 voices 数据源。

### 3.1 声音库弹窗的展示逻辑
- 数据源：`GET /api/v2/voices` 或 `v2_voices_config_path`（本地文件回落）。
- 展示结果：按 `character -> emotion` 分组列出 `voice_id`。
- 所以：只有当 `胡桃#happy` 这个 voice 真正存在于 voices 配置中，弹窗里才会出现 `happy` 这一行。

### 3.2 情绪管理页的展示逻辑
- 右侧表格是 assets 列表：`GET /api/v2/assets/audio?character=...&emotion=...&kind=ref`。
- emotion 的 Tab/分段控件只是“筛选标签”，并不等价于“某个 emotion voice 已存在”。
- 所以：同一 emotion 下上传 10 个资产，只会让 assets 表格变多，不会自动让声音库出现 10 个条目。

### 3.3 “多个参考音频”在合成时怎么用
在合成时，后端会把 voice 的 `ref_asset_ids` 视为候选池，然后选 1 个作为当次请求的参考音频。  
当前后端实现里，这个选择偏向“可复现/可控”，不是“让用户在声音库里看到多个条目手选”：
- `core/api.py` 会基于 `text_normalized`、`variation_seed`、策略等，从 `ref_asset_ids` 中挑 1 个，并把它写进 `selected_ref_asset_id`。
- 这意味着：“同一情绪多个参考音频”更像是“同一 voice 的多个参考样本”，而不是“多个 voice”。

## 4. 为什么你会感觉“后端角色管理混乱，数据无法统一”
这不是单一 bug，更像是“v2 架构还处于过渡期”的典型症状，主要来自 4 类原因。

### 4.1 两套存储形态并存（JSON voices + SQLite assets）
- voices 是 JSON 文件（便于编辑、版本化、迁移）。
- assets 是 SQLite（便于事务、去重、统计、清理）。
- 这本身合理，但如果 UI 没把“上传资产”与“创建/更新 voice 引用”做成强绑定动作，用户就会自然地认为“上传 = 可选”，从而产生认知断裂。

### 4.2 “情绪”在 UI 层与数据层语义不一致
- UI 的情绪标签是一组“可选筛选项”，默认就展示了多种情绪（default/happy/sad/...）。
- 数据层的情绪 voice 是否存在，取决于 voices 配置里有没有对应 `角色#情绪`。
- 于是会出现：UI 里有 happy 标签，但声音库里没有 `角色#happy` 这一项，这在用户视角就是“不一致”。

### 4.3 VoiceConfig/兼容字段导致“引用关系看起来不完整”
目前 voice 与 asset 的关联方式存在多种路径：
- 新路径：`ref_asset_ids`（显式引用 asset_id）。
- 兼容路径：`prompt_audio` 仅存文件路径，无法稳定表达“引用了哪个 asset”。
- 后果：某些地方只能“猜测 linked 状态”，有时你会看到“看起来绑定了，但另一处没体现”的体验问题。

### 4.4 多进程/配置路径不一致带来的错觉（最常见）
如果同时存在：
- UI 内嵌 API（进程内）读取 `app_config.json:v2_voices_config_path`。
- 外部 bat 启动的 API（独立进程）读取 `--config` 指向的另一份 voices JSON。

那就会出现：
- 情绪管理页能看到/创建的 voice，在声音库里看不到。
- 或声音库刷新后突然“回滚”到另一套数据。

你当前 `app_config.json` 显示 `v2_voices_config_path` 指向 `config/super_agent.json`，只要外部服务也保证用同一份文件，才能让“后端数据统一”。

## 5. 这件事应该如何定义“统一”，否则永远在打架
建议把产品语义明确成下面这一句，UI/后端都以它为准：

“用户可选择的是 Voice（角色#情绪）；用户可管理的是该 Voice 的参考音频池（多个 assets）；合成时系统从池中按策略选择 1 个。”

一旦定义成这样：
- 声音库就不应该因为 assets 多了就新增条目。
- 情绪管理页就必须把“创建 emotion voice”当成显式步骤或自动步骤，否则用户会误解。

## 6. 你截图里的场景，正确的解释与正确的预期
你的截图里 default 下有 2 条参考音频，但声音库只有 `胡桃#default`，这在现有模型下是“正常的”：
- 因为你还没有创建 `胡桃#happy`、`胡桃#sad` 等 emotion voice。
- 你上传的是 default 情绪资产，它们应该进入 `胡桃#default` 的 `ref_asset_ids` 池中，而不是让声音库多出一堆新情绪行。

如果你的目标是“让声音库出现 happy/sad...”，需要的动作是：
- 创建这些 `角色#情绪` voice（每个情绪一个）。
- 给每个情绪 voice 绑定各自的参考音频池（ref assets）。

## 7. 建议的“体验一致化”改造方向（只描述方案，不改代码）
下面这些是把“看起来混乱”变成“可理解且一致”的关键改造点。

### 7.1 在情绪管理页强制闭环（避免“上传=可选”的误解）
- 上传成功后明确提示：已上传到“参考音频库”，但还需要“创建该情绪 voice 并绑定”才能在合成/声音库中使用。
- 或者：上传后自动确保 `角色#情绪` voice 存在，并自动把 asset_id 追加到该 voice 的 `ref_asset_ids`。

### 7.2 声音库弹窗展示“voice 的参考池规模”，而不是展示 assets
- 在 `胡桃#default` 行旁边展示：`参考音频：2`，让用户知道“这个 voice 里确实有多个样本”。
- 依然保持“声音库的选择粒度是 voice”，避免条目爆炸。

### 7.3 明确 single source of truth（并在 UI 上可视化）
- 在 UI 明示当前 API 连接到的 `base_url`、当前使用的 `v2_voices_config_path`。
- 声音库的“刷新 voices”优先从 API 拉取，确保外部 API 模式下也一致。

## 8. 自查清单（你可以用来验证到底哪里不一致）
- 看情绪管理页右侧 assets 列表：这只说明“资产存在”。
- 看 `GET /api/v2/voices`：这才是“声音库应该展示什么”的来源。
- 看 `config/super_agent.json` 是否存在 `角色#happy`：不存在就不会在声音库出现。
- 确认外部 API 启动参数 `--config` 是否与 `app_config.json:v2_voices_config_path` 指向同一文件。

## 9. 术语对照（避免沟通歧义）
- “音色库/声音库”弹窗：Voice Picker，只展示 voices。
- “情绪管理”页右侧表格：Assets Library，只展示参考音频 assets。
- “绑定到当前 voice”：把选中的 asset_id 加入当前 voice 的 `ref_asset_ids`（形成引用关系）。

