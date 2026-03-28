<template>
  <div class="video-grid-container">
    <!-- Toolbar -->
    <div class="grid-toolbar">
      <span class="toolbar-label">{{ t('common.layout') }}:</span>
      <el-button-group>
        <el-button
          v-for="layout in layouts"
          :key="layout.cols"
          :type="currentCols === layout.cols ? 'primary' : 'default'"
          size="small"
          @click="setLayout(layout.cols)"
        >
          {{ t(layout.labelKey) }}
        </el-button>
      </el-button-group>
    </div>

    <!-- Grid -->
    <div
      class="video-grid"
      :style="gridStyle"
    >
      <div
        v-for="(_, cellIdx) in totalCells"
        :key="cellIdx"
        class="grid-cell"
        :class="{ 'has-source': !!assignments[cellIdx], 'drag-over': dragOverCell === cellIdx }"
        @dragover.prevent="dragOverCell = cellIdx"
        @dragleave="dragOverCell = null"
        @drop.prevent="onDrop($event, cellIdx)"
      >
        <template v-if="assignments[cellIdx]">
          <!-- Occupied cell -->
          <VideoPlayer
            :stream-path="assignments[cellIdx].streamPath || getStreamPath(assignments[cellIdx])"
            :label="assignments[cellIdx].name"
          />
          <div class="cell-controls">
            <el-button
              size="small"
              :type="roiPreviewCellIndex === cellIdx ? 'info' : 'default'"
              @click="toggleRoiPreview(cellIdx)"
            >
              <el-icon><View /></el-icon>
              {{ roiPreviewCellIndex === cellIdx ? t('videoGrid.hideRoi') : t('videoGrid.showRoi') }}
            </el-button>
            <el-button
              size="small"
              :type="roiCellIndex === cellIdx ? 'warning' : 'default'"
              @click="toggleRoiEditor(cellIdx)"
            >
              <el-icon><Edit /></el-icon>
              {{ t('videoGrid.editRoi') }}
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="removeCell(cellIdx)"
            >
              <el-icon><Close /></el-icon>
              {{ t('videoGrid.removeSource') }}
            </el-button>
          </div>

          <RoiDrawer
            v-if="roiCellIndex === cellIdx"
            :source="assignments[cellIdx]"
            :read-only="false"
            @close="roiCellIndex = null"
          />

          <RoiDrawer
            v-else-if="roiPreviewCellIndex === cellIdx"
            :source="assignments[cellIdx]"
            :read-only="true"
            @close="roiPreviewCellIndex = null"
          />
        </template>
        <template v-else>
          <!-- Empty cell / drop target -->
          <div class="drop-target">
            <el-icon :size="32" color="#555"><Plus /></el-icon>
            <span>{{ t('videoGrid.dropHere') }}</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourceStore } from '../stores/source.js'
import { useAppSettingsStore } from '../stores/appSettings.js'
import VideoPlayer from './VideoPlayer.vue'
import RoiDrawer from './RoiDrawer.vue'
import { extractRoutePath } from '../utils/sourceAddress.js'

const GRID_LAYOUT_STORAGE_KEY = 'v-sentinel.layout.cols'
const ALLOWED_LAYOUTS = [1, 2, 3, 4]

function loadInitialLayout() {
  if (typeof window === 'undefined') {
    return 2
  }

  const raw = Number(window.localStorage.getItem(GRID_LAYOUT_STORAGE_KEY))
  return ALLOWED_LAYOUTS.includes(raw) ? raw : 2
}

const store = useSourceStore()
const appSettingsStore = useAppSettingsStore()
const { t } = useI18n()
const currentCols = ref(loadInitialLayout())
const roiCellIndex = ref(null)
const roiPreviewCellIndex = ref(null)
const dragOverCell = ref(null)

const layouts = [
  { cols: 1, labelKey: 'videoGrid.layout1' },
  { cols: 2, labelKey: 'videoGrid.layout4' },
  { cols: 3, labelKey: 'videoGrid.layout9' },
  { cols: 4, labelKey: 'videoGrid.layout16' },
]

const totalCells = computed(() => currentCols.value * currentCols.value)

const gridStyle = computed(() => ({
  display: 'grid',
  gridTemplateColumns: `repeat(${currentCols.value}, 1fr)`,
  gridTemplateRows: `repeat(${currentCols.value}, minmax(0, 1fr))`,
  height: '100%',
  gap: '4px',
  flex: 1,
}))

const assignments = computed(() => store.gridAssignments)

function setLayout(cols) {
  if (!ALLOWED_LAYOUTS.includes(cols)) return
  currentCols.value = cols

  if (typeof window !== 'undefined') {
    window.localStorage.setItem(GRID_LAYOUT_STORAGE_KEY, String(cols))
  }
}

function getStreamPath(source) {
  return extractRoutePath(source.rtsp_url, appSettingsStore.mediamtxRtspAddr) || source.id
}

function toggleRoiEditor(cellIdx) {
  const opening = roiCellIndex.value !== cellIdx
  roiCellIndex.value = opening ? cellIdx : null
  if (opening) {
    roiPreviewCellIndex.value = null
  }
}

function toggleRoiPreview(cellIdx) {
  const opening = roiPreviewCellIndex.value !== cellIdx
  roiPreviewCellIndex.value = opening ? cellIdx : null
  if (opening && roiCellIndex.value === cellIdx) {
    roiCellIndex.value = null
  }
}

function removeCell(cellIdx) {
  store.removeFromCell(cellIdx)
  if (roiCellIndex.value === cellIdx) roiCellIndex.value = null
  if (roiPreviewCellIndex.value === cellIdx) roiPreviewCellIndex.value = null
}

function onDrop(event, cellIdx) {
  dragOverCell.value = null
  const sourceId = event.dataTransfer.getData('source-id')
  if (!sourceId) return
  const source = store.sources.find((s) => s.id === sourceId)
  if (source) {
    store.assignToCell(cellIdx, source)
  }
}
</script>

<style scoped>
.video-grid-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d0d1a;
}

.grid-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.toolbar-label {
  color: #888;
  font-size: 13px;
  white-space: nowrap;
}

.video-grid {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 4px;
}

.grid-cell {
  position: relative;
  background: #111;
  border: 2px solid #333;
  border-radius: 4px;
  overflow: hidden;
  min-height: 0;
  transition: border-color 0.2s;
}

.grid-cell.drag-over {
  border-color: #409EFF;
  background: rgba(64, 158, 255, 0.08);
}

.grid-cell.has-source {
  border-color: #555;
}

.drop-target {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #555;
  font-size: 13px;
}

.cell-controls {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  z-index: 10;
}

.cell-controls :deep(.el-button span) {
  white-space: nowrap;
}
</style>
