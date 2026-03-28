<template>
  <div class="roi-drawer-overlay" @keydown="onKeyDown" tabindex="0" ref="overlayEl">
    <!-- Canvas for drawing -->
    <canvas
      ref="canvasEl"
      class="roi-canvas"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @dblclick="onDblClick"
    />

    <!-- Toolbar -->
    <div class="roi-toolbar">
      <el-button-group>
        <el-button
          size="small"
          :type="mode === 'polygon' ? 'primary' : 'default'"
          @click="mode = 'polygon'"
        >
          <el-icon><EditPen /></el-icon> {{ t('roi.polygon') }}
        </el-button>
        <el-button
          size="small"
          :type="mode === 'rectangle' ? 'primary' : 'default'"
          @click="mode = 'rectangle'"
        >
          <el-icon><Crop /></el-icon> {{ t('roi.rectangle') }}
        </el-button>
      </el-button-group>
      <el-button size="small" type="success" :loading="saving" @click="save">
        <el-icon><Check /></el-icon> {{ t('roi.saveRois') }}
      </el-button>
      <el-button size="small" @click="emit('close')">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>

    <!-- Tag editor for selected shape -->
    <div v-if="selectedIdx !== null" class="tag-editor">
      <el-input
        v-model="shapes[selectedIdx].tag"
        size="small"
        :placeholder="t('roi.tagPlaceholder')"
        clearable
      >
        <template #prepend>{{ t('roi.tag') }}</template>
      </el-input>
      <el-button size="small" type="danger" @click="deleteSelected">
        <el-icon><Delete /></el-icon>
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useSourceStore } from '../stores/source.js'

const props = defineProps({
  source: {
    type: Object,
    required: true,
  },
})
const emit = defineEmits(['close'])

const store = useSourceStore()
const { t } = useI18n()
const canvasEl = ref(null)
const overlayEl = ref(null)
const mode = ref('polygon')
const saving = ref(false)

// Internal shape representation
// shape: { type: 'polygon'|'rectangle', points: [{x,y} normalized], tag: '' }
const shapes = ref([])
const selectedIdx = ref(null)

// Drawing state
let isDrawing = false
let currentPoints = []
let rectStart = null
let dragState = null // { shapeIdx, vertexIdx | 'body', startMouse, startPoints }

// ── Canvas ────────────────────────────────────────────────────────────────

function resizeCanvas() {
  if (!canvasEl.value) return
  const parent = canvasEl.value.parentElement
  canvasEl.value.width = parent.clientWidth
  canvasEl.value.height = parent.clientHeight
  render()
}

function render() {
  const canvas = canvasEl.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const w = canvas.width
  const h = canvas.height
  ctx.clearRect(0, 0, w, h)

  shapes.value.forEach((shape, idx) => {
    const pts = shape.points.map((p) => ({ x: p.x * w, y: p.y * h }))
    const isSelected = idx === selectedIdx.value
    const color = isSelected ? '#f0c040' : '#40a0f0'

    ctx.beginPath()
    if (pts.length === 0) return
    ctx.moveTo(pts[0].x, pts[0].y)
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
    if (shape.type === 'rectangle' || shape.type === 'polygon') ctx.closePath()

    ctx.strokeStyle = color
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.fillStyle = `${color}22`
    ctx.fill()

    // Vertices
    pts.forEach((p) => {
      ctx.beginPath()
      ctx.arc(p.x, p.y, 5, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
    })

    // Tag label
    if (shape.tag && pts.length > 0) {
      ctx.font = '12px sans-serif'
      ctx.fillStyle = color
      ctx.fillText(shape.tag, pts[0].x + 6, pts[0].y - 6)
    }
  })

  // In-progress polygon
  if (isDrawing && mode.value === 'polygon' && currentPoints.length) {
    const pts = currentPoints
    ctx.beginPath()
    ctx.moveTo(pts[0].x, pts[0].y)
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y)
    ctx.strokeStyle = '#80ff80'
    ctx.lineWidth = 2
    ctx.stroke()
    pts.forEach((p) => {
      ctx.beginPath()
      ctx.arc(p.x, p.y, 4, 0, Math.PI * 2)
      ctx.fillStyle = '#80ff80'
      ctx.fill()
    })
  }

  // In-progress rectangle
  if (isDrawing && mode.value === 'rectangle' && rectStart) {
    // drawn on mouseMove
  }
}

