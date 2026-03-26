<template>
  <div class="source-list">
    <div class="list-header">
      <span class="list-title">Video Sources</span>
      <el-button type="primary" size="small" @click="showAddDialog = true">
        <el-icon><Plus /></el-icon>
        Add
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
          <div class="source-url">{{ source.rtsp_url }}</div>
        </div>
        <div class="source-actions">
          <el-button
            size="small"
            :type="store.isRunning(source.id) ? 'warning' : 'success'"
            :loading="actionLoading[source.id]"
            @click="toggleAnalysis(source)"
          >
            {{ store.isRunning(source.id) ? 'Stop' : 'Analyze' }}
          </el-button>
          <el-button
            size="small"
            type="danger"
            @click="confirmDelete(source)"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>

      <div v-if="!store.sources.length" class="empty-hint">
        <el-icon :size="32" color="#555"><VideoCamera /></el-icon>
        <span>No sources yet</span>
      </div>
    </el-scrollbar>

    <!-- Add Source Dialog -->
    <el-dialog
      v-model="showAddDialog"
      title="Add Video Source"
      width="400px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="80px" @submit.prevent="addSource">
        <el-form-item label="Name" required>
          <el-input v-model="form.name" placeholder="Camera 1" />
        </el-form-item>
        <el-form-item label="RTSP URL" required>
          <el-input
            v-model="form.rtsp_url"
            placeholder="rtsp://..."
            type="url"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">Cancel</el-button>
        <el-button type="primary" :loading="addLoading" @click="addSource">
          Add
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useSourceStore } from '../stores/source.js'

const store = useSourceStore()
const showAddDialog = ref(false)
const addLoading = ref(false)
const actionLoading = reactive({})

const form = reactive({ name: '', rtsp_url: '' })

function onDragStart(event, source) {
  event.dataTransfer.setData('source-id', source.id)
  event.dataTransfer.effectAllowed = 'copy'
}

async function addSource() {
  if (!form.name || !form.rtsp_url) {
    ElMessage.warning('Please fill in all fields')
    return
  }
  addLoading.value = true
  try {
    await store.createSource({ name: form.name, rtsp_url: form.rtsp_url })
    showAddDialog.value = false
    form.name = ''
    form.rtsp_url = ''
    ElMessage.success('Source added')
  } catch (err) {
    ElMessage.error(err.message || 'Failed to add source')
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

async function confirmDelete(source) {
  try {
    await ElMessageBox.confirm(
      `Delete "${source.name}"?`,
      'Confirm',
      { type: 'warning', confirmButtonText: 'Delete', cancelButtonText: 'Cancel' }
    )
    await store.deleteSource(source.id)
    ElMessage.success('Deleted')
  } catch (_) {
    // User cancelled
  }
}
</script>

<style scoped>
.source-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1a1a2e;
  border-right: 1px solid #333;
}

.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
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

.source-name {
  font-size: 13px;
  font-weight: 600;
  color: #ddd;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.source-url {
  font-size: 11px;
  color: #666;
  word-break: break-all;
}

.source-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  gap: 8px;
  color: #555;
  font-size: 13px;
}
</style>
