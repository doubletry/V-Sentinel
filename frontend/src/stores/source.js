import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { sourcesApi, processorApi } from '../api/index.js'
import ElMessage from 'element-plus/es/components/message/index'
import { i18n } from '../i18n/index.js'

export const useSourceStore = defineStore('source', () => {
  const sources = ref([])
  const loading = ref(false)
  const runningSourceIds = ref(new Set())

  // Grid cell assignments: cellIndex -> source
  const gridAssignments = ref({})

  const isRunning = computed(() => (sourceId) => runningSourceIds.value.has(sourceId))
  const runningCount = computed(() => runningSourceIds.value.size)

  async function fetchSources() {
    loading.value = true
    try {
      sources.value = await sourcesApi.list()
    } catch (err) {
      ElMessage.error(i18n.global.t('sourceList.failedToLoadSources', { message: err.message }))
    } finally {
      loading.value = false
    }
  }

  async function createSource(data) {
    const source = await sourcesApi.create(data)
    sources.value.push(source)
    return source
  }

  async function updateSource(id, data) {
    const updated = await sourcesApi.update(id, data)
    const idx = sources.value.findIndex((s) => s.id === id)
    if (idx !== -1) sources.value[idx] = updated
    return updated
  }

  async function deleteSource(id) {
    await sourcesApi.delete(id)
    sources.value = sources.value.filter((s) => s.id !== id)
    // Remove from grid
    for (const [cell, src] of Object.entries(gridAssignments.value)) {
      if (src.id === id) delete gridAssignments.value[cell]
    }
    runningSourceIds.value.delete(id)
  }

  async function startProcessing(sourceId) {
    try {
      await processorApi.start(sourceId)
      runningSourceIds.value.add(sourceId)
      ElMessage.success(i18n.global.t('sourceList.analysisStarted'))
    } catch (err) {
      ElMessage.error(i18n.global.t('sourceList.failedToStart', { message: err.message }))
    }
  }

  async function stopProcessing(sourceId) {
    try {
      await processorApi.stop(sourceId)
      runningSourceIds.value.delete(sourceId)
      ElMessage.success(i18n.global.t('sourceList.analysisStopped'))
    } catch (err) {
      ElMessage.error(i18n.global.t('sourceList.failedToStop', { message: err.message }))
    }
  }

  async function startAllProcessing() {
    try {
      const result = await processorApi.startAll()
      await syncProcessorStatus()

      if (result.status === 'no_sources') {
        ElMessage.warning(i18n.global.t('service.noSources'))
      } else if (result.status === 'partial') {
        ElMessage.warning(i18n.global.t('service.partialStarted', { started: result.started }))
      } else {
        ElMessage.success(i18n.global.t('service.startedAll', { started: result.started }))
      }

      return result
    } catch (err) {
      ElMessage.error(i18n.global.t('service.startAllFailed', { message: err.message }))
      throw err
    }
  }

  async function stopAllProcessing() {
    try {
      const result = await processorApi.stopAll()
      await syncProcessorStatus()

      if (result.status === 'not_running') {
        ElMessage.info(i18n.global.t('service.notRunning'))
      } else if (result.status === 'partial') {
        ElMessage.warning(i18n.global.t('service.partialStopped', { stopped: result.stopped }))
      } else {
        ElMessage.success(i18n.global.t('service.stoppedAll', { stopped: result.stopped }))
      }

      return result
    } catch (err) {
      ElMessage.error(i18n.global.t('service.stopAllFailed', { message: err.message }))
      throw err
    }
  }

  async function syncProcessorStatus() {
    try {
      const statuses = await processorApi.status()
      const running = new Set(
        statuses.filter((s) => s.status === 'running').map((s) => s.source_id)
      )
      runningSourceIds.value = running
    } catch (_) {
      // Ignore
    }
  }

  function getRunningSourceIdsSnapshot() {
    return Array.from(runningSourceIds.value)
  }

  async function restartProcessing(sourceIds) {
    const targets = Array.from(
      new Set((sourceIds || []).map((item) => String(item || '').trim()).filter(Boolean))
    )

    if (!targets.length) {
      return {
        status: 'not_running',
        restarted: 0,
        stopped: 0,
        failed: [],
      }
    }

    const failed = []
    const stoppedIds = []
    let restarted = 0

    for (const sourceId of targets) {
      try {
        await processorApi.stop(sourceId)
        stoppedIds.push(sourceId)
        runningSourceIds.value.delete(sourceId)
      } catch (err) {
        failed.push({
          source_id: sourceId,
          phase: 'stop',
          reason: err.message,
        })
      }
    }

    for (const sourceId of stoppedIds) {
      try {
        const result = await processorApi.start(sourceId)
        if (result.status === 'started' || result.status === 'already_running') {
          restarted += 1
          runningSourceIds.value.add(sourceId)
        } else {
          failed.push({
            source_id: sourceId,
            phase: 'start',
            reason: result.status || 'unknown',
          })
        }
      } catch (err) {
        failed.push({
          source_id: sourceId,
          phase: 'start',
          reason: err.message,
        })
      }
    }

    await syncProcessorStatus()

    return {
      status: failed.length ? 'partial' : 'restarted',
      restarted,
      stopped: stoppedIds.length,
      failed,
    }
  }

  function assignToCell(cellIndex, source) {
    gridAssignments.value[cellIndex] = source
  }

  function removeFromCell(cellIndex) {
    delete gridAssignments.value[cellIndex]
  }

  return {
    sources,
    loading,
    runningSourceIds,
    runningCount,
    gridAssignments,
    isRunning,
    fetchSources,
    createSource,
    updateSource,
    deleteSource,
    startProcessing,
    stopProcessing,
    startAllProcessing,
    stopAllProcessing,
    syncProcessorStatus,
    getRunningSourceIdsSnapshot,
    restartProcessing,
    assignToCell,
    removeFromCell,
  }
})
