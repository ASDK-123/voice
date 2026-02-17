# Unitale v3 手工回归记录（按验收清单逐条执行）

- 日期: 2026-02-13
- 范围: `peiying/Unitale/index.html`（不改业务代码）
- 方式: 静态核验 + 脚本语法检查 + Prompt适配复核

## 1. 执行摘要
1. 已完成静态可验证项复查（关键词扫描、schema字段、函数存在性、`node --check`）。
2. 重构主链路与 v3 结构已落地，旧情绪向量/强度机制已清理。
3. 需要真实后端/音频资源的联调项仍为 PARTIAL（本轮未做端到端）。
4. Prompt 当前可用，但存在 3 个建议优化点（本轮仅记录，不改代码）。

## 2. 核验命令与结果

### 2.1 旧链路残留扫描
- 命令: `rg -n "emotionPresets|emotionForm|isEditingEmotion|SYSTEM_EMOTIONS|isSystemEmotion|mapEmotionToVoiceEmotion|saveEmotion|editEmotion\(|deleteEmotion\(|resetEmotionForm|resetEmotionsToDefault|libraries\.emotions|line\.intensity|schema_version:\s*2|version:\s*'2\.0'" peiying/Unitale/index.html`
- 结果: 无匹配（PASS）

### 2.2 v3 关键结构扫描
- 命令: `rg -n "schema_version:\s*3|version:\s*'3\.0'|normalizeEmotionTag|getEmotionOptionsForRole|globalEmotionCatalog|normalizeLineEmotion|normalizeScriptLineV3" peiying/Unitale/index.html`
- 结果: 命中关键位置，结构齐全（PASS）

### 2.3 主脚本语法检查
- 命令: `node --check <index.html主script提取文件>`
- 结果: 通过（PASS）

### 2.4 Prompt 片段扫描
- 命令: `rg -n "defaultPromptTemplate|\$\{emotionList\}|可用变量|IndexTTS|旁白通常选择|台词对象|intensity|强度" peiying/Unitale/index.html`
- 结果: 发现可用但有改进空间的文案点（见第4节）

## 3. 验收清单逐条记录

1. UI 不再有情绪预设区
- 状态: PASS（静态）
- 证据: 旧关键词扫描无匹配。

2. 脚本行无强度控件
- 状态: PASS（静态）
- 证据: 无 `line.intensity` 绑定；仅保留导入清洗 `delete out.intensity`（`peiying/Unitale/index.html:1620`）。

3. 脚本行情绪来自 v2 动态候选
- 状态: PASS（静态）
- 证据: `v-for="emotion in getEmotionOptionsForRole(line.role)"`（`peiying/Unitale/index.html:636`）。

4. 显式 voiceId 优先命中
- 状态: PASS（静态）
- 证据: `explicitVoiceId` 优先于自动匹配（`peiying/Unitale/index.html:2543`, `peiying/Unitale/index.html:2545`）。

5. 未命中 voice 走 direct reference
- 状态: PASS（静态）
- 证据: `prompt_audio_asset_id + mode=zero_shot` 分支（`peiying/Unitale/index.html:2559`, `peiying/Unitale/index.html:2571`）。

6. 无 voice 且无 reference 报错清晰
- 状态: PASS（静态）
- 证据: 报错文本明确（`peiying/Unitale/index.html:2557`, `peiying/Unitale/index.html:2565`）。

7. LLM 未知 emotion 自动回退并提示
- 状态: PASS（静态）
- 证据: `normalizeLineEmotion` 含回退 + 告警（`peiying/Unitale/index.html:1597`）；解析后调用（`peiying/Unitale/index.html:3968`）。

8. 导出不含 `libraries.emotions` 与 `line.intensity`
- 状态: PASS（静态）
- 证据: 导出 libraries 不含 emotions（`peiying/Unitale/index.html:3022`）；导出前行清洗（`peiying/Unitale/index.html:2988`, `peiying/Unitale/index.html:1620`）。

9. 拒绝导入 schema<3
- 状态: PASS（静态）
- 证据: 导入拦截（`peiying/Unitale/index.html:3104`-`peiying/Unitale/index.html:3107`）。

10. schema v3 导入成功后可继续使用
- 状态: PARTIAL（静态通过，联调未做）
- 证据: v3 导入恢复路径存在（`peiying/Unitale/index.html:3133`-`peiying/Unitale/index.html:3174`）。

11. v2 voices/assets 刷新、搜索、绑定/解绑、试听
- 状态: PARTIAL（静态）
- 证据: 相关函数和入口存在，未实际点击联调。

12. legacy timbre 迁移功能保持
- 状态: PASS（静态）
- 证据: `migrateLegacyTimbresToV2` 保留，导入时仍调用 `syncTimbresWithServer()`（`peiying/Unitale/index.html:3138`）。

13. Prompt 管理保存/重置
- 状态: PASS（静态）
- 证据: `savePrompt/resetPrompt` 路径正常（`peiying/Unitale/index.html:4238`, `peiying/Unitale/index.html:4243`）。

14. 脚本语法有效
- 状态: PASS（自动检查）
- 证据: `node --check` 通过。

## 4. Prompt 适配复核（当前是否适合）

### 4.1 结论
- 结论: **基本适配，可用于当前项目**。
- 说明: 主要结构已对齐（无 intensity、有 `${emotionList}`、台词对象字段已更新）。

### 4.2 建议优化点（本轮不改代码）
1. 建议 A
- 问题: 默认 Prompt 仍写 “IndexTTS” 表述。
- 位置: `peiying/Unitale/index.html:1062`
- 建议: 改为 “v2 参考音频情绪控制” 相关表述，避免语义滞后。

2. 建议 B
- 问题: Prompt 管理页“可用变量”提示未列出 `${emotionList}`、`${filterSection}`。
- 位置: `peiying/Unitale/index.html:769`
- 建议: 增加这两个变量，降低自定义 Prompt 漏填风险。

3. 建议 C
- 问题: 文案写“旁白通常选择平静”，但系统是动态情绪标签（常见 `default`）。
- 位置: `peiying/Unitale/index.html:1075`
- 建议: 改为“旁白优先使用该角色可用默认情绪（通常 default）”。

## 5. 下一轮联调执行单（仍不改代码）
1. 角色A创建 `happy/sad` 两个 voice 并绑定不同 ref asset，逐条生成听感对比。
2. 覆盖三条路由: 显式 `voiceId`、自动 `role#emotion`、direct reference 回退。
3. 导入 `schema=2` 文件确认拒绝；导入 `schema=3` 文件确认恢复并可合成。
4. 批量生成 20+ 台词，记录失败率、报错文本、是否卡顿/重复告警。

## 6. 结论与边界
- 本轮结论基于“静态可验证 + 自动语法检查”。
- 真实听感差异、服务端命中一致性、批量稳定性需你本地启动后端后完成联调复核。
