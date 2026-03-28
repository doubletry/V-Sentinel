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
            <div class="icon-upload-group">
              <el-avatar :size="28" shape="square" :src="form.favicon_url">
                <el-icon><VideoCamera /></el-icon>
              </el-avatar>
              <el-upload
                class="site-icon-upload"
                :show-file-list="false"
                :auto-upload="false"
                accept=".ico,.png,.jpg,.jpeg,.svg,.webp"
                :on-change="onSiteIconChange"
              >
                <el-button size="small">{{ t('settings.uploadSiteIcon') }}</el-button>
              </el-upload>
              <el-button size="small" @click="resetSiteIcon">{{ t('settings.resetSiteIcon') }}</el-button>
            </div>
          </el-form-item>
          <el-form-item :label="t('settings.iconPath')">
            <el-input v-model="form.favicon_url" placeholder="/favicon.ico" />
          </el-form-item>
          <el-form-item :label="t('settings.roiTagCandidates')">
            <div class="roi-tags-editor">
              <el-tag
                v-for="tag in roiTagList"
                :key="tag"
                closable
                type="info"
                effect="dark"
                class="roi-tag-item"
                @close="removeRoiTag(tag)"
              >
                {{ tag }}
              </el-tag>
              <span v-if="!roiTagList.length" class="roi-tag-empty">
                {{ t('settings.noRoiTags') }}
              </span>
            </div>
            <div class="roi-tag-input-row">
              <el-input
                v-model="roiTagInput"
                :placeholder="t('settings.roiTagInputPlaceholder')"
                @keyup.enter="addRoiTag"
              />
              <el-button type="primary" @click="addRoiTag">
                {{ t('settings.addRoiTag') }}
              </el-button>
            </div>
            <p class="roi-tag-hint">{{ t('settings.roiTagHint') }}</p>
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
import { useAppSettingsStore } from '../stores/appSettings.js'
import { useSourceStore } from '../stores/source.js'

const { t } = useI18n()
const appSettingsStore = useAppSettingsStore()
const sourceStore = useSourceStore()
const languageOptions = localeOptions

const loading = ref(false)
const saving = ref(false)
const serviceAction = ref('')
const roiTagInput = ref('')
const roiTagList = ref([])
const form = ref({
  ui_language: 'zh-CN',
  site_title: '',
  site_description: '',
  favicon_url: '/favicon.ico',
  roi_tag_options: '[]',
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

function parseRoiTagOptions(raw) {
  if (Array.isArray(raw)) {
    return Array.from(new Set(raw.map((item) => String(item || '').trim()).filter(Boolean)))
  }

  const text = String(raw || '').trim()
  if (!text) return []

  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) {
      return Array.from(
        new Set(parsed.map((item) => String(item || '').trim()).filter(Boolean))
      )
    }
  } catch (_) {
    // Fallback for legacy comma-separated values.
  }

  return Array.from(new Set(text.split(',').map((item) => item.trim()).filter(Boolean)))
}

function syncRoiTagOptionsToForm() {
  form.value.roi_tag_options = JSON.stringify(roiTagList.value)
}

function addRoiTag() {
  const tag = roiTagInput.value.trim()
  if (!tag) return

  if (roiTagList.value.includes(tag)) {
    ElMessage.warning(t('settings.roiTagExists'))
    return
  }

  roiTagList.value.push(tag)
  roiTagInput.value = ''
  syncRoiTagOptionsToForm()
}

function removeRoiTag(tag) {
  roiTagList.value = roiTagList.value.filter((item) => item !== tag)
  syncRoiTagOptionsToForm()
}

async function reload() {
  loading.value = true
  try {
    const data = await appSettingsStore.fetchSettings(true)
    Object.assign(form.value, data)
    roiTagList.value = parseRoiTagOptions(form.value.roi_tag_options)
    syncRoiTagOptionsToForm()
  } catch (err) {
    ElMessage.error(t('settings.failedToLoad', { message: err.message }))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    syncRoiTagOptionsToForm()
    const data = await appSettingsStore.updateSettings(form.value)
    Object.assign(form.value, data)
    roiTagList.value = parseRoiTagOptions(form.value.roi_tag_options)
    appSettingsStore.applyLanguage(form.value.ui_language)
    ElMessage.success(t('settings.settingsSaved'))
  } catch (err) {
    ElMessage.error(t('settings.failedToSave', { message: err.message }))
  } finally {
    saving.value = false
  }
}

function onSiteIconChange(uploadFile) {
  const raw = uploadFile?.raw
  if (!raw) return

  const maxBytes = 1024 * 1024
  if (raw.size > maxBytes) {
    ElMessage.warning(t('settings.iconTooLarge'))
    return
  }

  const reader = new FileReader()
  reader.onload = () => {
    if (typeof reader.result === 'string') {
      form.value.favicon_url = reader.result
    }
  }
  reader.readAsDataURL(raw)
}

function resetSiteIcon() {
  form.value.favicon_url = '/favicon.ico'
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

.icon-upload-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.roi-tags-editor {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.roi-tag-item {
  margin: 0;
}

.roi-tag-empty {
  color: #7f8bad;
  font-size: 12px;
}

.roi-tag-input-row {
  display: flex;
  gap: 8px;
}

.roi-tag-hint {
  margin-top: 6px;
  color: #8f9fbe;
  font-size: 12px;
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

  .roi-tag-input-row {
    flex-wrap: wrap;
  }
}
</style>
