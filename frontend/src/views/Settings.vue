<template>
  <div class="settings-page">
    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <el-icon :size="20"><Setting /></el-icon>
          <span>{{ t('settings.title') }}</span>
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
        <el-divider content-position="left">{{ t('settings.vengineServices') }}</el-divider>
        <el-form-item :label="t('settings.vengineHost')">
          <el-input v-model="form.vengine_host" placeholder="localhost" />
        </el-form-item>

        <!-- Per-service ports -->
        <el-form-item :label="t('settings.detectionPort')">
          <el-input v-model="form.detection_port" placeholder="50051" />
        </el-form-item>
        <el-form-item :label="t('settings.classificationPort')">
          <el-input v-model="form.classification_port" placeholder="50052" />
        </el-form-item>
        <el-form-item :label="t('settings.actionPort')">
          <el-input v-model="form.action_port" placeholder="50053" />
        </el-form-item>
        <el-form-item :label="t('settings.ocrPort')">
          <el-input v-model="form.ocr_port" placeholder="50054" />
        </el-form-item>
        <el-form-item :label="t('settings.uploadPort')">
          <el-input v-model="form.upload_port" placeholder="50050" />
        </el-form-item>

        <!-- MediaMTX -->
        <el-divider content-position="left">{{ t('settings.mediamtx') }}</el-divider>
        <el-form-item :label="t('settings.rtspAddress')">
          <el-input v-model="form.mediamtx_rtsp_addr" placeholder="rtsp://localhost:8554" />
        </el-form-item>
        <el-form-item :label="t('settings.webrtcAddress')">
          <el-input v-model="form.mediamtx_webrtc_addr" placeholder="http://localhost:8889" />
        </el-form-item>

        <!-- Thread pools -->
        <el-divider content-position="left">{{ t('settings.threadPools') }}</el-divider>
        <el-form-item :label="t('settings.maxPullWorkers')">
          <el-input v-model="form.max_pull_workers" placeholder="20" />
        </el-form-item>
        <el-form-item :label="t('settings.maxPushWorkers')">
          <el-input v-model="form.max_push_workers" placeholder="10" />
        </el-form-item>
        <el-form-item :label="t('settings.maxCpuWorkers')">
          <el-input v-model="form.max_cpu_workers" placeholder="16" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="save" :loading="saving">
            {{ t('settings.saveSettings') }}
          </el-button>
          <el-button @click="reload">{{ t('common.reset') }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { settingsApi } from '../api/index.js'

const { t } = useI18n()
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
    ElMessage.error(t('settings.failedToLoad', { message: err.message }))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const data = await settingsApi.update(form.value)
    Object.assign(form.value, data)
    ElMessage.success(t('settings.settingsSaved'))
  } catch (err) {
    ElMessage.error(t('settings.failedToSave', { message: err.message }))
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
