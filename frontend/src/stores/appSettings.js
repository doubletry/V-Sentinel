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
  brand_icon: 'VideoCamera',
  nav_icon_video_wall: 'Monitor',
  nav_icon_messages: 'Bell',
  nav_icon_settings: 'Setting',
}

export const APP_ICON_OPTIONS = [
  { value: 'VideoCamera', labelKey: 'settings.iconVideoCamera' },
  { value: 'Monitor', labelKey: 'settings.iconMonitor' },
  { value: 'Bell', labelKey: 'settings.iconBell' },
  { value: 'Setting', labelKey: 'settings.iconSetting' },
  { value: 'Tools', labelKey: 'settings.iconTools' },
  { value: 'Camera', labelKey: 'settings.iconCamera' },
  { value: 'Notification', labelKey: 'settings.iconNotification' },
  { value: 'Operation', labelKey: 'settings.iconOperation' },
]

const ALLOWED_ICON_VALUES = new Set(APP_ICON_OPTIONS.map((item) => item.value))

function withDefaults(data = {}) {
  return {
    ...DEFAULT_UI_SETTINGS,
    ...data,
  }
}

function normalizeIcon(iconName, fallback) {
  return ALLOWED_ICON_VALUES.has(iconName) ? iconName : fallback
}

export const useAppSettingsStore = defineStore('appSettings', () => {
  const settings = ref(withDefaults())
  const loading = ref(false)
  const loaded = ref(false)

  const siteTitle = computed(() => settings.value.site_title || DEFAULT_UI_SETTINGS.site_title)
  const siteDescription = computed(() => settings.value.site_description || DEFAULT_UI_SETTINGS.site_description)
  const uiLanguage = computed(() => settings.value.ui_language || DEFAULT_UI_SETTINGS.ui_language)
  const faviconUrl = computed(() => settings.value.favicon_url || DEFAULT_UI_SETTINGS.favicon_url)
  const brandIcon = computed(() => normalizeIcon(settings.value.brand_icon, DEFAULT_UI_SETTINGS.brand_icon))
  const navIcons = computed(() => ({
    videoWall: normalizeIcon(settings.value.nav_icon_video_wall, DEFAULT_UI_SETTINGS.nav_icon_video_wall),
    messages: normalizeIcon(settings.value.nav_icon_messages, DEFAULT_UI_SETTINGS.nav_icon_messages),
    settings: normalizeIcon(settings.value.nav_icon_settings, DEFAULT_UI_SETTINGS.nav_icon_settings),
  }))

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
    brandIcon,
    navIcons,
    fetchSettings,
    updateSettings,
    patchSettings,
    applyLanguage,
  }
})
