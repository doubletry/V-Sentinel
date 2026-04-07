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
        <span class="msg-time">{{ formatTimeWithTimezone(msg.timestamp, appSettingsStore.timeZone) }}</span>
      </div>
      <div class="msg-body">{{ msg.message }}</div>
      <div v-if="messageImageSrc(msg)" class="msg-image">
        <img
          :src="messageImageSrc(msg)"
          alt="snapshot"
          @dblclick="openPreview(messageImageSrc(msg))"
        />
      </div>
    </div>

    <div v-if="!messages.length" class="empty-msgs">
      <el-icon :size="32" color="#555"><ChatRound /></el-icon>
      <span>{{ t('messageList.noMessages') }}</span>
    </div>

    <el-dialog v-model="previewVisible" width="70%" top="5vh" append-to-body>
      <img v-if="previewImage" :src="previewImage" alt="preview" class="preview-image" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppSettingsStore } from '../stores/appSettings.js'
import { formatTimeWithTimezone } from '../utils/time.js'

const props = defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
})

const { t } = useI18n()
const appSettingsStore = useAppSettingsStore()
const previewVisible = ref(false)
const previewImage = ref('')

function levelType(level) {
  const map = { info: '', warning: 'warning', alert: 'danger' }
  return map[level] ?? ''
}

function messageImageSrc(message) {
  if (message?.image_url) return message.image_url
  if (message?.image_base64) return `data:image/jpeg;base64,${message.image_base64}`
  return ''
}

function openPreview(imageSrc) {
  previewImage.value = imageSrc
  previewVisible.value = true
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
  min-width: 0;
}

.msg-source {
  font-size: 13px;
  font-weight: 600;
  color: #aaa;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-time {
  margin-left: auto;
  font-size: 13px;
  color: #9aa6c0;
  font-weight: 600;
  white-space: nowrap;
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
  width: auto;
  max-width: min(100%, 360px);
  max-height: 220px;
  border-radius: 4px;
  object-fit: contain;
  cursor: zoom-in;
  image-rendering: auto;
}

.preview-image {
  width: 100%;
  max-height: 75vh;
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
