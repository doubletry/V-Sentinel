import { createI18n } from 'vue-i18n'
import zhCN from './locales/zh-CN.js'
import enUS from './locales/en-US.js'

export const LOCALE_STORAGE_KEY = 'v-sentinel.locale'
const FALLBACK_LOCALE = 'zh-CN'

const messages = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

export const localeOptions = [
  { value: 'zh-CN', labelKey: 'language.zhCN' },
  { value: 'en-US', labelKey: 'language.enUS' },
]

function normalizeLocale(value) {
  return Object.prototype.hasOwnProperty.call(messages, value)
    ? value
    : FALLBACK_LOCALE
}

function getInitialLocale() {
  if (typeof window === 'undefined') {
    return FALLBACK_LOCALE
  }
  const saved = window.localStorage.getItem(LOCALE_STORAGE_KEY)
  return normalizeLocale(saved)
}

const initialLocale = getInitialLocale()

if (typeof document !== 'undefined') {
  document.documentElement.lang = initialLocale
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  fallbackLocale: FALLBACK_LOCALE,
  messages,
})

export function setI18nLocale(locale) {
  const normalized = normalizeLocale(locale)
  i18n.global.locale.value = normalized

  if (typeof window !== 'undefined') {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, normalized)
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = normalized
  }

  return normalized
}
