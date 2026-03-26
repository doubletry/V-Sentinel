import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { sourcesApi, processorApi } from '../api/index.js'
import { ElMessage } from 'element-plus'

export const useSourceStore = defineStore('source', () => {
  const sources = ref([])
  const loading = ref(false)
  const runningSourceIds = ref(new Set())

  // Grid cell assignments: cellIndex -> source
  const gridAssignments = ref({})

  const isRunning = computed(() => (sourceId) => runningSourceIds.value.has(sourceId))

  async function fetchSources() {
    loading.value = true
    try {
      sources.value = await sourcesApi.list()
    } catch (err) {
      ElMessage.error(`Failed to load sources: ${err.message}`)
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
      ElMessage.success('Analysis started')
    } catch (err) {
      ElMessage.error(`Failed to start: ${err.message}`)
    }
  }

  async function stopProcessing(sourceId) {
    try {
      await processorApi.stop(sourceId)
      runningSourceIds.value.delete(sourceId)
      ElMessage.success('Analysis stopped')
    } catch (err) {
      ElMessage.error(`Failed to stop: ${err.message}`)
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
    gridAssignments,
    isRunning,
    fetchSources,
    createSource,
    updateSource,
    deleteSource,
    startProcessing,
    stopProcessing,
    syncProcessorStatus,
    assignToCell,
    removeFromCell,
  }
})
