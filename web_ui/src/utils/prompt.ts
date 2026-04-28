// 默认 Prompt 模板与动态构建
// 将原 index.html 的 prompt 逻辑模块化
// P6: 情绪列表改为动态注入，不再依赖静态目录

import type { SfxItem, BgmItem, FilterItem } from '@/types'

// ── 动态区块构建 ──

/** 构建音效库描述区块 */
function buildSfxSection(sfxList: SfxItem[]): string {
    const enabled = sfxList.filter(s => s.enabled !== false)
    if (enabled.length > 0) {
        const items = enabled.map(s => `- ${s.name}: ${s.description}`).join('\n')
        return `# 音效库 (Sound Effects)
你可以使用以下音效素材，请根据剧情需要插入：
${items}
**注意：必须严格使用列表中的名称，严禁编造不存在的音效。且绝对禁止使用 BGM 库中的名称。**`
    }
    return `# 音效库 (Sound Effects)
当前音效库为空。
**注意：请勿生成任何 'sfx' 字段。**`
}

/** 构建 BGM 库描述区块 */
function buildBgmSection(bgmList: BgmItem[]): string {
    const enabled = bgmList.filter(b => b.enabled !== false)
    if (enabled.length > 0) {
        const items = enabled.map(b => `- ${b.name}: ${b.description}`).join('\n')
        return `# 背景音乐库 (Background Music)
现有以下背景音乐素材可用：
${items}

**核心指令：**
1. 必须**逐字匹配**使用列表中的名称。
2. 如果列表中没有适合当前剧情的音乐，**请勿生成** BGM 播放指令。
3. **严禁编造**列表中不存在的 BGM 名称。
4. **绝对禁止**使用 SFX 库中的名称。`
    }
    return `# 背景音乐库 (Background Music)
**当前背景音乐库为空 (EMPTY)。**

**核心指令：**
1. **严禁生成**任何 action="play" 的 BGM 控制块。
2. 你只能生成 action="stop" 的指令（如果需要停止之前的音乐）。
3. 绝对不要编造 BGM 名称。`
}

/** 构建滤波器库描述区块 */
function buildFilterSection(filterList: FilterItem[]): string {
    const enabled = filterList.filter(f => f.enabled !== false)
    if (enabled.length > 0) {
        const items = enabled.map(f => `- ${f.name}: ${f.description}`).join('\n')
        return `# 滤波器库 (Audio Filters)
如果剧情需要特殊音效处理（如电话、水下、回忆），请使用以下滤波器：
${items}
**注意：必须严格使用列表中的名称，如果没有匹配项则不要使用 filter 字段。**`
    }
    return `# 滤波器库 (Audio Filters)
当前滤波器库为空。
**注意：请勿生成任何 filter 字段。**`
}

/** 构建 BGM 示例行（JSON 输出中的第一行） */
function buildBgmExample(bgmList: BgmItem[]): string {
    const enabled = bgmList.filter(b => b.enabled !== false)
    if (enabled.length > 0 && enabled[0]) {
        return `{"type": "bgm", "action": "play", "name": "${enabled[0].name}"},\n  `
    }
    return ''
}

/** 构建 SFX 示例片段（嵌入到台词对象中') */
function buildSfxExample(sfxList: SfxItem[]): string {
    const enabled = sfxList.filter(s => s.enabled !== false)
    if (enabled.length > 0 && enabled[0]) {
        return `, "sfx": [{"name": "${enabled[0].name}", "position": 0.2}]`
    }
    return ''
}

// ── 默认模板 ──

