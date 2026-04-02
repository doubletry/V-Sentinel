import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import config from '../config.js'
import { settingsApi } from '../api/index.js'
import { setI18nLocale } from '../i18n/index.js'

const DEFAULT_UI_SETTINGS = {
  ui_language: 'zh-CN',
  timezone: 'Asia/Shanghai',
  processor_plugin: 'truck',
  site_title: config.siteName,
  site_description: config.siteDescription,
  favicon_url: '/favicon.ico',
  roi_tag_options: '["person","vehicle","intrusion"]',
  mediamtx_rtsp_addr: 'rtsp://localhost:8554',
  mediamtx_webrtc_addr: config.mediamtxWebrtcUrl || 'http://localhost:8889',
  email_from_address: '',
  email_from_auth_code: '',
  email_to_addresses: '',
  email_cc_addresses: '',
  email_port: '50055',
  daily_summary_hour: '23',
  daily_summary_minute: '59',
  message_retention_days: '7',
}

function parseRoiTagOptions(raw) {
  if (Array.isArray(raw)) {
    return Array.from(
      new Set(raw.map((item) => String(item || '').trim()).filter(Boolean))
    )
  }

  const text = String(raw || '').trim()
  if (!text) return []

  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) {
      return Array.from(
        new Set(parsed.map((item) => String(item || '').trim()).filter(Boolean))
      )
    }
  } catch (_) {
    // Fallback to comma-separated parsing for backward compatibility.
  }

  return Array.from(
    new Set(text.split(',').map((item) => item.trim()).filter(Boolean))
  )
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
  const timeZone = computed(() => settings.value.timezone || DEFAULT_UI_SETTINGS.timezone)
  const faviconUrl = computed(() => settings.value.favicon_url || DEFAULT_UI_SETTINGS.favicon_url)
  const siteIconUrl = computed(() => faviconUrl.value)
  const roiTagOptions = computed(
    () => parseRoiTagOptions(settings.value.roi_tag_options || DEFAULT_UI_SETTINGS.roi_tag_options)
  )
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

  async function testEmail(payload) {
    return settingsApi.testEmail(payload)
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
    timeZone,
    faviconUrl,
    siteIconUrl,
    roiTagOptions,
    mediamtxRtspAddr,
    mediamtxWebrtcAddr,
    fetchSettings,
    updateSettings,
    testEmail,
    patchSettings,
    applyLanguage,
  }
})
