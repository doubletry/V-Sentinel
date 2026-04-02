<template>
  <div class="messages-page">
    <div class="page-header">
      <div class="header-left">
        <h2>{{ t('messages.title') }}</h2>
        <el-tag :type="store.wsConnected ? 'success' : 'danger'" size="small" effect="dark">
          {{ store.wsConnected ? t('messages.connected') : t('messages.disconnected') }}
        </el-tag>
      </div>
      <div class="header-right">
        <el-select
          v-model="filterSource"
          :placeholder="t('messages.allSources')"
          clearable
          size="small"
          style="width: 200px"
          @change="handleFilterChange"
        >
          <el-option
            v-for="src in sourceStore.sources"
            :key="src.id"
            :label="src.name"
            :value="src.id"
          />
        </el-select>
        <el-button
          v-if="store.pendingCount > 0"
          size="small"
          type="warning"
          @click="jumpToLatest"
        >
          {{ t('messages.newMessages', { count: store.pendingCount }) }}
        </el-button>
        <el-button size="small" @click="store.clearMessages">{{ t('messages.clear') }}</el-button>
      </div>
    </div>

    <el-scrollbar ref="scrollbar" class="messages-scroll">
      <MessageList :messages="store.messages" />
    </el-scrollbar>
    <div class="messages-pagination">
      <el-pagination
        background
        layout="sizes, prev, pager, next, total"
        :page-sizes="store.pageSizeOptions"
        :page-size="store.pageSize"
        :current-page="store.page"
        :total="store.total"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessageStore } from '../stores/message.js'
import { useSourceStore } from '../stores/source.js'
import MessageList from '../components/MessageList.vue'

const store = useMessageStore()
const sourceStore = useSourceStore()
const { t } = useI18n()
const filterSource = ref('')
const scrollbar = ref(null)

// Auto-scroll to top (newest first)
watch(
  () => store.messages.length,
  async () => {
    await nextTick()
    scrollbar.value?.setScrollTop(0)
  }
)

async function handlePageChange(nextPage) {
  await store.fetchMessages(nextPage, store.pageSize)
}

async function handleSizeChange(nextSize) {
  await store.fetchMessages(1, nextSize)
}

async function handleFilterChange(value) {
  store.setFilterSource(value || '')
  await store.fetchMessages(1, store.pageSize)
}

async function jumpToLatest() {
  await store.fetchMessages(1, store.pageSize)
}

onMounted(() => {
  store.fetchMessages(1, store.pageSize)
  store.connectWS()
  if (!sourceStore.sources.length) {
    sourceStore.fetchSources()
  }
})

onBeforeUnmount(() => {
  store.disconnectWS()
})
</script>

<style scoped>
.messages-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0d0d1a;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.header-left h2 {
  font-size: 16px;
  color: #ddd;
  font-weight: 600;
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 880px) {
  .page-header {
    flex-wrap: wrap;
    gap: 8px;
  }

  .header-right {
    width: 100%;
    justify-content: flex-end;
  }
}
.messages-scroll {
  flex: 1;
  min-height: 0;
}

.messages-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 8px 12px 12px;
  border-top: 1px solid #26314d;
  background: #131a2e;
  flex-shrink: 0;
}
</style>
