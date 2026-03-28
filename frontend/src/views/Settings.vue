<template>
  <div class="settings-page">
    <div class="settings-shell">
      <div class="settings-head">
        <div class="title-line">
          <el-icon :size="20"><Setting /></el-icon>
          <h1>{{ t('settings.title') }}</h1>
        </div>
        <p>{{ t('settings.subtitle') }}</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        class="settings-form"
        label-width="210px"
        label-position="right"
        v-loading="loading"
      >
        <section class="settings-section">
          <h2>{{ t('settings.interface') }}</h2>
          <el-form-item :label="t('settings.systemLanguage')">
            <el-select v-model="form.ui_language" style="width: 100%">
              <el-option
                v-for="option in languageOptions"
                :key="option.value"
                :label="t(option.labelKey)"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('settings.siteTitle')">
            <el-input v-model="form.site_title" :placeholder="t('settings.siteTitle')" />
          </el-form-item>
          <el-form-item :label="t('settings.siteDescription')">
            <el-input
              v-model="form.site_description"
              :placeholder="t('settings.siteDescription')"
            />
          </el-form-item>
          <el-form-item :label="t('settings.faviconUrl')">
            <el-input v-model="form.favicon_url" placeholder="/favicon.ico" />
          </el-form-item>
          <el-form-item :label="t('settings.brandIcon')">
            <el-select v-model="form.brand_icon" style="width: 100%">
              <el-option
                v-for="option in iconOptions"
                :key="option.value"
                :label="t(option.labelKey)"
                :value="option.value"
              >
                <div class="icon-option">
                  <el-icon><component :is="option.value" /></el-icon>
                  <span>{{ t(option.labelKey) }}</span>
                </div>
              </el-option>
            </el-select>
          </el-form-item>

          <h3>{{ t('settings.tabbarIcons') }}</h3>
          <el-form-item :label="t('settings.videoWallIcon')">
            <el-select v-model="form.nav_icon_video_wall" style="width: 100%">
              <el-option
                v-for="option in iconOptions"
                :key="`wall-${option.value}`"
                :label="t(option.labelKey)"
                :value="option.value"
              >
                <div class="icon-option">
                  <el-icon><component :is="option.value" /></el-icon>
                  <span>{{ t(option.labelKey) }}</span>
                </div>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item :label="t('settings.messagesIcon')">
            <el-select v-model="form.nav_icon_messages" style="width: 100%">
              <el-option
                v-for="option in iconOptions"
                :key="`msg-${option.value}`"
                :label="t(option.labelKey)"
                :value="option.value"
              >
                <div class="icon-option">
                  <el-icon><component :is="option.value" /></el-icon>
                  <span>{{ t(option.labelKey) }}</span>
                </div>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item :label="t('settings.settingsIcon')">
            <el-select v-model="form.nav_icon_settings" style="width: 100%">
              <el-option
                v-for="option in iconOptions"
                :key="`settings-${option.value}`"
                :label="t(option.labelKey)"
                :value="option.value"
              >
                <div class="icon-option">
                  <el-icon><component :is="option.value" /></el-icon>
                  <span>{{ t(option.labelKey) }}</span>
                </div>
              </el-option>
            </el-select>
          </el-form-item>
        </section>

        <section class="settings-section">
          <h2>{{ t('settings.backendService') }}</h2>
          <div class="service-control-row">
            <el-tag :type="sourceStore.runningCount > 0 ? 'success' : 'info'" effect="dark">
              {{
                sourceStore.runningCount > 0
                  ? t('settings.runningStatus', { count: sourceStore.runningCount })
                  : t('settings.stoppedStatus')
              }}
            </el-tag>
            <div class="service-buttons">
              <el-button
                type="success"
                :loading="serviceAction === 'start'"
                @click="startAllServices"
              >
                {{ t('settings.startAll') }}
              </el-button>
              <el-button
                type="warning"
                :loading="serviceAction === 'stop'"
                @click="stopAllServices"
              >
                {{ t('settings.stopAll') }}
              </el-button>
            </div>
          </div>
          <p class="service-tip">{{ t('settings.backendServiceTip') }}</p>
        </section>

        <section class="settings-section">
          <h2>{{ t('settings.vengineServices') }}</h2>
          <el-form-item :label="t('settings.vengineHost')">
            <el-input v-model="form.vengine_host" placeholder="localhost" />
          </el-form-item>
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
        </section>

        <section class="settings-section">
          <h2>{{ t('settings.mediamtx') }}</h2>
          <el-form-item :label="t('settings.rtspAddress')">
            <el-input v-model="form.mediamtx_rtsp_addr" placeholder="rtsp://localhost:8554" />
          </el-form-item>
          <el-form-item :label="t('settings.webrtcAddress')">
            <el-input v-model="form.mediamtx_webrtc_addr" placeholder="http://localhost:8889" />
          </el-form-item>
        </section>

        <section class="settings-section">
          <h2>{{ t('settings.threadPools') }}</h2>
          <el-form-item :label="t('settings.maxPullWorkers')">
            <el-input v-model="form.max_pull_workers" placeholder="20" />
          </el-form-item>
          <el-form-item :label="t('settings.maxPushWorkers')">
            <el-input v-model="form.max_push_workers" placeholder="10" />
          </el-form-item>
          <el-form-item :label="t('settings.maxCpuWorkers')">
            <el-input v-model="form.max_cpu_workers" placeholder="16" />
          </el-form-item>
        </section>

        <div class="settings-actions">
          <el-button @click="reload">{{ t('common.reset') }}</el-button>
          <el-button type="primary" @click="save" :loading="saving">
            {{ t('settings.saveSettings') }}
          </el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { localeOptions } from '../i18n/index.js'
