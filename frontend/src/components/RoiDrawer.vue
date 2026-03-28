<template>
  <div
    class="roi-drawer-overlay"
    :class="{ 'read-only': readOnly }"
    @keydown="onKeyDown"
    tabindex="0"
    ref="overlayEl"
  >
    <canvas
      ref="canvasEl"
      class="roi-canvas"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @dblclick.prevent="onDblClick"
    />

    <div class="roi-toolbar">
      <template v-if="!readOnly">
        <el-button-group>
          <el-button
            size="small"
            :type="mode === 'polygon' ? 'primary' : 'default'"
            @click="mode = 'polygon'"
          >
            <el-icon><EditPen /></el-icon>
            {{ t('roi.polygon') }}
          </el-button>
          <el-button
            size="small"
            :type="mode === 'rectangle' ? 'primary' : 'default'"
            @click="mode = 'rectangle'"
          >
            <el-icon><Crop /></el-icon>
            {{ t('roi.rectangle') }}
          </el-button>
        </el-button-group>

        <el-button
          v-if="mode === 'polygon' && isDrawing"
          size="small"
          type="primary"
          :disabled="currentPoints.length < 3"
          @click="finishPolygon"
        >
          <el-icon><Check /></el-icon>
          {{ t('roi.finishPolygon') }}
        </el-button>

        <el-button size="small" type="success" :loading="saving" @click="save">
          <el-icon><Check /></el-icon>
          {{ t('roi.saveRois') }}
        </el-button>
        <el-button size="small" @click="emit('close')">
          <el-icon><Close /></el-icon>
          {{ t('roi.exitEdit') }}
        </el-button>
      </template>

      <template v-else>
        <el-tag type="info" effect="dark">{{ t('roi.previewMode') }}</el-tag>
        <el-button size="small" @click="emit('close')">
          <el-icon><Close /></el-icon>
          {{ t('roi.closePreview') }}
        </el-button>
      </template>
    </div>

    <div v-if="!readOnly && selectedIdx !== null" class="tag-editor">
      <el-select
        v-model="shapes[selectedIdx].tag"
        size="small"
        class="tag-select"
        :placeholder="t('roi.selectTag')"
      >
        <el-option v-for="tag in tagOptions" :key="tag" :label="tag" :value="tag" />
      </el-select>
      <el-button size="small" type="danger" @click="deleteSelected">
        <el-icon><Delete /></el-icon>
        {{ t('roi.deleteShape') }}
      </el-button>
    </div>

    <div v-if="!readOnly && isDrawing" class="draw-hint">
      {{ mode === 'polygon' ? t('roi.polygonHint') : t('roi.rectangleHint') }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { useSourceStore } from '../stores/source.js'
import { useAppSettingsStore } from '../stores/appSettings.js'

const props = defineProps({
  source: {
    type: Object,
    required: true,
  },
  readOnly: {
    type: Boolean,
    default: false,
  },
})
const emit = defineEmits(['close'])

const store = useSourceStore()
const appSettingsStore = useAppSettingsStore()
const { t } = useI18n()

const canvasEl = ref(null)
const overlayEl = ref(null)
const mode = ref('polygon')
const saving = ref(false)

const shapes = ref([])
const selectedIdx = ref(null)
const isDrawing = ref(false)
const currentPoints = ref([])
const rectStart = ref(null)
const pointerPos = ref(null)

const tagOptions = computed(() => appSettingsStore.roiTagOptions)

let dragState = null

function resizeCanvas() {
  if (!canvasEl.value) return
  const parent = canvasEl.value.parentElement
  canvasEl.value.width = parent.clientWidth
  canvasEl.value.height = parent.clientHeight
  render()
}

function getCanvasPos(event) {
  const rect = canvasEl.value.getBoundingClientRect()
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

function getVideoElement() {
  return canvasEl.value?.parentElement?.querySelector('video.video-element') || null
}

function getVideoRect() {
  const canvas = canvasEl.value
  if (!canvas) {
    return { x: 0, y: 0, width: 1, height: 1 }
  }

  const cw = canvas.width || 1
  const ch = canvas.height || 1
  const videoEl = getVideoElement()

  if (!videoEl || !videoEl.videoWidth || !videoEl.videoHeight) {
    return { x: 0, y: 0, width: cw, height: ch }
  }

  const containerAspect = cw / ch
  const videoAspect = videoEl.videoWidth / videoEl.videoHeight

  if (containerAspect > videoAspect) {
    const height = ch
    const width = height * videoAspect
    return {
      x: (cw - width) / 2,
      y: 0,
      width,
      height,
    }
  }

  const width = cw
  const height = width / videoAspect
  return {
    x: 0,
    y: (ch - height) / 2,
    width,
    height,
  }
}

function clampNorm(point) {
  return {
    x: Math.max(0, Math.min(1, point.x)),
    y: Math.max(0, Math.min(1, point.y)),
  }
}

function canvasToNorm(point, videoRect = getVideoRect()) {
  const width = videoRect.width || 1
  const height = videoRect.height || 1
  return clampNorm({
    x: (point.x - videoRect.x) / width,
    y: (point.y - videoRect.y) / height,
  })
}

function normToCanvas(point, videoRect = getVideoRect()) {
  return {
    x: videoRect.x + point.x * videoRect.width,
    y: videoRect.y + point.y * videoRect.height,
  }
}

function isInsideVideo(point, videoRect = getVideoRect()) {
  return (
    point.x >= videoRect.x &&
    point.x <= videoRect.x + videoRect.width &&
    point.y >= videoRect.y &&
    point.y <= videoRect.y + videoRect.height
  )
}

function isPointInPolygon(point, polygon) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x
    const yi = polygon[i].y
    const xj = polygon[j].x
    const yj = polygon[j].y

    const intersect =
      yi > point.y !== yj > point.y &&
      point.x < ((xj - xi) * (point.y - yi)) / (yj - yi) + xi

    if (intersect) inside = !inside
  }
  return inside
}

