<script setup lang="ts">
/** 审计日志页（M01-14/M15-13；dev-plan P17.1）：筛选/分页/CSV 导出。 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Download as IconDownload, Refresh as IconRefresh } from '@element-plus/icons-vue'
import { settingsApi } from '../api/settings'

interface AuditItem {
  id: number
  user_id: number | null
  action: string
  detail: string
  ip: string
  created_at: string
}

const { t } = useI18n()
const items = ref<AuditItem[]>([])
const total = ref(0)
const page = ref(1)
const range = ref('7d')
const actionFilter = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await settingsApi.auditLogs({
      range: range.value,
      action: actionFilter.value,
      page: page.value,
    })
    items.value = r.items
    total.value = r.total
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

async function exportCsv() {
  try {
    const r = await settingsApi.auditExport(range.value)
    const blob = new Blob(['﻿' + r.csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = r.filename
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <div class="audit">
    <header class="bar glass">
      <el-select v-model="range" size="small" style="width: 110px" @change="page = 1; load()">
        <el-option value="24h" :label="t('security.range24h')" />
        <el-option value="7d" :label="t('security.range7d')" />
        <el-option value="30d" :label="t('security.range30d')" />
        <el-option value="all" :label="t('security.rangeAll')" />
      </el-select>
      <el-input
        v-model="actionFilter"
        size="small"
        :placeholder="t('security.actionPh')"
        style="width: 180px"
        clearable
        @keyup.enter="page = 1; load()"
      />
      <el-button size="small" :icon="IconRefresh" circle @click="load" />
      <span class="spacer" />
      <el-button size="small" :icon="IconDownload" @click="exportCsv">{{ t('security.exportCsv') }}</el-button>
    </header>

    <section class="glass table-card" v-loading="loading">
      <el-table :data="items" size="small" style="width: 100%">
        <el-table-column :label="t('security.colTime')" width="160">
          <template #default="{ row }">{{ row.created_at.replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column prop="action" :label="t('security.colAction')" width="140" />
        <el-table-column prop="detail" :label="t('security.colDetail')" min-width="240" show-overflow-tooltip />
        <el-table-column prop="ip" :label="t('security.colIp')" width="130" />
        <el-table-column prop="user_id" label="UID" width="70" />
      </el-table>
      <el-pagination
        v-model:current-page="page"
        layout="prev, pager, next"
        :page-size="50"
        :total="total"
        class="pager"
        @current-change="load"
      />
    </section>
  </div>
</template>

<style scoped>
.audit {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.bar {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 8px 14px;
}
.spacer {
  flex: 1;
}
.table-card {
  padding: 6px 10px 10px;
}
.pager {
  margin-top: 10px;
  justify-content: flex-end;
}
</style>
