/**
 * 应用打开编排（M03-9 + M04-10/12；dev-plan P4.1）。
 *
 * 统一首页磁贴 / 命令面板 / 入口浮层的打开链路。状态为模块级单例：
 * 入口选择浮层与 iframe 内嵌窗由 App.vue 全局渲染一次，任何调用方共享。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { PortalApp } from '../api/portal'

const popupApp = ref<PortalApp | null>(null)
const popupVisible = ref(false)
const iframeApp = ref<PortalApp | null>(null)
const iframeVisible = ref(false)

export function useOpenApp() {
  const { t } = useI18n()

  async function openApp(app: PortalApp) {
    if (!app.urls.length) {
      ElMessage.info(t('apps.noEntry'))
      return
    }
    if (app.urls.length > 1) {
      popupApp.value = app
      popupVisible.value = true
      return
    }
    openUrl(app, app.urls[0].url)
  }

  /** 按 open_mode 打开指定地址；iframe 模式弹全局内嵌窗。 */
  function openUrl(app: PortalApp, url: string) {
    if (!url) return
    if (app.open_mode === 'current') {
      window.location.href = url
      return
    }
    if (app.open_mode === 'iframe') {
      iframeApp.value = app
      iframeVisible.value = true
      return
    }
    window.open(url, '_blank', 'noopener')
  }

  /** 入口浮层选中入口后的回调（App.vue 中绑定到 EntryPopup @choose）。 */
  function onChooseEntry(app: PortalApp, url: string) {
    openUrl(app, url)
  }

  return {
    popupApp,
    popupVisible,
    iframeApp,
    iframeVisible,
    openApp,
    openUrl,
    onChooseEntry,
  }
}