import { APP_ICON_OPTIONS, useAppSettingsStore } from '../stores/appSettings.js'
import { useSourceStore } from '../stores/source.js'

const { t } = useI18n()
const appSettingsStore = useAppSettingsStore()
const sourceStore = useSourceStore()
const languageOptions = localeOptions
const iconOptions = APP_ICON_OPTIONS

const loading = ref(false)
const saving = ref(false)
const serviceAction = ref('')
const form = ref({
  ui_language: 'zh-CN',
  site_title: '',
  site_description: '',
  favicon_url: '/favicon.ico',
  brand_icon: 'VideoCamera',
  nav_icon_video_wall: 'Monitor',
  nav_icon_messages: 'Bell',
  nav_icon_settings: 'Setting',
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
    const data = await appSettingsStore.fetchSettings(true)
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
    const data = await appSettingsStore.updateSettings(form.value)
    Object.assign(form.value, data)
    appSettingsStore.applyLanguage(form.value.ui_language)
    ElMessage.success(t('settings.settingsSaved'))
  } catch (err) {
    ElMessage.error(t('settings.failedToSave', { message: err.message }))
  } finally {
    saving.value = false
  }
}

async function startAllServices() {
  serviceAction.value = 'start'
  try {
    await sourceStore.startAllProcessing()
  } finally {
    serviceAction.value = ''
  }
}

async function stopAllServices() {
  serviceAction.value = 'stop'
  try {
    await sourceStore.stopAllProcessing()
  } finally {
    serviceAction.value = ''
  }
}

onMounted(async () => {
  await Promise.all([
    reload(),
    sourceStore.syncProcessorStatus(),
  ])
})
</script>

<style scoped>
.settings-page {
  height: 100%;
  overflow-y: auto;
  padding: 20px 24px 28px;
  background:
    radial-gradient(circle at 0% 0%, rgba(64, 158, 255, 0.13), transparent 42%),
    radial-gradient(circle at 100% 100%, rgba(0, 178, 169, 0.12), transparent 40%),
    #0d0d1a;
}

.settings-shell {
  max-width: 980px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.settings-head {
  padding: 4px 4px 0;
}

.title-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-line h1 {
  font-size: 22px;
  font-weight: 700;
  color: #e9f0ff;
}

.settings-head p {
  margin-top: 6px;
  color: #9ba8be;
  font-size: 13px;
}

.settings-form {
  background: rgba(16, 21, 37, 0.92);
  border: 1px solid #26314d;
  border-radius: 14px;
  padding: 16px;
}

.settings-section {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid #30364d;
  border-radius: 12px;
  padding: 16px 12px 6px;
  margin-bottom: 14px;
}

.settings-section h2 {
  font-size: 14px;
  color: #9ab2df;
  margin-bottom: 10px;
}

.settings-section h3 {
  margin: 8px 0 12px;
  color: #7f95bf;
  font-size: 13px;
  font-weight: 600;
}

.icon-option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.service-control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.service-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.service-tip {
  margin-top: 8px;
  color: #8f9fbe;
  font-size: 12px;
  line-height: 1.45;
}

.settings-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  position: sticky;
  bottom: 0;
  padding-top: 10px;
  padding-bottom: 4px;
  background: linear-gradient(to bottom, rgba(16, 21, 37, 0), rgba(16, 21, 37, 0.96) 26%);
}

:deep(.el-form-item__label) {
  color: #aab7d2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 768px) {
  .settings-page {
    padding: 12px 12px 20px;
  }

  .settings-form {
    padding: 12px;
  }

  .title-line h1 {
    font-size: 18px;
  }

  :deep(.el-form-item) {
    margin-bottom: 14px;
  }

  :deep(.el-form-item__label) {
    width: 100% !important;
    justify-content: flex-start;
    margin-bottom: 4px;
    line-height: 1.4;
  }

  :deep(.el-form-item__content) {
    margin-left: 0 !important;
  }
}
</style>