function hitTestShapes(pos) {
  const videoRect = getVideoRect()
  for (let i = shapes.value.length - 1; i >= 0; i--) {
    const shape = shapes.value[i]
    const canvasPoints = shape.points.map((point) => normToCanvas(point, videoRect))

    for (let j = 0; j < canvasPoints.length; j++) {
      const dx = canvasPoints[j].x - pos.x
      const dy = canvasPoints[j].y - pos.y
      if (Math.sqrt(dx * dx + dy * dy) < 8) {
        return { shapeIdx: i, vertexIdx: j }
      }
    }

    if (canvasPoints.length >= 3 && isPointInPolygon(pos, canvasPoints)) {
      return { shapeIdx: i, vertexIdx: 'body' }
    }
  }

  return null
}

function drawShape(ctx, shape, idx, videoRect) {
  const points = shape.points.map((point) => normToCanvas(point, videoRect))
  if (!points.length) return

  const selected = idx === selectedIdx.value && !props.readOnly
  const color = selected ? '#f0c040' : '#40a0f0'

  ctx.beginPath()
  ctx.moveTo(points[0].x, points[0].y)
  for (let i = 1; i < points.length; i++) {
    ctx.lineTo(points[i].x, points[i].y)
  }
  ctx.closePath()
  ctx.strokeStyle = color
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = `${color}22`
  ctx.fill()

  if (!props.readOnly) {
    points.forEach((point) => {
      ctx.beginPath()
      ctx.arc(point.x, point.y, 4.5, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
    })
  }

  if (shape.tag) {
    ctx.font = '12px sans-serif'
    ctx.fillStyle = color
    ctx.fillText(shape.tag, points[0].x + 6, points[0].y - 8)
  }
}

function drawPolygonPreview(ctx, videoRect) {
  if (!(isDrawing.value && mode.value === 'polygon' && currentPoints.value.length)) return

  const points = currentPoints.value.map((point) => normToCanvas(point, videoRect))
  const pointer = pointerPos.value
    ? normToCanvas(canvasToNorm(pointerPos.value, videoRect), videoRect)
    : null

  ctx.beginPath()
  ctx.moveTo(points[0].x, points[0].y)
  for (let i = 1; i < points.length; i++) {
    ctx.lineTo(points[i].x, points[i].y)
  }
  if (pointer) {
    ctx.lineTo(pointer.x, pointer.y)
  }
  ctx.strokeStyle = '#80ff80'
  ctx.lineWidth = 2
  ctx.stroke()

  if (pointer && points.length >= 2) {
    ctx.beginPath()
    ctx.setLineDash([4, 4])
    ctx.moveTo(pointer.x, pointer.y)
    ctx.lineTo(points[0].x, points[0].y)
    ctx.strokeStyle = '#80ff80aa'
    ctx.stroke()
    ctx.setLineDash([])
  }

  points.forEach((point) => {
    ctx.beginPath()
    ctx.arc(point.x, point.y, 4, 0, Math.PI * 2)
    ctx.fillStyle = '#80ff80'
    ctx.fill()
  })
}

function drawRectanglePreview(ctx, videoRect) {
  if (!(isDrawing.value && mode.value === 'rectangle' && rectStart.value && pointerPos.value)) return

  const start = normToCanvas(rectStart.value, videoRect)
  const end = normToCanvas(canvasToNorm(pointerPos.value, videoRect), videoRect)
  const x = Math.min(start.x, end.x)
  const y = Math.min(start.y, end.y)
  const width = Math.abs(start.x - end.x)
  const height = Math.abs(start.y - end.y)

  ctx.strokeStyle = '#80ff80'
  ctx.lineWidth = 2
  ctx.strokeRect(x, y, width, height)
}

function render() {
  const canvas = canvasEl.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  const videoRect = getVideoRect()
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  ctx.save()
  ctx.setLineDash([6, 4])
  ctx.strokeStyle = 'rgba(64, 160, 240, 0.5)'
  ctx.lineWidth = 1
  ctx.strokeRect(videoRect.x, videoRect.y, videoRect.width, videoRect.height)
  ctx.restore()

  shapes.value.forEach((shape, idx) => drawShape(ctx, shape, idx, videoRect))
  drawPolygonPreview(ctx, videoRect)
  drawRectanglePreview(ctx, videoRect)
}

function clearDrawingState() {
  isDrawing.value = false
  currentPoints.value = []
  rectStart.value = null
  dragState = null
}

function createShapeWithDefaultTag(type, points) {
  const defaultTag = tagOptions.value[0] || ''
  shapes.value.push({ type, points, tag: defaultTag })
  selectedIdx.value = shapes.value.length - 1
}

function finalizeRectangle(startNorm, endNorm) {
  const x1 = Math.min(startNorm.x, endNorm.x)
  const y1 = Math.min(startNorm.y, endNorm.y)
  const x2 = Math.max(startNorm.x, endNorm.x)
  const y2 = Math.max(startNorm.y, endNorm.y)

  if (x2 - x1 <= 0.01 || y2 - y1 <= 0.01) return

  createShapeWithDefaultTag('rectangle', [
    { x: x1, y: y1 },
    { x: x2, y: y1 },
    { x: x2, y: y2 },
    { x: x1, y: y2 },
  ])
}

function finishPolygon() {
  if (!(mode.value === 'polygon' && isDrawing.value && currentPoints.value.length >= 3)) {
    return
  }

  createShapeWithDefaultTag('polygon', currentPoints.value.map((point) => ({ ...point })))
  clearDrawingState()
  render()
}

function onMouseDown(event) {
  if (props.readOnly) return

  overlayEl.value?.focus()
  const pos = getCanvasPos(event)
  pointerPos.value = pos
  const videoRect = getVideoRect()

  if (!isDrawing.value) {
    const hit = hitTestShapes(pos)
    if (hit) {
      selectedIdx.value = hit.shapeIdx
      dragState = {
        shapeIdx: hit.shapeIdx,
        vertexIdx: hit.vertexIdx,
        startMouse: pos,
        startPoints: shapes.value[hit.shapeIdx].points.map((point) => ({ ...point })),
      }
      render()
      return
    }
  }

  if (!isInsideVideo(pos, videoRect)) {
    ElMessage.warning(t('roi.pointOutside'))
    return
  }

  const pointNorm = canvasToNorm(pos, videoRect)
  selectedIdx.value = null

  if (mode.value === 'polygon') {
    isDrawing.value = true
    currentPoints.value.push(pointNorm)
    render()
    return
  }

  if (mode.value === 'rectangle') {
    if (!isDrawing.value || !rectStart.value) {
      isDrawing.value = true
      rectStart.value = pointNorm
    } else {
      finalizeRectangle(rectStart.value, pointNorm)
      clearDrawingState()
    }
    render()
  }
}

function onMouseMove(event) {
  const pos = getCanvasPos(event)
  pointerPos.value = pos

  if (props.readOnly) {
    render()
    return
  }

  if (dragState) {
    const videoRect = getVideoRect()
    const width = videoRect.width || 1
    const height = videoRect.height || 1
    const dx = (pos.x - dragState.startMouse.x) / width
    const dy = (pos.y - dragState.startMouse.y) / height
    const shape = shapes.value[dragState.shapeIdx]

    if (dragState.vertexIdx === 'body') {
      shape.points = dragState.startPoints.map((point) =>
        clampNorm({ x: point.x + dx, y: point.y + dy })
      )
    } else {
      shape.points = dragState.startPoints.map((point, index) => {
        if (index === dragState.vertexIdx) {
          return clampNorm({ x: point.x + dx, y: point.y + dy })
        }
        return { ...point }
      })
    }

    render()
    return
  }

  if (isDrawing.value) {
    render()
  }
}

function onMouseUp() {
  if (dragState) {
    dragState = null
    render()
  }
}

function onDblClick() {
  if (!props.readOnly && mode.value === 'polygon') {
    finishPolygon()
  }
}

function onKeyDown(event) {
  if (event.key === 'Escape') {
    if (isDrawing.value) {
      clearDrawingState()
      render()
    } else {
      emit('close')
    }
    return
  }

  if (props.readOnly) return

  if (event.key === 'Enter' && mode.value === 'polygon') {
    finishPolygon()
    return
  }

  if ((event.key === 'Delete' || event.key === 'Backspace') && selectedIdx.value !== null) {
    deleteSelected()
  }
}

function deleteSelected() {
  if (props.readOnly) return
  if (selectedIdx.value === null) return

  shapes.value.splice(selectedIdx.value, 1)
  selectedIdx.value = null
  render()
}

async function save() {
  if (props.readOnly) {
    emit('close')
    return
  }

  if (!tagOptions.value.length) {
    ElMessage.warning(t('roi.noTagOptions'))
    return
  }

  const invalidIndex = shapes.value.findIndex(
    (shape) => !shape.tag || !tagOptions.value.includes(shape.tag)
  )

  if (invalidIndex !== -1) {
    selectedIdx.value = invalidIndex
    ElMessage.warning(t('roi.tagRequired'))
    render()
    return
  }

  saving.value = true
  try {
    const rois = shapes.value.map((shape) => ({
      type: shape.type,
      points: shape.points,
      tag: shape.tag,
    }))

    await store.updateSource(props.source.id, { rois })
    ElMessage.success(t('roi.roisSaved'))
  } catch (err) {
    ElMessage.error(err.message || t('roi.saveFailed'))
  } finally {
    saving.value = false
  }
}

function loadExistingRois() {
  const source = store.sources.find((item) => item.id === props.source.id)
  const rois = source?.rois || props.source.rois || []
  shapes.value = rois.map((roi) => ({
    type: roi.type,
    points: roi.points.map((point) => ({ x: point.x, y: point.y })),
    tag: roi.tag || '',
  }))
  selectedIdx.value = null
  clearDrawingState()
  render()
}

const resizeObserver = new ResizeObserver(resizeCanvas)

watch(() => props.source?.id, loadExistingRois)

watch(() => props.readOnly, () => {
  selectedIdx.value = null
  clearDrawingState()
  render()
})

onMounted(async () => {
  if (!appSettingsStore.loaded) {
    await appSettingsStore.fetchSettings().catch(() => {
      // Keep fallback tag options when settings API is unavailable.
    })
  }

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

.roi-drawer-overlay.read-only .roi-canvas {
  cursor: default;
}

.roi-toolbar {
  position: absolute;
  top: 8px;
  left: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  z-index: 110;
}

.roi-toolbar :deep(.el-button span) {
  white-space: nowrap;
}

.tag-editor {
  position: absolute;
  bottom: 8px;
  left: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  z-index: 110;
  background: rgba(0, 0, 0, 0.72);
  padding: 6px;
  border-radius: 6px;
}

.tag-select {
  min-width: 190px;
}

.draw-hint {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 110;
  background: rgba(0, 0, 0, 0.68);
  color: #d4deef;
  font-size: 12px;
  line-height: 1.4;
  padding: 6px 8px;
  border-radius: 6px;
  max-width: min(80%, 360px);
}
</style>