// ── Mouse Events ──────────────────────────────────────────────────────────

function getCanvasPos(event) {
  const rect = canvasEl.value.getBoundingClientRect()
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

function toNorm(pos) {
  const w = canvasEl.value.width
  const h = canvasEl.value.height
  return { x: pos.x / w, y: pos.y / h }
}

function hitTestShapes(pos) {
  const canvas = canvasEl.value
  const w = canvas.width
  const h = canvas.height
  for (let i = shapes.value.length - 1; i >= 0; i--) {
    const shape = shapes.value[i]
    const pts = shape.points.map((p) => ({ x: p.x * w, y: p.y * h }))
    // Check vertex hit
    for (let j = 0; j < pts.length; j++) {
      const dx = pts[j].x - pos.x
      const dy = pts[j].y - pos.y
      if (Math.sqrt(dx * dx + dy * dy) < 8) {
        return { shapeIdx: i, vertexIdx: j }
      }
    }
    // Check polygon body
    if (isPointInPolygon(pos, pts)) {
      return { shapeIdx: i, vertexIdx: 'body' }
    }
  }
  return null
}

function isPointInPolygon(point, pts) {
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const xi = pts[i].x, yi = pts[i].y
    const xj = pts[j].x, yj = pts[j].y
    const intersect = yi > point.y !== yj > point.y &&
      point.x < ((xj - xi) * (point.y - yi)) / (yj - yi) + xi
    if (intersect) inside = !inside
  }
  return inside
}

function onMouseDown(event) {
  overlayEl.value?.focus()
  const pos = getCanvasPos(event)

  // Check if clicking existing shape
  const hit = hitTestShapes(pos)
  if (hit && !isDrawing) {
    selectedIdx.value = hit.shapeIdx
    dragState = {
      shapeIdx: hit.shapeIdx,
      vertexIdx: hit.vertexIdx,
      startMouse: pos,
      startPoints: shapes.value[hit.shapeIdx].points.map((p) => ({ ...p })),
    }
    render()
    return
  }

  if (mode.value === 'polygon') {
    if (!isDrawing) {
      isDrawing = true
      selectedIdx.value = null
    }
    currentPoints.push(pos)
    render()
  } else if (mode.value === 'rectangle') {
    isDrawing = true
    selectedIdx.value = null
    rectStart = pos
  }
}

function onMouseMove(event) {
  const pos = getCanvasPos(event)

  if (dragState) {
    const canvas = canvasEl.value
    const w = canvas.width
    const h = canvas.height
    const dx = pos.x - dragState.startMouse.x
    const dy = pos.y - dragState.startMouse.y
    const shape = shapes.value[dragState.shapeIdx]

    if (dragState.vertexIdx === 'body') {
      shape.points = dragState.startPoints.map((p) => ({
        x: Math.max(0, Math.min(1, p.x + dx / w)),
        y: Math.max(0, Math.min(1, p.y + dy / h)),
      }))
    } else {
      shape.points = dragState.startPoints.map((p, i) => {
        if (i === dragState.vertexIdx) {
          return {
            x: Math.max(0, Math.min(1, p.x + dx / w)),
            y: Math.max(0, Math.min(1, p.y + dy / h)),
          }
        }
        return { ...p }
      })
    }
    render()
    return
  }

  if (isDrawing && mode.value === 'rectangle' && rectStart) {
    const canvas = canvasEl.value
    const ctx = canvas.getContext('2d')
    render()
    ctx.strokeStyle = '#80ff80'
    ctx.lineWidth = 2
    ctx.strokeRect(rectStart.x, rectStart.y, pos.x - rectStart.x, pos.y - rectStart.y)
  }
}

