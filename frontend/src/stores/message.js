import { defineStore } from 'pinia'
import { ref } from 'vue'
import config from '../config.js'
import { messagesApi } from '../api/index.js'

export const useMessageStore = defineStore('message', () => {
  const messages = ref([])
  const wsConnected = ref(false)
  const filterSource = ref('')
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(20)
  const total = ref(0)
  let _ws = null
  let _reconnectTimer = null

  const pageSizeOptions = [20, 40, 60, 80, 100]

  async function fetchMessages(nextPage = page.value, nextPageSize = pageSize.value) {
    loading.value = true
    try {
      const data = await messagesApi.list({
        page: nextPage,
        page_size: nextPageSize,
        source_id: filterSource.value || undefined,
      })
      page.value = Number(data.page || nextPage)
      pageSize.value = Number(data.page_size || nextPageSize)
      total.value = Number(data.total || 0)
      messages.value = Array.isArray(data.items) ? data.items : []
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
        const matchesFilter = !filterSource.value || msg.source_id === filterSource.value
        if (!matchesFilter) return
        total.value += 1
        if (page.value === 1) {
          messages.value.unshift(msg)
          if (messages.value.length > pageSize.value) {
            messages.value = messages.value.slice(0, pageSize.value)
          }
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
    total.value = 0
  }

  function setFilterSource(sourceId) {
    filterSource.value = sourceId
  }

  return {
    messages,
    loading,
    page,
    pageSize,
    total,
    pageSizeOptions,
    wsConnected,
    filterSource,
    fetchMessages,
    connectWS,
    disconnectWS,
    clearMessages,
    setFilterSource,
  }
})
