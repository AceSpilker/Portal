<script setup lang="ts">
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>

<template>
  <ElConfigProvider :locale="zhCn">
    <!-- 不包顶层 <transition>：out-in 编排一旦被打断会死锁（视图插不回、白屏需刷新）；
         页面入场效果由各视图自身的 fade-up / stagger 动画承担 -->
    <router-view />
  </ElConfigProvider>
</template>