function onMouseUp(event) {
  if (dragState) {
    dragState = null
    return
  }

  if (mode.value === 'rectangle' && isDrawing && rectStart) {
    const pos = getCanvasPos(event)
    const w = canvasEl.value.width
    const h = canvasEl.value.height
    const x1 = Math.min(rectStart.x, pos.x) / w
    const y1 = Math.min(rectStart.y, pos.y) / h
    const x2 = Math.max(rectStart.x, pos.x) / w
    const y2 = Math.max(rectStart.y, pos.y) / h
    if (x2 - x1 > 0.01 && y2 - y1 > 0.01) {
      shapes.value.push({
        type: 'rectangle',
        points: [
          { x: x1, y: y1 },
          { x: x2, y: y1 },
          { x: x2, y: y2 },
          { x: x1, y: y2 },
        ],
        tag: '',
      })
      selectedIdx.value = shapes.value.length - 1
    }
    isDrawing = false
    rectStart = null
    render()
  }
}

function onDblClick() {
  if (mode.value === 'polygon' && isDrawing && currentPoints.length >= 3) {
    const w = canvasEl.value.width
    const h = canvasEl.value.height
    shapes.value.push({
      type: 'polygon',
      points: currentPoints.map((p) => ({ x: p.x / w, y: p.y / h })),
      tag: '',
    })
    selectedIdx.value = shapes.value.length - 1
    isDrawing = false
    currentPoints = []
    render()
  }
}

function onKeyDown(event) {
  if ((event.key === 'Delete' || event.key === 'Backspace') && selectedIdx.value !== null) {
    deleteSelected()
  }
  if (event.key === 'Escape') {
    isDrawing = false
    currentPoints = []
    rectStart = null
    selectedIdx.value = null
    render()
  }
}

function deleteSelected() {
  if (selectedIdx.value !== null) {
    shapes.value.splice(selectedIdx.value, 1)
    selectedIdx.value = null
    render()
  }
}

// ── Save ──────────────────────────────────────────────────────────────────

async function save() {
  saving.value = true
  try {
    const rois = shapes.value.map((s) => ({
      type: s.type,
      points: s.points,
      tag: s.tag,
    }))
    await store.updateSource(props.source.id, { rois })
    ElMessage.success(t('roi.roisSaved'))
  } catch (err) {
    ElMessage.error(err.message || t('roi.saveFailed'))
  } finally {
    saving.value = false
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────

function loadExistingRois() {
  const source = store.sources.find((s) => s.id === props.source.id)
  const rois = source?.rois || props.source.rois || []
  shapes.value = rois.map((roi) => ({
    type: roi.type,
    points: roi.points.map((p) => ({ x: p.x, y: p.y })),
    tag: roi.tag || '',
  }))
}

const resizeObserver = new ResizeObserver(resizeCanvas)

onMounted(() => {
  loadExistingRois()
  resizeCanvas()
  overlayEl.value?.focus()
  if (canvasEl.value) {
    resizeObserver.observe(canvasEl.value.parentElement)
  }
})

onBeforeUnmount(() => {
  resizeObserver.disconnect()
})
</script>

<style scoped>
.roi-drawer-overlay {
  position: absolute;
  inset: 0;
  z-index: 100;
  outline: none;
}

.roi-canvas {
  position: absolute;
  inset: 0;
  cursor: crosshair;
}

.roi-toolbar {
  position: absolute;
  top: 8px;
  left: 8px;
  display: flex;
  gap: 6px;
  z-index: 110;
}

.tag-editor {
  position: absolute;
  bottom: 8px;
  left: 8px;
  display: flex;
  gap: 6px;
  z-index: 110;
  background: rgba(0, 0, 0, 0.7);
  padding: 6px;
  border-radius: 6px;
}
</style>
