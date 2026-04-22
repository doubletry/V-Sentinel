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
let _reconnectTimer = null
let _reconnectAttempts = 0
let _shouldReconnect = false
const MAX_RECONNECT_DELAY = 30000 // 30s cap
const STREAM_PENDING_RETRY_DELAY = 1000

function _scheduleReconnect(delayOverride = null) {
  if (!_shouldReconnect || !props.streamPath) return
  if (_reconnectTimer) return
  // Exponential backoff: 2s, 4s, 8s, 16s, 30s cap
  const delay = delayOverride ?? Math.min(2000 * Math.pow(2, _reconnectAttempts), MAX_RECONNECT_DELAY)
  _reconnectAttempts++
  _reconnectTimer = setTimeout(() => {
    _reconnectTimer = null
    if (_shouldReconnect && props.streamPath) connect()
  }, delay)
}

function _cancelReconnect() {
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer)
    _reconnectTimer = null
  }
}

async function connect() {
  if (!props.streamPath) return
  _shouldReconnect = true
  error.value = ''
  connected.value = false

  if (_conn) {
    _conn.stop()
    _conn = null
  }

  try {
    _conn = await connectWebRTC(props.streamPath, videoEl.value)
    if (!_shouldReconnect) {
      _conn?.stop?.()
      _conn = null
      return
    }
    connected.value = true
    _reconnectAttempts = 0

    // Monitor connection state for auto-reconnect
    if (_conn.pc) {
      _conn.pc.onconnectionstatechange = () => {
        const state = _conn?.pc?.connectionState
        if (_shouldReconnect && (state === 'failed' || state === 'disconnected' || state === 'closed')) {
          connected.value = false
          error.value = t('videoPlayer.connectionLost')
          _scheduleReconnect()
        }
      }
    }
  } catch (err) {
    const message = err.message || t('videoPlayer.connectionFailed')
    if (err?.name === 'WHEPError' && err?.status === 404) {
      error.value = ''
      _scheduleReconnect(STREAM_PENDING_RETRY_DELAY)
      return
    }
    error.value = message
    _scheduleReconnect()
  }
}

function disconnect() {
  _shouldReconnect = false
  _cancelReconnect()
  if (_conn) {
    _conn.stop()
    _conn = null
  }
  connected.value = false
  _reconnectAttempts = 0
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
