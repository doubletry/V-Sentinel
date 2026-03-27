<template>
  <div class="settings-page">
    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <el-icon :size="20"><Setting /></el-icon>
          <span>Platform Settings</span>
        </div>
      </template>

      <el-form
        ref="formRef"
        :model="form"
        label-width="180px"
        label-position="right"
        v-loading="loading"
      >
        <!-- V-Engine Host -->
        <el-divider content-position="left">V-Engine Services</el-divider>
        <el-form-item label="V-Engine Host">
          <el-input v-model="form.vengine_host" placeholder="localhost" />
        </el-form-item>

        <!-- Per-service ports -->
        <el-form-item label="Detection Port">
          <el-input v-model="form.detection_port" placeholder="50051" />
        </el-form-item>
        <el-form-item label="Classification Port">
          <el-input v-model="form.classification_port" placeholder="50052" />
        </el-form-item>
        <el-form-item label="Action Port">
          <el-input v-model="form.action_port" placeholder="50053" />
        </el-form-item>
        <el-form-item label="OCR Port">
          <el-input v-model="form.ocr_port" placeholder="50054" />
        </el-form-item>
        <el-form-item label="Upload Port">
          <el-input v-model="form.upload_port" placeholder="50050" />
        </el-form-item>

        <!-- MediaMTX -->
        <el-divider content-position="left">MediaMTX</el-divider>
        <el-form-item label="RTSP Address">
          <el-input v-model="form.mediamtx_rtsp_addr" placeholder="rtsp://localhost:8554" />
        </el-form-item>
        <el-form-item label="WebRTC Address">
          <el-input v-model="form.mediamtx_webrtc_addr" placeholder="http://localhost:8889" />
        </el-form-item>

        <!-- Thread pools -->
        <el-divider content-position="left">Thread Pools</el-divider>
        <el-form-item label="Max Pull Workers">
          <el-input v-model="form.max_pull_workers" placeholder="20" />
        </el-form-item>
        <el-form-item label="Max Push Workers">
          <el-input v-model="form.max_push_workers" placeholder="10" />
        </el-form-item>
        <el-form-item label="Max CPU Workers">
          <el-input v-model="form.max_cpu_workers" placeholder="16" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="save" :loading="saving">
            Save Settings
          </el-button>
          <el-button @click="reload">Reset</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { settingsApi } from '../api/index.js'

const loading = ref(false)
const saving = ref(false)
const form = ref({
  vengine_host: '',
  detection_port: '',
  classification_port: '',
  action_port: '',
  ocr_port: '',
  upload_port: '',
  mediamtx_rtsp_addr: '',
  mediamtx_webrtc_addr: '',
  max_pull_workers: '',
  max_push_workers: '',
  max_cpu_workers: '',
})

async function reload() {
  loading.value = true
  try {
    const data = await settingsApi.get()
    Object.assign(form.value, data)
  } catch (err) {
    ElMessage.error(`Failed to load settings: ${err.message}`)
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const data = await settingsApi.update(form.value)
    Object.assign(form.value, data)
    ElMessage.success('Settings saved successfully')
  } catch (err) {
    ElMessage.error(`Failed to save settings: ${err.message}`)
  } finally {
    saving.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.settings-page {
  padding: 24px;
  max-width: 700px;
  margin: 0 auto;
}

.settings-card {
  background: #1a1a2e;
  border: 1px solid #333;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #eee;
}

:deep(.el-divider__text) {
  background: #1a1a2e;
  color: #888;
}
</style>
