// 工程存档数据模型

import type { ScriptEntry } from './script'
import type { SfxItem, BgmItem, TimbreItem, FilterItem } from './library'
import type { Voice, Asset } from './voice'

/** 角色 */
export interface Character {
    id: string
    name: string
    /** v2 voice 绑定（"角色#情绪"格式） */
    voiceId: string
    /** legacy 参考音频文件路径（保留向后兼容） */
    voiceFile: string
}

/** 带文件数据的资源（导出/导入用） */
export interface LibraryItemWithFile {
    /** Base64 编码的文件数据 */
    _fileData?: string
    /** MIME 类型 */
    _mimeType?: string
}

/** 工程导出格式 (Schema v3) */
export interface ExportSchema {
    version: '3.0'
    schema_version: 3
    timestamp: string

    libraries: {
        sfx: (SfxItem & LibraryItemWithFile)[]
        bgm: (BgmItem & LibraryItemWithFile)[]
        timbres: (TimbreItem & LibraryItemWithFile)[]
        voices: Voice[]
        assets: Asset[]
        filters: FilterItem[]
    }

    project: {
        rawScript: string
        rawAnalysisResult: string
        characters: Character[]
        scriptLines: (ScriptEntry & { audioBase64?: string })[]
    }
}

/** 项目快照（IndexedDB 持久化用） */
export interface ProjectSnapshot {
    rawScript: string
    rawAnalysisResult: string
    characters: Character[]
    scriptLines: ScriptEntry[]
    sfxLibrary: SfxItem[]
    bgmLibrary: BgmItem[]
    timbres: TimbreItem[]
    filterLibrary: FilterItem[]
    v2Voices: Voice[]
    v2Assets: Asset[]
}

/** 创建默认角色 */
export function createDefaultCharacter(name: string): Character {
    return {
        id: `char_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`,
        name,
        voiceId: '',
        voiceFile: '',
    }
}
