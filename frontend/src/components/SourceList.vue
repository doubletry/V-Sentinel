<template>
  <div class="source-list">
    <!-- Top section: Video Sources -->
    <div class="section sources-section">
      <div class="list-header">
        <span class="list-title">{{ t('sourceList.title') }}</span>
        <el-button type="primary" size="small" @click="showAddDialog = true">
          <el-icon><Plus /></el-icon>
          {{ t('common.add') }}
        </el-button>
      </div>

      <el-scrollbar class="sources-scroll">
        <div
          v-for="source in store.sources"
          :key="source.id"
          class="source-item"
          draggable="true"
          @dragstart="onDragStart($event, source)"
        >
          <div class="source-info">
            <div class="source-name">
              <el-badge
                :type="store.isRunning(source.id) ? 'success' : 'info'"
                is-dot
                class="status-dot"
              />
              {{ source.name }}
            </div>
            <div class="source-url">{{ getSourceRoute(source) }}</div>
          </div>
          <div class="source-actions">
            <el-button
              size="small"
              :type="store.isRunning(source.id) ? 'warning' : 'success'"
              :loading="actionLoading[source.id]"
              @click="toggleAnalysis(source)"
            >
              {{ store.isRunning(source.id) ? t('sourceList.stop') : t('sourceList.analyze') }}
            </el-button>
            <el-button
              size="small"
              :title="t('common.edit')"
              @click="openEditDialog(source)"
            >
              <el-icon><EditPen /></el-icon>
            </el-button>
            <el-button
              size="small"
              type="danger"
              :title="t('common.delete')"
              @click="confirmDelete(source)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>

        <div v-if="!store.sources.length" class="empty-hint">
          <el-icon :size="32" color="#555"><VideoCamera /></el-icon>
          <span>{{ t('sourceList.noSources') }}</span>
        </div>
      </el-scrollbar>
    </div>

    <!-- Bottom section: Result Streams (auto-detected) -->
    <div class="section results-section">
      <div class="list-header results-header">
        <span class="list-title">{{ t('sourceList.resultStreams') }}</span>
      </div>

      <el-scrollbar class="sources-scroll">
        <div
          v-for="rs in resultStreams"
          :key="rs.id"
          class="source-item result-item"
          draggable="true"
          @dragstart="onResultDragStart($event, rs)"
        >
          <div class="source-info">
            <div class="source-name result-name">
              <el-badge type="success" is-dot class="status-dot" />
              {{ rs.name }}
            </div>
            <div class="source-url">{{ rs.streamPath }}</div>
          </div>
        </div>

        <div v-if="!resultStreams.length" class="empty-hint">
          <el-icon :size="24" color="#555"><Monitor /></el-icon>
          <span>{{ t('sourceList.noResultStreams') }}</span>
        </div>
      </el-scrollbar>
    </div>

    <!-- Add Source Dialog -->
    <el-dialog
      v-model="showAddDialog"
      :title="t('sourceList.addSource')"
      width="400px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="80px" @submit.prevent="addSource">
        <el-form-item :label="t('sourceList.name')" required>
          <el-input v-model="form.name" :placeholder="t('sourceList.name')" />
        </el-form-item>
        <el-form-item :label="t('sourceList.routePath')" required>
          <el-input
            v-model="form.route_path"
            :placeholder="t('sourceList.routePlaceholder')"
          />
        </el-form-item>
        <div class="route-hint">{{ t('sourceList.routeHint', { base: appSettingsStore.mediamtxRtspAddr }) }}</div>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="addLoading" @click="addSource">
          {{ t('common.add') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Edit Source Dialog -->
    <el-dialog
      v-model="showEditDialog"
      :title="t('sourceList.editSource')"
      width="400px"
      :close-on-click-modal="false"
    >
      <el-form :model="editForm" label-width="80px" @submit.prevent="saveEdit">
        <el-form-item :label="t('sourceList.name')" required>
          <el-input v-model="editForm.name" :placeholder="t('sourceList.name')" />
        </el-form-item>
        <el-form-item :label="t('sourceList.routePath')" required>
          <el-input
            v-model="editForm.route_path"
            :placeholder="t('sourceList.routePlaceholder')"
          />
        </el-form-item>
        <div class="route-hint">{{ t('sourceList.routeHint', { base: appSettingsStore.mediamtxRtspAddr }) }}</div>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="editLoading" @click="saveEdit">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import ElMessage from 'element-plus/es/components/message/index'
import ElMessageBox from 'element-plus/es/components/message-box/index'
import { useSourceStore } from '../stores/source.js'
import { useAppSettingsStore } from '../stores/appSettings.js'
import { buildRtspUrl, extractRoutePath, normalizeRoutePath } from '../utils/sourceAddress.js'

const store = useSourceStore()
const appSettingsStore = useAppSettingsStore()
const { t } = useI18n()
const showAddDialog = ref(false)
const showEditDialog = ref(false)
const addLoading = ref(false)
const editLoading = ref(false)
const actionLoading = reactive({})
const editingSourceId = ref('')

const form = reactive({ name: '', route_path: '' })
const editForm = reactive({ name: '', route_path: '' })

/**
 * Computed result streams from running analysis sources.
 * Each running source automatically gets a corresponding result stream
 * with the path `{route}_processed`.
 */
const resultStreams = computed(() => {
  return store.sources
    .filter((s) => store.isRunning(s.id))
    .map((s) => {
      const route = getSourceRoute(s)
      return {
        id: `result_${s.id}`,
        name: `${s.name} (${t('sourceList.resultSuffix')})`,
        streamPath: `${route}_processed`,
        isResult: true,
        originalSourceId: s.id,
      }
    })
})

function onDragStart(event, source) {
  event.dataTransfer.setData('source-id', source.id)
  event.dataTransfer.effectAllowed = 'copy'
}

function onResultDragStart(event, resultStream) {
  // Pass virtual result stream data for drag-and-drop into the grid
  event.dataTransfer.setData('result-stream', JSON.stringify(resultStream))
  event.dataTransfer.effectAllowed = 'copy'
}

async function addSource() {
  const routePath = normalizeRoutePath(form.route_path)
  const rtspUrl = buildRtspUrl(
    appSettingsStore.mediamtxRtspAddr,
    routePath,
    appSettingsStore.mediamtxUsername,
    appSettingsStore.mediamtxPassword
  )

  if (!form.name || !routePath) {
    ElMessage.warning(t('sourceList.fillAllFields'))
    return
  }
  if (!rtspUrl) {
    ElMessage.warning(t('sourceList.missingRtspBase'))
    return
  }

  addLoading.value = true
  try {
    await store.createSource({ name: form.name, rtsp_url: rtspUrl })
    showAddDialog.value = false
    form.name = ''
    form.route_path = ''
    ElMessage.success(t('sourceList.sourceAdded'))
  } catch (err) {
    ElMessage.error(err.message || t('sourceList.failedToAdd'))
  } finally {
    addLoading.value = false
  }
}

async function toggleAnalysis(source) {
  actionLoading[source.id] = true
  try {
    if (store.isRunning(source.id)) {
      await store.stopProcessing(source.id)
    } else {
      await store.startProcessing(source.id)
    }
  } finally {
    delete actionLoading[source.id]
  }
}

function openEditDialog(source) {
  editingSourceId.value = source.id
  editForm.name = source.name
  editForm.route_path = extractRoutePath(source.rtsp_url, appSettingsStore.mediamtxRtspAddr)
  showEditDialog.value = true
}

async function saveEdit() {
  if (!editingSourceId.value) return

  const routePath = normalizeRoutePath(editForm.route_path)
  const rtspUrl = buildRtspUrl(
    appSettingsStore.mediamtxRtspAddr,
    routePath,
    appSettingsStore.mediamtxUsername,
    appSettingsStore.mediamtxPassword
  )

  if (!editForm.name || !routePath) {
    ElMessage.warning(t('sourceList.fillAllFields'))
    return
  }
  if (!rtspUrl) {
    ElMessage.warning(t('sourceList.missingRtspBase'))
    return
  }

  editLoading.value = true
  try {
    await store.updateSource(editingSourceId.value, {
      name: editForm.name,
      rtsp_url: rtspUrl,
    })
    showEditDialog.value = false
    ElMessage.success(t('sourceList.sourceUpdated'))
  } catch (err) {
    ElMessage.error(err.message || t('sourceList.failedToUpdate'))
  } finally {
    editLoading.value = false
  }
}

async function confirmDelete(source) {
  try {
    await ElMessageBox.confirm(
      t('sourceList.deleteConfirmMessage', { name: source.name }),
      t('sourceList.deleteConfirmTitle'),
      {
        type: 'warning',
        confirmButtonText: t('common.delete'),
        cancelButtonText: t('common.cancel'),
      }
    )
    await store.deleteSource(source.id)
    ElMessage.success(t('sourceList.deleted'))
  } catch (_) {
    // User cancelled
  }
}

function getSourceRoute(source) {
  return extractRoutePath(source.rtsp_url, appSettingsStore.mediamtxRtspAddr) || source.rtsp_url
}

onMounted(async () => {
  if (!appSettingsStore.loaded) {
    await appSettingsStore.fetchSettings().catch(() => {
      // Keep fallback defaults when settings API is unavailable.
    })
  }
})
</script>

<style scoped>
.source-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1a1a2e;
  border-right: 1px solid #333;
}

.section {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.sources-section {
  flex: 1;
  overflow: hidden;
}

.results-section {
  flex: 0 0 auto;
  max-height: 40%;
  border-top: 2px solid #333;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.results-header {
  background: rgba(103, 194, 58, 0.06);
}

.list-title {
  font-size: 14px;
  font-weight: 600;
  color: #ccc;
}

.sources-scroll {
  flex: 1;
}

.source-item {
  padding: 10px 12px;
  border-bottom: 1px solid #222;
  cursor: grab;
  transition: background 0.15s;
}

.source-item:hover {
  background: rgba(64, 158, 255, 0.08);
}

.result-item {
  background: rgba(103, 194, 58, 0.03);
}

.result-item:hover {
  background: rgba(103, 194, 58, 0.08);
}

.source-name {
  font-size: 13px;
  font-weight: 600;
  color: #ddd;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.result-name {
  color: #a3d977;
}

.source-url {
  font-size: 11px;
  color: #666;
  word-break: break-all;
}

.route-hint {
  margin-top: 2px;
  color: #7587af;
  font-size: 12px;
}

.source-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: nowrap;
}

.source-actions :deep(.el-button span) {
  white-space: nowrap;
}

.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px;
  gap: 8px;
  color: #555;
  font-size: 13px;
}
</style>
