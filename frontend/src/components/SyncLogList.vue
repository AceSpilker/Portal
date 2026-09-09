<script setup lang="ts">
/**
 * 同步/连接事件日志列表（088）：MySQL 同步与 Redis 缓存面板共用。
 * 显示最近 N 条事件（时间/动作/状态/耗时/消息），kind 决定数据源。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Refresh as IconRefresh } from '@element-plus/icons-vue'
import { syncApi, type SyncLogItem } from '../api/sync'

const props = defineProps<{ kind: 'mysql' | 'redis' }>()

const { t } = useI18n()
const items = ref<SyncLogItem[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = (await syncApi.syncLogs(props.kind, 30)).items
  } catch {
    /* 静默：日志区失败不影响面板 */
  } finally {
    loading.value = false
  }
}

const statusType = (s: string): 'success' | 'danger' | 'info' =>
  s === 'ok' ? 'success' : s === 'failed' ? 'danger' : 'info'

/** ISO-UTC → 本地时间显示（DB 约定存 UTC） */
function fmtTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <section class="synclog glass">
    <header class="log-head">
      <h3>{{ t('sync.logTitle') }}</h3>
      <el-button size="small" :icon="IconRefresh" circle :loading="loading" @click="load" />
    </header>
    <el-table :data="items" size="small" v-loading="loading" max-height="300">
      <el-table-column :label="t('sync.logColTime')" width="150">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="action" :label="t('sync.logColAction')" width="92">
        <template #default="{ row }">
          <span class="action-cell">{{ row.action }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('sync.logColStatus')" width="84" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)" effect="plain">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('sync.logColDuration')" width="82" align="right">
        <template #default="{ row }">{{ row.duration_ms ? `${row.duration_ms}ms` : '-' }}</template>
      </el-table-column>
      <el-table-column prop="message" :label="t('sync.logColMessage')" min-width="200" show-overflow-tooltip />
    </el-table>
  </section>
</template>

<style scoped>
.synclog {
  padding: 12px 14px;
  border-radius: var(--p-radius);
}
.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.log-head h3 {
  margin: 0;
  font-size: 14px;
}
.action-cell {
  font-family: ui-monospace, monospace;
}
.log-empty {
  margin: 6px 0 2px;
  color: var(--p-muted);
  font-size: 12.5px;
  text-align: center;
}
</style>
