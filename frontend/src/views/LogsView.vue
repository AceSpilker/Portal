<script setup lang="ts">
/** 日志中心（072）：操作审计（audit_logs）+ 系统日志（system_logs）双标签，管理员专用。 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AuditPanel from '../components/AuditPanel.vue'
import SystemLogPanel from '../components/SystemLogPanel.vue'

const { t } = useI18n()
const tab = ref<'audit' | 'system'>('audit')
</script>

<template>
  <div class="logs-view fade-up">
    <h2 class="page-title">{{ t('logs.title') }}</h2>
    <p class="page-desc">{{ t('logs.desc') }}</p>

    <el-tabs v-model="tab" class="glass tabs-card">
      <el-tab-pane :label="t('logs.tabAudit')" name="audit">
        <AuditPanel />
      </el-tab-pane>
      <el-tab-pane :label="t('logs.tabSystem')" name="system" lazy>
        <SystemLogPanel />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.logs-view {
  padding: 4px 2px 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overscroll-behavior: contain;
}
.page-title {
  margin: 0 0 4px;
  font-size: 20px;
}
.page-desc {
  margin: 0 0 14px;
  font-size: 13px;
  color: var(--p-muted);
}
.tabs-card {
  padding: 4px 14px 14px;
  border-radius: 12px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.tabs-card :deep(.el-tabs) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.tabs-card :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.tabs-card :deep(.el-tab-pane) {
  height: 100%;
}
</style>
