<template>
  <div class="video-player-wrapper">
    <video
      ref="videoEl"
      class="video-element"
      autoplay
      muted
      playsinline
    />
    <div v-if="!connected && !error" class="video-placeholder">
      <el-icon :size="40" color="#555"><VideoCamera /></el-icon>
      <span>{{ t('videoPlayer.connecting') }}</span>
    </div>
    <div v-if="error" class="video-placeholder error">
      <el-icon :size="40" color="#f56c6c"><CircleClose /></el-icon>
      <span>{{ error }}</span>
      <el-button size="small" type="primary" @click="connect">{{ t('common.retry') }}</el-button>
    </div>
    <div v-if="label" class="video-label">{{ label }}</div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { connectWebRTC } from '../utils/webrtc.js'
import { useAppSettingsStore } from '../stores/appSettings.js'

const props = defineProps({
  streamPath: {
    type: String,
    default: '',
  },
  label: {
    type: String,
    default: '',
  },
})

const videoEl = ref(null)
const connected = ref(false)
const error = ref('')
const { t } = useI18n()
const appSettingsStore = useAppSettingsStore()
let _conn = null

async function connect() {
  if (!props.streamPath) return
  error.value = ''
  connected.value = false

  if (_conn) {
    _conn.stop()
    _conn = null
  }

  try {
    _conn = await connectWebRTC(props.streamPath, videoEl.value, appSettingsStore.mediamtxWebrtcAddr)
    connected.value = true
  } catch (err) {
    error.value = err.message || t('videoPlayer.connectionFailed')
  }
}

function disconnect() {
  if (_conn) {
    _conn.stop()
    _conn = null
  }
  connected.value = false
}

watch(() => props.streamPath, (newPath) => {
  disconnect()
  if (newPath) connect()
})

onMounted(() => {
  if (!appSettingsStore.loaded) {
    appSettingsStore.fetchSettings().catch(() => {
      // Keep fallback defaults when settings API is unavailable.
    })
  }

  if (props.streamPath) connect()
})

onBeforeUnmount(() => {
  disconnect()
})
</script>

<style scoped>
.video-player-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  background: #0d0d1a;
  overflow: hidden;
}

.video-element {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.video-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #888;
  font-size: 13px;
}

.video-placeholder.error {
  color: #f56c6c;
}

.video-label {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
}
</style>
