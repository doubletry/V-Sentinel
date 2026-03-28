<template>
  <div class="message-list">
    <div
      v-for="(msg, idx) in messages"
      :key="idx"
      class="message-card"
      :class="[`level-${msg.level}`, { 'agent-summary': msg.source_id === '__agent__' }]"
    >
      <div class="msg-header">
        <el-tag
          :type="levelType(msg.level)"
          size="small"
          effect="dark"
        >
          {{ msg.source_id === '__agent__' ? t('messageList.summary') : msg.level.toUpperCase() }}
        </el-tag>
        <span class="msg-source">{{ msg.source_name }}</span>
        <span class="msg-time">{{ formatTime(msg.timestamp) }}</span>
      </div>
      <div class="msg-body">{{ msg.message }}</div>
      <div v-if="msg.image_base64" class="msg-image">
        <img :src="`data:image/jpeg;base64,${msg.image_base64}`" alt="snapshot" />
      </div>
    </div>

    <div v-if="!messages.length" class="empty-msgs">
      <el-icon :size="32" color="#555"><ChatRound /></el-icon>
      <span>{{ t('messageList.noMessages') }}</span>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

const props = defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
})

const { t } = useI18n()

function levelType(level) {
  const map = { info: '', warning: 'warning', alert: 'danger' }
  return map[level] ?? ''
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString()
}
</script>

<style scoped>
.message-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
}

.message-card {
  background: #1e1e2e;
  border-radius: 6px;
  padding: 10px 14px;
  border-left: 4px solid #555;
}

.message-card.level-info {
  border-left-color: #409EFF;
}

.message-card.level-warning {
  border-left-color: #e6a23c;
}

.message-card.level-alert {
  border-left-color: #f56c6c;
}

.message-card.agent-summary {
  background: #1a2a3e;
  border-left-color: #67c23a;
  border: 1px solid #2a3a4e;
}

.msg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.msg-source {
  font-size: 13px;
  font-weight: 600;
  color: #aaa;
}

.msg-time {
  margin-left: auto;
  font-size: 11px;
  color: #666;
}

.msg-body {
  font-size: 13px;
  color: #ccc;
  line-height: 1.5;
}

.msg-image {
  margin-top: 8px;
}

.msg-image img {
  max-width: 100%;
  max-height: 160px;
  border-radius: 4px;
  object-fit: contain;
}

.empty-msgs {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 10px;
  color: #555;
  font-size: 13px;
}
</style>
