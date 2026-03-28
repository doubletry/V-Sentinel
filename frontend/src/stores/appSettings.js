import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import config from '../config.js'
import { settingsApi } from '../api/index.js'
import { setI18nLocale } from '../i18n/index.js'

const DEFAULT_UI_SETTINGS = {
  ui_language: 'zh-CN',
  site_title: config.siteName,
  site_description: config.siteDescription,
  favicon_url: '/favicon.ico',
  mediamtx_rtsp_addr: 'rtsp://localhost:8554',
  mediamtx_webrtc_addr: config.mediamtxWebrtcUrl || 'http://localhost:8889',
}

function withDefaults(data = {}) {
  return {
    ...DEFAULT_UI_SETTINGS,
    ...data,
  }
}

export const useAppSettingsStore = defineStore('appSettings', () => {
  const settings = ref(withDefaults())
  const loading = ref(false)
  const loaded = ref(false)

  const siteTitle = computed(() => settings.value.site_title || DEFAULT_UI_SETTINGS.site_title)
  const siteDescription = computed(() => settings.value.site_description || DEFAULT_UI_SETTINGS.site_description)
  const uiLanguage = computed(() => settings.value.ui_language || DEFAULT_UI_SETTINGS.ui_language)
  const faviconUrl = computed(() => settings.value.favicon_url || DEFAULT_UI_SETTINGS.favicon_url)
  const siteIconUrl = computed(() => faviconUrl.value)
  const mediamtxRtspAddr = computed(
    () => settings.value.mediamtx_rtsp_addr || DEFAULT_UI_SETTINGS.mediamtx_rtsp_addr
  )
  const mediamtxWebrtcAddr = computed(
    () => settings.value.mediamtx_webrtc_addr || DEFAULT_UI_SETTINGS.mediamtx_webrtc_addr
  )

  async function fetchSettings(force = false) {
    if (loaded.value && !force) {
      return settings.value
    }

    loading.value = true
    try {
      const data = await settingsApi.get()
      settings.value = withDefaults(data)
      loaded.value = true
      return settings.value
    } finally {
      loading.value = false
    }
  }

  async function updateSettings(payload) {
    const data = await settingsApi.update(payload)
    settings.value = withDefaults(data)
    loaded.value = true
    return settings.value
  }

  function patchSettings(partial) {
    settings.value = withDefaults({
      ...settings.value,
      ...partial,
    })
  }

  function applyLanguage(language) {
    const locale = language || uiLanguage.value
    setI18nLocale(locale)
  }

  return {
    settings,
    loading,
    loaded,
    siteTitle,
    siteDescription,
    uiLanguage,
    faviconUrl,
    siteIconUrl,
    mediamtxRtspAddr,
    mediamtxWebrtcAddr,
    fetchSettings,
    updateSettings,
    patchSettings,
    applyLanguage,
  }
})
