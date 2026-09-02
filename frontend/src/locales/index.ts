import { createI18n } from 'vue-i18n'
import zhCN from './zh-CN'
import en from './en'

export type AppLocale = 'zh-CN' | 'en'

export const LOCALE_KEY = 'portal.locale'
export const DEFAULT_LOCALE: AppLocale = 'zh-CN'

/** 读取本地语言偏好（默认中文）。 */
export function getLocale(): AppLocale {
  const saved = localStorage.getItem(LOCALE_KEY)
  return saved === 'en' ? 'en' : DEFAULT_LOCALE
}

export function setLocale(locale: AppLocale) {
  localStorage.setItem(LOCALE_KEY, locale)
  i18n.global.locale.value = locale
  // 后端按 Accept-Language 返回对应语言的错误/提示文案
  document.documentElement.setAttribute('lang', locale)
}

const i18n = createI18n({
  legacy: false,
  locale: getLocale(),
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN, en },
  missingWarn: false,
  fallbackWarn: false,
})

export default i18n
