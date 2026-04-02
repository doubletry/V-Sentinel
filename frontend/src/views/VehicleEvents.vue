<template>
  <div class="vehicle-events-page">
    <div class="page-header">
      <div class="header-left">
        <h2>{{ t('vehicleEvents.title') }}</h2>
        <p>{{ t('vehicleEvents.subtitle') }}</p>
      </div>
      <div class="header-right">
        <el-button size="small" @click="loadEvents" :loading="loading">
          {{ t('vehicleEvents.refresh') }}
        </el-button>
        <el-button type="primary" size="small" @click="sendSummaryNow" :loading="sendingSummary">
          {{ t('vehicleEvents.sendSummaryNow') }}
        </el-button>
      </div>
    </div>

    <div class="summary-card">
      <div class="summary-range">
        {{ t('vehicleEvents.range') }}:
        {{ formatDateTime(eventSince) }}
        ~
        {{ formatDateTime(eventUntil) }}
      </div>
      <div class="summary-text">{{ summaryText }}</div>
    </div>

    <div class="table-wrap">
      <el-table :data="vehicleEvents" stripe height="100%" v-loading="loading" class="events-table">
        <el-table-column prop="source_name" :label="t('vehicleEvents.source')" min-width="120" />
        <el-table-column prop="plate" :label="t('vehicleEvents.plate')" min-width="120" />
        <el-table-column :label="t('vehicleEvents.enterTime')" min-width="170">
          <template #default="{ row }">
            {{ formatDateTime(row.enter_time) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('vehicleEvents.exitTime')" min-width="170">
          <template #default="{ row }">
            {{ formatDateTime(row.exit_time) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('vehicleEvents.missingActions')" min-width="220">
          <template #default="{ row }">
            {{ (row.missing_actions || []).join('、') || t('vehicleEvents.none') }}
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ElMessage from 'element-plus/es/components/message/index'
import { vehicleEventsApi } from '../api/index.js'
import { useAppSettingsStore } from '../stores/appSettings.js'
import { formatDateTimeWithTimezone } from '../utils/time.js'

const { t } = useI18n()
const appSettingsStore = useAppSettingsStore()
const loading = ref(false)
const sendingSummary = ref(false)
const vehicleEvents = ref([])
const summaryText = ref('')
const eventSince = ref('')
const eventUntil = ref('')

function formatDateTime(timestamp) {
  return formatDateTimeWithTimezone(timestamp, appSettingsStore.timeZone)
}

async function loadEvents() {
  loading.value = true
  try {
    const result = await vehicleEventsApi.today()
    vehicleEvents.value = Array.isArray(result.visits) ? result.visits : []
    summaryText.value = result.summary_text || ''
    eventSince.value = result.since || ''
    eventUntil.value = result.until || ''
  } catch (err) {
    ElMessage.error(t('vehicleEvents.loadFailed', { message: err.message }))
  } finally {
    loading.value = false
  }
}

async function sendSummaryNow() {
  sendingSummary.value = true
  try {
    const result = await vehicleEventsApi.sendSummaryNow()
    summaryText.value = result.summary_text || ''
    eventSince.value = result.since || ''
    eventUntil.value = result.until || ''
    ElMessage.success(
      t('vehicleEvents.sendSummaryNowSuccess', { count: result.visit_count ?? 0 })
    )
  } catch (err) {
    ElMessage.error(t('vehicleEvents.sendSummaryNowFailed', { message: err.message }))
  } finally {
    sendingSummary.value = false
  }
}

onMounted(() => {
  loadEvents()
})
</script>

<style scoped>
.vehicle-events-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #0d0d1a;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.header-left h2 {
  color: #e9f0ff;
  font-size: 16px;
  font-weight: 600;
}

.header-left p {
  margin-top: 4px;
  color: #9db2da;
  font-size: 12px;
}

.header-right {
  display: flex;
  gap: 8px;
}

.summary-card {
  margin: 12px;
  padding: 14px 16px;
  border: 1px solid #39517d;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(32, 53, 88, 0.96), rgba(18, 31, 54, 0.98));
  color: #edf4ff;
}

.summary-range {
  margin-bottom: 8px;
  font-size: 13px;
  color: #b9cdf0;
}

.summary-text {
  line-height: 1.7;
  white-space: pre-wrap;
  color: #f5f8ff;
}

.table-wrap {
  flex: 1;
  min-height: 0;
  padding: 0 12px 12px;
}

.events-table {
  width: 100%;
}

@media (max-width: 900px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
