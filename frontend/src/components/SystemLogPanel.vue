<script setup lang="ts">
/** 系统日志面板（072）：system_logs 级别/关键词/范围筛选 + 分页 + 可选自动刷新。 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Refresh as IconRefresh } from '@element-plus/icons-vue'
import request from '../api/request'

interface SystemLogItem {
  id: number
  level: string
  logger: string
  message: string
  created_at: string
}

const { t } = useI18n()
const items = ref<SystemLogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const range = ref('7d')
const level = ref('')
const q = ref('')
const loading = ref(false)
const auto = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await request.get<never, { total: number; items: SystemLogItem[] }>(
      '/system-logs',
      { params: { range: range.value, level: level.value, q: q.value, page: page.value, page_size: pageSize } },
    )
    items.value = r.items
    total.value = r.total
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}

let timer: number | undefined
function reload() {
  page.value = 1
  load()
}
function setAuto(v: unknown) {
  window.clearInterval(timer)
  if (v) {
    timer = window.setInterval(() => {
      page.value = 1
      load()
    }, 5000)
  }
}
onMounted(() => {
  load()
})
onBeforeUnmount(() => window.clearInterval(timer))

const levelTag = (lv: string) => (lv === 'ERROR' ? 'danger' : lv === 'WARNING' ? 'warning' : 'info')
</script>

<template>
  <div class="syslog">
    <header class="bar glass">
      <el-select v-model="range" size="small" style="width: 110px" @change="reload">
        <el-option value="24h" :label="t('security.range24h')" />
        <el-option value="7d" :label="t('security.range7d')" />
        <el-option value="30d" :label="t('security.range30d')" />
        <el-option value="all" :label="t('security.rangeAll')" />
      </el-select>
      <el-select v-model="level" size="small" style="width: 130px" clearable :placeholder="t('logs.levelPh')" @change="reload">
        <el-option value="ERROR" label="ERROR" />
        <el-option value="WARNING" label="WARNING" />
        <el-option value="INFO" label="INFO" />
      </el-select>
      <el-input
        v-model="q"
        size="small"
        :placeholder="t('logs.keywordPh')"
        style="width: 200px"
        clearable
        @keyup.enter="page = 1; load()"
      />
      <el-button size="small" :icon="IconRefresh" circle @click="load" />
      <span class="spacer" />
      <span class="auto-label">{{ t('logs.autoRefresh') }}</span>
      <el-switch v-model="auto" size="small" @change="setAuto" />
    </header>

    <div class="table-fill">
      <el-table v-loading="loading" :data="items" size="small" height="100%" class="glass">
      <el-table-column :label="t('logs.colTime')" width="170">
        <template #default="{ row }">
          <span class="mono">{{ new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('logs.colLevel')" width="100">
        <template #default="{ row }">
          <el-tag :type="levelTag(row.level)" size="small">{{ row.level }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="logger" :label="t('logs.colLogger')" width="180" show-overflow-tooltip />
      <el-table-column prop="message" :label="t('logs.colMessage')" show-overflow-tooltip />
    </el-table>
      </div>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next, total"
      class="pager"
      @current-change="load"
    />
  </div>
</template>

<style scoped>
.table-fill {
  flex: 1;
  min-height: 0;
}
.pager {
  flex-shrink: 0;
}
.bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.spacer {
  flex: 1;
}
.auto-label {
  font-size: 12.5px;
  color: var(--p-muted);
}
.pager {
  margin-top: 10px;
  justify-content: flex-end;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
</style>
