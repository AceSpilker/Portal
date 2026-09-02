<script setup lang="ts">
import { computed } from 'vue'
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import enLocale from 'element-plus/es/locale/lang/en'
import i18n from './locales'

// Element Plus 组件内置文案跟随语言切换
const elLocale = computed(() => (i18n.global.locale.value === 'en' ? enLocale : zhCn))
</script>

<template>
  <ElConfigProvider :locale="elLocale">
    <!-- 不包顶层 <transition>：out-in 编排一旦被打断会死锁（视图插不回、白屏需刷新）；
         页面入场效果由各视图自身的 fade-up / stagger 动画承担 -->
    <router-view />
  </ElConfigProvider>
</template>