/** 默认 Prompt 模板（包含动态占位符） */
export const DEFAULT_PROMPT_TEMPLATE = `你是 Unitale Studio——AI 有声书制作工具的脚本分析引擎。你的任务是将给定小说内容拆分为台词和旁白，并自动识别每一句台词的角色和情绪。
**注意：生成的结果将直接用于 CosyVoice v2 语音合成系统。情绪标签 (emotion) 必须严格使用下方列出的英文标签，不要自行编造。**

\${sfxSection}

\${bgmSection}

\${filterSection}

# 情绪/风格设置 (Emotion / Style)
请为每一句台词（包括旁白）选择一个最合适的情绪标签。

1. **可用情绪标签 (必须严格使用以下英文标签)**: \${emotionList}
   - **注意**: emotion 字段的值必须是上述列表中的某一个英文标签，**严禁**编造列表之外的值。
   - 旁白通常选择 "default" 或 "calm"，也可根据氛围选择其他标签。
   - 如果列表中没有完全匹配的情绪，请选择最接近的标签。

# 规则

## 1. 拆分与识别
- **完整保留**: 必须完整保留原文内容，不得遗漏、删改或省略任何字句。
- **严禁删改**: **绝对禁止**删除原文中的说话人提示语（如"他低声说"、"笑着问道"）。这些内容必须作为"旁白"单独提取出来。
- **内容提取**: 提取对话内容和所有非对话的旁白。
- **角色识别**: 根据小说内容分析说话人。旁白的角色名统一标记为"旁白"。
- **长度控制**: 文本拆分长度要适中。**避免过碎**（不要把每一句短句都拆成独立一行），也**避免过长**（单行文本建议不超过 50-80 字，过长的旁白请在句号处适当拆分）。
- **旁白处理**: 连续的旁白内容应优先合并，除非中间需要插入音效、有明显的时间跳跃，或合并后长度过长。

## 2. 音效插入 (sfx)
- 如果情节需要（如"摔门而去"、"雷声大作"），且音效库中有对应素材，请在 JSON 对象中添加 \`sfx\` 字段。
- **严格限制**: 只能使用【音效库】中列出的名称。如果库为空或没有匹配项，**绝对不要**添加此字段。
- **禁止混用**: **绝对禁止**在 \`sfx\` 字段中使用【背景音乐库】中的名称。
- **支持多音效**: 一句台词中可以插入多个音效，只要位置合理。
- 格式: \`"sfx": [{"name": "音效名称", "position": 0.5}]\`
- \`position\`: 0.0-1.0 之间的浮点数，表示音效在**台词念白时长内**的插入位置。
- **重要**: \`position\` 计算**不包含** \`break_duration\`（停顿时间）。

## 3. 背景音乐控制 (BGM Control)
- **开头 BGM**: 请**务必**在脚本的最开始尝试匹配并插入一个适合当前氛围的 BGM。
- 当剧情氛围发生变化，需要切换或停止背景音乐时，请插入一个独立的 BGM 控制对象。
- **格式**: \`{"type": "bgm", "action": "play", "name": "BGM名称"}\` 或 \`{"type": "bgm", "action": "stop"}\`
- **严格限制**:
  - \`name\` 字段**必须完全等于**【背景音乐库】中列出的某一个名称。
  - **禁止混用**: **绝对禁止**在 BGM 控制块中使用【音效库】中的名称。
  - 如果【背景音乐库】为空或没有匹配项，**绝对不要**生成播放指令。
- **注意**: 不要将 bgm 字段放在台词对象中，BGM 是独立的控制块。

## 4. 停顿时间
- 分析台词后的剧情节奏，设置该台词结束后的停顿时间（秒）。
- 默认为 0。如果有动作描写、心理活动或需要留白，请设置相应时长（如 0.5, 1.0, 2.0）。

## 5. 音频滤波器 (Filter)
- 如果剧情环境特殊（如"在水下说话"、"电话通话中"、"回忆/内心独白"），且【滤波器库】中有对应效果，请在台词对象中添加 \`filter\` 字段。
- **格式**: \`"filter": "滤波器名称"\`
- **严格限制**: 必须使用【滤波器库】中存在的名称。如果没有匹配项，**不要**生成此字段。
- **特别提醒**: 如果角色是"旁白"，**千万不要**使用滤波器。

## 6. 输出格式
- **严格 JSON**: 输出格式必须是严格的 JSON 数组，不包含任何额外说明或代码块标记。
- **数组元素**: 必须是以下两种对象之一：
  1. **台词对象**: \`{"type": "dialogue", "role_name": "...", "text_content": "...", "emotion": "...", "break_duration": 0, "filter": "...", "sfx": [...]}\`
  2. **BGM 对象**: \`{"type": "bgm", "action": "play", "name": "..."}\` 或 \`{"type": "bgm", "action": "stop"}\`
  - **严禁生成** \`{"type": "sfx", ...}\` 这种独立音效块。音效必须包含在台词对象的 \`sfx\` 字段中。

## 示例

### 输入:
<novel_content>
"别接那个电话！"老李猛地按住了我的手，脸色惨白，"那是昨晚值班的小张打来的。"
我愣住了，看着办公桌上疯狂震动的座机："可是……小张不是今早已经确认死亡了吗？"
"对，"老李的声音在发抖，"所以，别接。如果你接了，他会问你为什么不救他。"
</novel_content>

### 输出:
[
  \${bgmExampleLine}{"type": "dialogue", "role_name": "老李", "text_content": "别接那个电话！", "emotion": "fear", "break_duration": 0},
  {"type": "dialogue", "role_name": "旁白", "text_content": "老李猛地按住了我的手，脸色惨白，", "emotion": "default", "break_duration": 0},
  {"type": "dialogue", "role_name": "老李", "text_content": "那是昨晚值班的小张打来的。", "emotion": "fear", "break_duration": 0.5},
  {"type": "dialogue", "role_name": "旁白", "text_content": "我愣住了，看着办公桌上疯狂震动的座机：", "emotion": "default", "break_duration": 0\${sfxExample}},
  {"type": "dialogue", "role_name": "我", "text_content": "可是……小张不是今早已经确认死亡了吗？", "emotion": "surprise", "break_duration": 0.5},
  {"type": "dialogue", "role_name": "老李", "text_content": "对，", "emotion": "sad", "break_duration": 0},
  {"type": "dialogue", "role_name": "旁白", "text_content": "老李的声音在发抖，", "emotion": "default", "break_duration": 0},
  {"type": "dialogue", "role_name": "老李", "text_content": "所以，别接。如果你接了，他会问你为什么不救他。", "emotion": "fear", "break_duration": 0}
]

# 输入内容

## 小说原文:
<novel_content>
\${rawScript}
</novel_content>`

