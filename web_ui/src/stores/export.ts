import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useLibrariesStore } from '@/stores/libraries'
import { useProVoiceStore } from '@/stores/pro_voice'
import { useProTaskStore } from '@/stores/pro_task'
import { useIndexedDB } from '@/composables/useIndexedDB'
import { useAudioEngine } from '@/composables/useAudioEngine'
import { bufferToWave, downloadBlob, blobToBase64, base64ToBlob, mergeAudioBlobs } from '@/utils/audio'
import { isDialogue } from '@/types'
import type { ExportSchema, ScriptEntry, ScriptLine, ProjectSnapshot } from '@/types'

export const useExportStore = defineStore('export', () => {
  const project = useProjectStore()
  const libs = useLibrariesStore()
  const voices = useProVoiceStore()
  const taskStore = useProTaskStore()
  const idb = useIndexedDB()
  const engine = useAudioEngine()

  const isExporting = ref(false)
  const isImporting = ref(false)
  const isRenderingAudio = ref(false)
  const isMergingTaskAudio = ref(false)
  const progressMessage = ref('')

  function setMessage(message: string) {
    progressMessage.value = message
  }

  async function saveToBrowser() {
    setMessage('正在保存到浏览器...')
    try {
      const snapshot = {
        ...project.toSerializable(),
        sfxLibrary: libs.sfxLibrary,
        bgmLibrary: libs.bgmLibrary,
        timbres: libs.timbres,
        filterLibrary: libs.filterLibrary,
        v2Voices: voices.voices,
        v2Assets: voices.assets,
      } as ProjectSnapshot
      await idb.saveProject(snapshot)

      const items: { key: string; blob: Blob }[] = []
      for (const [key, blob] of libs.localFileMap.entries()) {
        items.push({ key, blob })
      }
      if (items.length > 0) {
        await idb.saveAssetsBatch(items)
      }

      setMessage('已保存到浏览器')
    } catch (e) {
      setMessage(`保存失败: ${(e as Error).message}`)
    }
  }

  async function loadFromBrowser() {
    setMessage('正在从浏览器加载...')
    try {
      const snapshot = await idb.loadProject()
      if (!snapshot) {
        setMessage('没有找到已保存的项目')
        return
      }

      project.rawScript = snapshot.rawScript || ''
      project.rawAnalysisResult = snapshot.rawAnalysisResult || ''
      project.characters = snapshot.characters || []
      project.scriptLines = (snapshot.scriptLines || []) as ScriptEntry[]

      libs.sfxLibrary = snapshot.sfxLibrary || []
      libs.bgmLibrary = snapshot.bgmLibrary || []
      libs.timbres = snapshot.timbres || []
      libs.filterLibrary = snapshot.filterLibrary || []
      voices.voices = snapshot.v2Voices || []
      voices.assets = snapshot.v2Assets || []

      const allAssets = await idb.loadAllAssets()
      for (const [key, blob] of allAssets.entries()) {
        libs.localFileMap.set(key, blob)
      }

      setMessage('已从浏览器恢复项目')
    } catch (e) {
      setMessage(`加载失败: ${(e as Error).message}`)
    }
  }

  async function buildExportSchema(): Promise<ExportSchema> {
    return {
      version: '3.0',
      schema_version: 3,
      timestamp: new Date().toISOString(),
      libraries: {
        sfx: await Promise.all(libs.sfxLibrary.map(async s => {
          const blob = libs.getFileBlob(s.filename)
          if (blob) {
            return { ...s, _fileData: await blobToBase64(blob), _mimeType: blob.type }
          }
          return { ...s }
        })),
        bgm: await Promise.all(libs.bgmLibrary.map(async b => {
          const blob = libs.getFileBlob(b.filename)
          if (blob) {
            return { ...b, _fileData: await blobToBase64(blob), _mimeType: blob.type }
          }
          return { ...b }
        })),
        timbres: await Promise.all(libs.timbres.map(async t => {
          const blob = libs.getFileBlob(t.refPath)
          if (blob) {
            return { ...t, _fileData: await blobToBase64(blob), _mimeType: blob.type }
          }
          return { ...t }
        })),
        voices: voices.voices,
        assets: voices.assets,
        filters: libs.filterLibrary,
      },
      project: {
        rawScript: project.rawScript,
        rawAnalysisResult: project.rawAnalysisResult,
        characters: project.characters,
        scriptLines: await Promise.all(project.scriptLines.map(async line => {
          if (isDialogue(line) && line.audioUrl) {
            try {
              const res = await fetch(line.audioUrl)
              const blob = await res.blob()
              return { ...line, audioBase64: await blobToBase64(blob) }
            } catch {
              return line
            }
          }
          return line
        })),
      },
    }
  }

  async function exportProjectFile() {
    isExporting.value = true
    setMessage('正在导出工程文件...')
    try {
      const schema = await buildExportSchema()
      const blob = new Blob([JSON.stringify(schema, null, 2)], { type: 'application/json' })
      downloadBlob(blob, `cosyvoice_project_${Date.now()}.json`)
      setMessage('工程文件已导出')
    } catch (e) {
      setMessage(`导出失败: ${(e as Error).message}`)
    } finally {
      isExporting.value = false
    }
  }

  async function importProjectFile(file: File) {
    isImporting.value = true
    setMessage('正在导入工程文件...')
    try {
      const schema = JSON.parse(await file.text()) as ExportSchema

      if (schema.libraries) {
        libs.sfxLibrary = (schema.libraries.sfx || []).map(s => {
          if (s._fileData) libs.localFileMap.set(s.filename, base64ToBlob(s._fileData))
          const { _fileData: _, _mimeType: __, ...rest } = s
          return rest
        })
        libs.bgmLibrary = (schema.libraries.bgm || []).map(b => {
          if (b._fileData) libs.localFileMap.set(b.filename, base64ToBlob(b._fileData))
          const { _fileData: _, _mimeType: __, ...rest } = b
          return rest
        })
        libs.timbres = (schema.libraries.timbres || []).map(t => {
          if (t._fileData) libs.localFileMap.set(t.refPath, base64ToBlob(t._fileData))
          const { _fileData: _, _mimeType: __, ...rest } = t
          return rest
        })
        libs.filterLibrary = schema.libraries.filters || []
        voices.voices = schema.libraries.voices || []
        voices.assets = schema.libraries.assets || []
      }

      if (schema.project) {
        project.rawScript = schema.project.rawScript || ''
        project.rawAnalysisResult = schema.project.rawAnalysisResult || ''
        project.characters = schema.project.characters || []
        project.scriptLines = (schema.project.scriptLines || []).map(line => {
          if (isDialogue(line) && (line as ScriptLine & { audioBase64?: string }).audioBase64) {
            const typed = line as ScriptLine & { audioBase64?: string }
            const blob = base64ToBlob(typed.audioBase64!)
            const url = URL.createObjectURL(blob)
            const { audioBase64: _, ...rest } = typed
            return { ...rest, audioUrl: url, isGenerating: false } as ScriptLine
          }
          return line
        }) as ScriptEntry[]
      }

      setMessage('工程文件已导入')
    } catch (e) {
      setMessage(`导入失败: ${(e as Error).message}`)
    } finally {
      isImporting.value = false
    }
  }

  async function exportRenderedAudio() {
    isRenderingAudio.value = true
    setMessage('正在渲染工程音频...')
    try {
      const buffer = await engine.renderOffline(project.scriptLines)
      if (!buffer) {
        setMessage('没有可渲染的音频行')
        return
      }
      downloadBlob(bufferToWave(buffer), `cosyvoice_render_${Date.now()}.wav`)
      setMessage('工程音频已导出')
    } catch (e) {
      setMessage(`渲染失败: ${(e as Error).message}`)
    } finally {
      isRenderingAudio.value = false
    }
  }

  function exportSrtFile() {
    const lines = project.scriptLines.filter(l => isDialogue(l)) as ScriptLine[]
    if (lines.length === 0) {
      setMessage('没有可导出的台词行')
      return
    }
    let srtContent = ''
    let timeOffset = 0
    let index = 1
    for (const line of lines) {
      const dur = line.break_duration || 0.5
      const textDur = Math.max(1, line.text.length * 0.5)
      const startMs = timeOffset * 1000
      const endMs = (timeOffset + textDur) * 1000
      srtContent += `${index}\n${formatSrtTime(startMs)} --> ${formatSrtTime(endMs)}\n${line.role}: ${line.text}\n\n`
      timeOffset += textDur + dur
      index++
    }
    downloadBlob(new Blob([srtContent], { type: 'text/plain' }), `cosyvoice_subtitle_${Date.now()}.srt`)
    setMessage('字幕文件已导出')
  }

  function exportTaskPlanFile() {
    const blob = new Blob([JSON.stringify(taskStore.serializeTaskPlan(), null, 2)], { type: 'application/json' })
    downloadBlob(blob, `cosyvoice_task_plan_${Date.now()}.json`)
    setMessage('任务计划已导出')
  }

  async function importTaskPlanFile(file: File) {
    setMessage('正在导入任务计划...')
    try {
      taskStore.restoreTaskPlan(JSON.parse(await file.text()))
      setMessage('任务计划已导入')
    } catch (e) {
      setMessage(`任务计划导入失败: ${(e as Error).message}`)
    }
  }

  async function exportMergedTaskAudio() {
    isMergingTaskAudio.value = true
    setMessage('正在合并批量任务结果...')
    try {
      const rows = taskStore.taskRows.filter(row => row.status === 'done' && row.audio_url)
      if (rows.length === 0) {
        setMessage('没有已完成的批量结果可导出')
        return
      }
      const blobs = await Promise.all(rows.map(row => taskStore.getClient().getAuthedAudioBlob(row.audio_url!)))
      downloadBlob(await mergeAudioBlobs(blobs), `cosyvoice_batch_merged_${Date.now()}.wav`)
      setMessage('批量结果已合并导出')
    } catch (e) {
      setMessage(`合并失败: ${(e as Error).message}`)
    } finally {
      isMergingTaskAudio.value = false
    }
  }

  function restoreTaskDraft() {
    const ok = taskStore.loadTaskPlanFromStorage()
    setMessage(ok ? '已恢复浏览器中的任务草稿' : '没有找到可恢复的任务草稿')
  }

  return {
    isExporting,
    isImporting,
    isRenderingAudio,
    isMergingTaskAudio,
    progressMessage,
    saveToBrowser,
    loadFromBrowser,
    exportProjectFile,
    importProjectFile,
    exportRenderedAudio,
    exportSrtFile,
    exportTaskPlanFile,
    importTaskPlanFile,
    exportMergedTaskAudio,
    restoreTaskDraft,
  }
})

function formatSrtTime(ms: number): string {
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  const mill = Math.floor(ms % 1000)
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad3(mill)}`
}

function pad(n: number): string {
  return n.toString().padStart(2, '0')
}

function pad3(n: number): string {
  return n.toString().padStart(3, '0')
}
