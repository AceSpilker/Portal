<script setup lang="ts">
import { computed } from 'vue'
import { ElConfigProvider } from 'element-plus'
import { useI18n } from 'vue-i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import enLocale from 'element-plus/es/locale/lang/en'
import i18n from './locales'
import { useTheme } from './composables/useTheme'
import { useOpenApp } from './composables/useOpenApp'
import EntryPopup from './components/EntryPopup.vue'
import { isMobile } from './composables/useIsMobile'

// Element Plus 组件内置文案跟随语言切换
const elLocale = computed(() => (i18n.global.locale.value === 'en' ? enLocale : zhCn))
const { t } = useI18n()

// 外观主题（M02-18/19/20）：暗色/主题色/壁纸，全局监听即时生效
useTheme()

// 应用打开编排的全局浮层（入口选择 + iframe 内嵌），首页/命令面板共享
const { popupApp, popupVisible, iframeApp, iframeVisible, onChooseEntry } = useOpenApp()
</script>

<template>
  <ElConfigProvider :locale="elLocale">
    <!-- 自定义壁纸层（P4.6）：变量由 useTheme 写入 html，opacity=0 时不可见 -->
    <div class="wallpaper-layer" aria-hidden="true" />
    <!-- 不包顶层 <transition>：out-in 编排一旦被打断会死锁（视图插不回、白屏需刷新）；
         页面入场效果由各视图自身的 fade-up / stagger 动画承担 -->
    <router-view />

    <!-- 全局多入口选择浮层（M04-12）与 iframe 内嵌窗（M03-9） -->
    <EntryPopup v-model="popupVisible" :app="popupApp" @choose="onChooseEntry" />
    <el-dialog
      v-model="iframeVisible"
      :title="iframeApp?.name"
      :width="isMobile ? '96%' : '78%'"
      destroy-on-close
      append-to-body
    >
      <iframe
        v-if="iframeVisible && iframeApp"
        :src="iframeApp.urls[0]?.url"
        class="global-iframe"
        :title="iframeApp.name"
      />
      <template #footer>
        <el-button @click="iframeApp && onChooseEntry(iframeApp, iframeApp.urls[0]?.url ?? '')">
          {{ t('home.iframeNewTab') }}
        </el-button>
        <el-button type="primary" class="btn-gradient" @click="iframeVisible = false">
          {{ t('common.close') }}
        </el-button>
      </template>
    </el-dialog>
  </ElConfigProvider>
</template>

<style>
.wallpaper-layer {
  position: fixed;
  inset: -24px; /* 模糊边缘外扩，避免露出暗边 */
  z-index: -1;
  pointer-events: none;
  background: var(--p-wallpaper-bg, none);
  filter: var(--p-wallpaper-filter, none);
  opacity: var(--p-wallpaper-opacity, 0);
}
.global-iframe {
  width: 100%;
  height: min(68vh, 720px);
  border: none;
  border-radius: 10px;
  background: var(--p-card);
}
</style>
