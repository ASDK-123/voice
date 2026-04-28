// 资源库数据模型

/** 音效条目 */
export interface SfxItem {
    id: string
    /** 显示名称 */
    name: string
    /** 描述说明 */
    description: string
    /** 对应 localFileMap 中的 key（文件名） */
    filename: string
    /** 是否启用（参与 AI 分析） */
    enabled: boolean
}

/** BGM 条目 */
export interface BgmItem {
    id: string
    name: string
    description: string
    filename: string
    enabled: boolean
}

/** 音色条目（本地参考音频绑定） */
export interface TimbreItem {
    id: string
    /** 音色名称 */
    name: string
    /** 描述说明 */
    description: string
    /** 参考音频文件名（在 localFileMap 中的 key） */
    refPath: string
}

/** 滤波器类型 */
export type FilterType =
    | 'lowpass'
    | 'highpass'
    | 'bandpass'
    | 'lowshelf'
    | 'highshelf'
    | 'peaking'
    | 'notch'
    | 'allpass'
    | 'distortion'

/** 滤波器条目 */
export interface FilterItem {
    id: string
    name: string
    description: string
    /** 滤波器类型 */
    type: FilterType
    /** 截止/中心频率 (Hz) */
    frequency: number
    /** 品质因数 */
    Q: number
    /** 增益 (dB) 或失真量 */
    gain: number
    /** 是否启用（参与 AI 分析） */
    enabled: boolean
}

/** 创建默认 SFX */
export function createDefaultSfx(overrides: Partial<SfxItem> = {}): SfxItem {
    return {
        id: `sfx_${Date.now()}`,
        name: '',
        description: '',
        filename: '',
        enabled: true,
        ...overrides,
    }
}

/** 创建默认 BGM */
export function createDefaultBgm(overrides: Partial<BgmItem> = {}): BgmItem {
    return {
        id: `bgm_${Date.now()}`,
        name: '',
        description: '',
        filename: '',
        enabled: true,
        ...overrides,
    }
}

/** 创建默认滤波器 */
export function createDefaultFilter(overrides: Partial<FilterItem> = {}): FilterItem {
    return {
        id: `filter_${Date.now()}`,
        name: '',
        description: '',
        type: 'lowpass',
        frequency: 1000,
        Q: 1,
        gain: 0,
        enabled: true,
        ...overrides,
    }
}
