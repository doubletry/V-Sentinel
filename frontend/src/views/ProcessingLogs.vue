<template>
  <div class="processing-logs-page">
    <div class="page-header">
      <div class="header-left">
        <h2>{{ t('processingLogs.title') }}</h2>
        <p>{{ t('processingLogs.subtitle') }}</p>
      </div>
      <div class="header-right">
        <el-button size="small" @click="loadLogs(logPage)">
          {{ t('processingLogs.refresh') }}
        </el-button>
      </div>
    </div>

    <div class="table-wrap">
      <el-table
        :data="logItems"
        size="small"
        height="100%"
        v-loading="logsLoading"
        class="logs-table"
        :empty-text="t('processingLogs.noLogs')"
      >
        <el-table-column :label="t('processingLogs.logTime')" width="172">
          <template #default="scope">
            {{ formatLogTime(scope.row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('processingLogs.logLevel')" width="100">
          <template #default="scope">
            <el-tag
              size="small"
              :type="scope.row.level === 'ERROR' ? 'danger' : scope.row.level === 'WARNING' ? 'warning' : 'info'"
              effect="dark"
            >
              {{ scope.row.level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('processingLogs.logModule')" prop="module" min-width="200" />
        <el-table-column :label="t('processingLogs.logMessage')" prop="message" min-width="420" />
      </el-table>
    </div>

    <div class="logs-pagination">
      <el-pagination
        background
        layout="prev, pager, next, total"
        :total="logTotal"
        :page-size="logPageSize"
        :current-page="logPage"
        @current-change="loadLogs"
      />
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ElMessage from 'element-plus/es/components/message/index'
import { processorApi } from '../api/index.js'

const { t } = useI18n()
const logsLoading = ref(false)
const logItems = ref([])
const logTotal = ref(0)
const logPage = ref(1)
const logPageSize = ref(12)
const logErrorNotified = ref(false)
let logTimer = null

function formatLogTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return Number.isNaN(date.getTime()) ? String(timestamp) : date.toLocaleString()
}

async function loadLogs(page = 1) {
  logPage.value = page
  logsLoading.value = true
  try {
    const data = await processorApi.logs(page, logPageSize.value)
    logItems.value = data.items || []
    logTotal.value = Number(data.total || 0)
    logErrorNotified.value = false
  } catch (err) {
    if (!logErrorNotified.value) {
      ElMessage.error(t('processingLogs.failedLoad', { message: err.message }))
      logErrorNotified.value = true
    }
  } finally {
    logsLoading.value = false
  }
}

onMounted(() => {
  loadLogs(1)
  logTimer = setInterval(() => {
    loadLogs(logPage.value)
  }, 5000)
})

onBeforeUnmount(() => {
  if (logTimer) {
    clearInterval(logTimer)
    logTimer = null
  }
})
</script>

<style scoped>
.processing-logs-page {
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

.header-left {
  min-width: 0;
}

.header-left h2 {
  color: #dce7ff;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.2;
}

.header-left p {
  margin-top: 4px;
  color: #8ea0c8;
  font-size: 12px;
}

.table-wrap {
  flex: 1;
  min-height: 0;
  padding: 12px;
}

.logs-table {
  width: 100%;
}

.logs-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 8px 12px 12px;
  border-top: 1px solid #26314d;
  background: #131a2e;
  flex-shrink: 0;
}

:deep(.logs-table .el-table__cell) {
  padding-top: 6px;
  padding-bottom: 6px;
}

@media (max-width: 900px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .logs-pagination {
    justify-content: center;
  }
}
</style>
