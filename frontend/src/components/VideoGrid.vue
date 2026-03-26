<template>
  <div class="video-grid-container">
    <!-- Toolbar -->
    <div class="grid-toolbar">
      <span class="toolbar-label">Layout:</span>
      <el-button-group>
        <el-button
          v-for="layout in layouts"
          :key="layout.cols"
          :type="currentCols === layout.cols ? 'primary' : 'default'"
          size="small"
          @click="setLayout(layout.cols)"
        >
          {{ layout.label }}
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
              :type="roiCellIndex === cellIdx ? 'warning' : 'default'"
              @click="toggleRoi(cellIdx)"
            >
              <el-icon><Edit /></el-icon>
              ROI
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="removeCell(cellIdx)"
            >
              <el-icon><Close /></el-icon>
            </el-button>
          </div>
          <!-- ROI Drawer overlay -->
          <RoiDrawer
            v-if="roiCellIndex === cellIdx"
            :source="assignments[cellIdx]"
            @close="roiCellIndex = null"
          />
        </template>
        <template v-else>
          <!-- Empty cell / drop target -->
          <div class="drop-target">
            <el-icon :size="32" color="#555"><Plus /></el-icon>
            <span>Drop source here</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useSourceStore } from '../stores/source.js'
import VideoPlayer from './VideoPlayer.vue'
import RoiDrawer from './RoiDrawer.vue'

const store = useSourceStore()
const currentCols = ref(2)
const roiCellIndex = ref(null)
const dragOverCell = ref(null)

const layouts = [
  { cols: 1, label: '1×1' },
  { cols: 2, label: '2×2' },
  { cols: 3, label: '3×3' },
]

const totalCells = computed(() => currentCols.value * currentCols.value)

const gridStyle = computed(() => ({
  display: 'grid',
  gridTemplateColumns: `repeat(${currentCols.value}, 1fr)`,
  gap: '4px',
  flex: 1,
}))

const assignments = computed(() => store.gridAssignments)

function setLayout(cols) {
  currentCols.value = cols
}

function getStreamPath(source) {
  // Derive stream path from RTSP URL
  return source.rtsp_url?.split('/').pop() || source.id
}

function toggleRoi(cellIdx) {
  roiCellIndex.value = roiCellIndex.value === cellIdx ? null : cellIdx
}

function removeCell(cellIdx) {
  store.removeFromCell(cellIdx)
  if (roiCellIndex.value === cellIdx) roiCellIndex.value = null
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
  gap: 8px;
  padding: 8px 12px;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.toolbar-label {
  color: #888;
  font-size: 13px;
}

.video-grid {
  flex: 1;
  overflow: hidden;
  padding: 4px;
}

.grid-cell {
  position: relative;
  background: #111;
  border: 2px solid #333;
  border-radius: 4px;
  overflow: hidden;
  min-height: 120px;
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
  gap: 4px;
  z-index: 10;
}
</style>
