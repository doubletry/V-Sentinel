import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import config from '../config.js'
import { messagesApi } from '../api/index.js'

export const useMessageStore = defineStore('message', () => {
  const messages = ref([])
  const wsConnected = ref(false)
  const filterSource = ref('')
  const loading = ref(false)
  let _ws = null
  let _reconnectTimer = null

  const filteredMessages = computed(() => {
    if (!filterSource.value) return messages.value
    return messages.value.filter((m) => m.source_id === filterSource.value)
  })

  async function fetchMessages() {
    loading.value = true
    try {
      const data = await messagesApi.list({ limit: 500 })
      messages.value = Array.isArray(data) ? data : []
      return messages.value
    } finally {
      loading.value = false
    }
  }

  function connectWS() {
    if (_ws && _ws.readyState === WebSocket.OPEN) return

    // Build WebSocket URL: if wsBaseUrl is empty (relative), derive from current page
    let wsBase = config.wsBaseUrl
    if (!wsBase) {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      wsBase = `${proto}//${window.location.host}`
    }
    const url = `${wsBase}/ws/messages`
    _ws = new WebSocket(url)

    _ws.onopen = () => {
      wsConnected.value = true
      if (_reconnectTimer) {
        clearTimeout(_reconnectTimer)
        _reconnectTimer = null
      }
    }

    _ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg === 'pong') return
        // Keep newest at front, limit to 500
        messages.value.unshift(msg)
        if (messages.value.length > 500) {
          messages.value = messages.value.slice(0, 500)
        }
      } catch (_) {
        // Ignore parse errors
      }
    }

    _ws.onclose = () => {
      wsConnected.value = false
      _ws = null
      // Auto reconnect after 3s
      _reconnectTimer = setTimeout(connectWS, 3000)
    }

    _ws.onerror = () => {
      _ws?.close()
    }
  }

  function disconnectWS() {
    if (_reconnectTimer) {
      clearTimeout(_reconnectTimer)
      _reconnectTimer = null
    }
    _ws?.close()
    _ws = null
    wsConnected.value = false
  }

  function clearMessages() {
    messages.value = []
  }

  function setFilterSource(sourceId) {
    filterSource.value = sourceId
  }

  return {
    messages,
    loading,
    wsConnected,
    filterSource,
    filteredMessages,
    fetchMessages,
    connectWS,
    disconnectWS,
    clearMessages,
    setFilterSource,
  }
})