// ── Prompt 构建 ──

export interface PromptBuildContext {
    rawScript: string
    sfxLibrary: SfxItem[]
    bgmLibrary: BgmItem[]
    filterLibrary: FilterItem[]
    emotionCatalog?: string[]
    customTemplate?: string
}

/**
 * 构建完整的分析 Prompt
 * 根据资源库状态动态填充模板变量
 */
export function buildAnalysisPrompt(ctx: PromptBuildContext): string {
    const template = ctx.customTemplate || DEFAULT_PROMPT_TEMPLATE

    // P6: 优先使用调用方传入的动态情绪目录，无可用时提供基本默认值
    const fallbackEmotions = ['default', 'happy', 'sad', 'calm', 'surprise', 'angry', 'fear', 'disgust']
    const emotionList = (ctx.emotionCatalog && ctx.emotionCatalog.length > 0 ? ctx.emotionCatalog : fallbackEmotions).join(', ')
    const sfxSection = buildSfxSection(ctx.sfxLibrary)
    const bgmSection = buildBgmSection(ctx.bgmLibrary)
    const filterSection = buildFilterSection(ctx.filterLibrary)
    const bgmExampleLine = buildBgmExample(ctx.bgmLibrary)
    const sfxExample = buildSfxExample(ctx.sfxLibrary)

    return template
        .replace(/\$\{emotionList\}/g, emotionList)
        .replace(/\$\{sfxSection\}/g, sfxSection)
        .replace(/\$\{bgmSection\}/g, bgmSection)
        .replace(/\$\{filterSection\}/g, filterSection)
        .replace(/\$\{bgmExampleLine\}/g, bgmExampleLine)
        .replace(/\$\{sfxExample\}/g, sfxExample)
        .replace(/\$\{rawScript\}/g, ctx.rawScript)
}
