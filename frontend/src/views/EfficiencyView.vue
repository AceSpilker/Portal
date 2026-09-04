<script setup lang="ts">
/**
 * 效率模块页（M13/M11/M12；dev-plan P16）：日程 / 文件 / 下载 三页签。
 * 文件与下载仅管理员可见（后端 M 权限兜底）。
 */
import { ref } from 'vue'
import { Calendar, Files, Download } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import SchedulePanel from '../components/SchedulePanel.vue'
import FilesPanel from '../components/FilesPanel.vue'
import DownloadsPanel from '../components/DownloadsPanel.vue'

const { t } = useI18n()
const auth = useAuthStore()

type TabKey = 'schedule' | 'files' | 'downloads'
const active = ref<TabKey>('schedule')

const TABS = [
  { key: 'schedule', icon: Calendar },
  { key: 'files', icon: Files },
  { key: 'downloads', icon: Download },
] as const
</script>

<template>
  <div class="eff">
    <header class="page-head">
      <h2>{{ t('nav.efficiency') }}</h2>
      <nav class="tabs">
        <button
          v-for="tb in TABS"
          :key="tb.key"
          type="button"
          class="tab"
          :class="{ active: active === tb.key }"
          @click="active = tb.key"
        >
          <el-icon :size="13"><component :is="tb.icon" /></el-icon>
          {{ t(`eff.tab.${tb.key}`) }}
        </button>
      </nav>
    </header>

    <SchedulePanel v-show="active === 'schedule'" />
    <FilesPanel v-if="auth.isAdmin" v-show="active === 'files'" />
    <DownloadsPanel v-if="auth.isAdmin" v-show="active === 'downloads'" />
  </div>
</template>

<style scoped>
.eff {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}
.page-head {
  display: flex;
  align-items: center;
  gap: 16px;
}
.page-head h2 {
  margin: 0;
  font-size: 18px;
}
.tabs {
  display: flex;
  gap: 6px;
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 14px;
  border: none;
  border-radius: 999px;
  background: var(--p-card);
  font-size: 13px;
  cursor: pointer;
  color: inherit;
}
.tab.active {
  background: color-mix(in srgb, var(--p-primary) 14%, var(--p-card));
  color: var(--p-primary);
  font-weight: 600;
}
</style>
