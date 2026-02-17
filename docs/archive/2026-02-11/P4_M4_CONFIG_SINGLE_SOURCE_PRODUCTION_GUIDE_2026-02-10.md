# P4-M4 生产指南：配置单一化与 legacy 收口

最后更新：2026-02-10  
阶段目标：确立 v2 voices + v2 assets 为唯一运行时事实源，legacy 配置仅作为导入来源。  
前置阶段：M3 完成并稳定。

---

## 1. 里程碑定义

### 1.1 使命

1. 引入统一 voices store（`core/storage/voices_file.py`）并替代分散的 CharacterConfig 读写路径。
2. 固化配置职责：
   - `app_config.json`：应用设置
   - v2 voices JSON：业务配置
   - v2 assets sqlite：资产索引
3. 关闭 legacy 运行时写路径，保留导入工具链。

### 1.2 非目标

1. 不删除 legacy 文件（先保留兼容读取与导入提示）。
2. 不改变用户已有 v2 voices 文件内容语义。
3. 不改 UI 的所有展示细节（只改配置来源与同步机制）。

---

## 2. 单一事实源策略（SSOT）

### 2.1 事实源定义

1. voices：`app_config.json:v2_voices_config_path` 指向的 JSON（运行时唯一来源）。
2. assets：`data/api_v2_assets.sqlite3` + `data/assets/audio/`。

### 2.2 禁止事项

1. 禁止任何新功能继续写 `config/config.json`、`config/voice_config.json` 等 legacy 文件。
2. 禁止 UI 与 API 分别维护不同 voices 内存副本并长期不落盘。

### 2.3 允许事项

1. legacy 文件可读取用于导入。
2. 保留 `core/v2/legacy_import.py` 作为唯一迁移入口。

---

## 3. 核心实现对象：voices store

建议接口：

```python
class VoicesStore:
    def get_voice(self, voice_id: str) -> dict | None: ...
    def list_voices(self) -> list[dict]: ...
    def upsert_voice(self, voice: dict) -> None: ...
    def delete_voice(self, voice_id: str) -> bool: ...
    def reload(self) -> None: ...
    def save(self) -> None: ...
```

工程要求：
1. 原子写（临时文件 + replace）。
2. 线程安全（至少读写锁或单锁保护）。
3. schema normalize（补齐 `character/emotion/selection_policy/ref_asset_ids` 默认值）。

---

## 4. 迁移执行步骤

## Phase A：建立 store 与双写保护（1-1.5 天）

1. 新建 `core/storage/voices_file.py`。
2. 在 API 路径接入 store（保持现有接口不变）。
3. 在关键写操作加“legacy 写保护断言”：
   - 若检测到写 legacy，日志警告并阻断。

## Phase B：UI/API 同源验证（1 天）

1. 外部 API 进程与 UI 内嵌 API 统一读取同一 `v2_voices_config_path`。
2. UI 顶部展示当前 voices 路径与 API 连接状态。
3. 保存 voice 后立即 `reload` 验证一致性。

## Phase C：legacy 收口（0.5-1 天）

1. 把 legacy 导入入口集中到 UI 按钮/脚本。
2. 启动时若检测到 legacy 且 v2 为空，提示导入而非自动运行 legacy。
3. 文档明确“legacy 不再参与运行时”。

---

## 5. 验收标准（DoD）

1. 任何运行时 voice 变更都落在 v2 voices 文件，不再写 legacy。
2. UI 内嵌 API 与外部 API 读取同一路径且行为一致。
3. `POST/PUT/DELETE /api/v2/voices` 全流程可持久化且重启后一致。
4. legacy 文件存在时不会影响运行结果（仅触发导入提示）。

---

## 6. 测试矩阵

### 6.1 功能测试

1. 创建 voice -> 重启服务 -> voice 仍存在。
2. 更新 `ref_asset_ids` -> synth 选择行为生效。
3. 删除 voice -> 列表中消失且无脏数据。

### 6.2 一致性测试

1. UI 修改 voice 后，外部 API 立刻可见。
2. 外部 API 修改 voice 后，UI 刷新可见。

### 6.3 迁移测试

1. 给定 legacy config，执行导入脚本：
   - `python scripts/import_legacy_voice_config_to_v2.py ...`
2. 导入后 voice schema 合法且可 synth。

---

## 7. 发布与回滚

### 7.1 发布策略

1. 先灰度到测试环境，重点验证“同源读取”。
2. 再发布到主环境，观察 24h。

### 7.2 观察指标

1. voices CRUD 错误率
2. voices 文件写入失败率
3. “路径不一致”告警次数

### 7.3 回滚策略

1. 恢复旧 CharacterConfig 路径。
2. 保留新 store 文件但不启用。
3. 如果新 schema 导致问题，回退到前一份 voices 文件备份。

---

## 8. 风险与对策

风险 A：并发写导致 voices 文件损坏  
对策：原子写 + 写锁 + 文件备份轮转。

风险 B：schema 不兼容导致旧 voice 丢字段  
对策：normalize 时保留未知字段（forward compatibility）。

风险 C：路径错配持续发生  
对策：启动时打印并校验路径，UI 显示路径，提供一键复制与检查按钮。

---

## 9. 评审清单

1. 是否彻底切断 legacy 运行时写路径？
2. store 是否线程安全与原子写？
3. UI/API 是否同源读取并可证据化（日志/UI显示）？
4. 导入链路是否可用且可回滚？
5. 文档是否明确对用户的行为变化？

---

## 10. 乔布斯理念对齐（M4）

1. 简洁：用户只需要理解“一份 voices 配置”。
2. 端到端：从 UI 到 API 的配置体验一致，不再出现“改了没生效”。
3. 细节：路径可见、状态可见、错误可解释，减少心智负担。

---

## 11. M4 结束后的目标状态

1. 配置体系稳定，团队不再被“多配置源”反复拖慢。
2. 新功能全部基于 v2 voices/assets 扩展，遗留包袱封顶。
3. P4 主目标闭环：结构清晰、规则统一、配置单源、可持续迭代。

