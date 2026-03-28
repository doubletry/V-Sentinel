<template>
  <el-config-provider>
    <el-container class="app-container">
      <el-header class="app-header">
        <div class="header-brand">
          <el-icon :size="22" color="#409EFF">
            <component :is="appSettingsStore.brandIcon" />
          </el-icon>
          <span class="brand-name">{{ appSettingsStore.siteTitle }}</span>
          <span class="brand-desc">{{ appSettingsStore.siteDescription }}</span>
        </div>
        <el-menu
          mode="horizontal"
          :router="true"
          :default-active="$route.path"
          background-color="#1a1a2e"
          text-color="#ccc"
          active-text-color="#409EFF"
          class="header-nav"
        >
          <el-menu-item index="/">
            <el-icon><component :is="appSettingsStore.navIcons.videoWall" /></el-icon>
            {{ t('nav.videoWall') }}
          </el-menu-item>
          <el-menu-item index="/messages">
            <el-icon><component :is="appSettingsStore.navIcons.messages" /></el-icon>
            {{ t('nav.messages') }}
          </el-menu-item>
          <el-menu-item index="/settings">
            <el-icon><component :is="appSettingsStore.navIcons.settings" /></el-icon>
            {{ t('nav.settings') }}
          </el-menu-item>
        </el-menu>

        <div class="header-tools">
          <span class="lang-label">{{ t('language.label') }}</span>
          <el-select v-model="localeModel" size="small" class="lang-select">
            <el-option
              v-for="option in localeOptions"
              :key="option.value"
              :label="t(option.labelKey)"
              :value="option.value"
            />
          </el-select>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { localeOptions, LOCALE_STORAGE_KEY, setI18nLocale } from './i18n/index.js'
import { useAppSettingsStore } from './stores/appSettings.js'

const { t, locale } = useI18n()
const appSettingsStore = useAppSettingsStore()

const localeModel = computed({
  get: () => locale.value,
  set: (value) => {
    setI18nLocale(value)
    appSettingsStore.patchSettings({ ui_language: value })
  },
})

function syncDocumentTitle(title) {
  if (typeof document !== 'undefined' && title) {
    document.title = title
  }
}

function syncFavicon(href) {
  if (typeof document === 'undefined') return

  const iconHref = href || '/favicon.ico'
  let link = document.querySelector("link[rel*='icon']")
  if (!link) {
    link = document.createElement('link')
    link.setAttribute('rel', 'icon')
    document.head.appendChild(link)
  }
  link.setAttribute('href', iconHref)
}

watch(() => appSettingsStore.siteTitle, syncDocumentTitle, { immediate: true })
watch(() => appSettingsStore.faviconUrl, syncFavicon, { immediate: true })

onMounted(async () => {
  try {
    await appSettingsStore.fetchSettings()

    if (typeof window !== 'undefined') {
      const hasSavedLocale = Boolean(window.localStorage.getItem(LOCALE_STORAGE_KEY))
      if (!hasSavedLocale) {
        setI18nLocale(appSettingsStore.uiLanguage)
      }
    }
  } catch (_) {
    // Keep local defaults when settings API is unavailable.
  }
})
</script>

<style>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  background: #0d0d1a;
  color: #eee;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  padding: 0 16px;
  height: 56px !important;
  flex-shrink: 0;
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 16px;
  min-width: 0;
}

.brand-name {
  font-size: 18px;
  font-weight: 700;
  color: #409EFF;
}

.brand-desc {
  font-size: 12px;
  color: #888;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 340px;
}

.header-nav {
  flex: 1;
  min-width: 0;
  border-bottom: none !important;
}

.header-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.lang-label {
  color: #888;
  font-size: 12px;
  white-space: nowrap;
}

.lang-select {
  width: 118px;
}

.app-main {
  flex: 1;
  overflow: hidden;
  padding: 0;
}

@media (max-width: 960px) {
  .brand-desc,
  .lang-label {
    display: none;
  }

  .lang-select {
    width: 90px;
  }
}
</style>
