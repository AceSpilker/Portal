<template>
  <div class="viewer">
    <div class="viewer-head">
      <h3>MySQL · {{ service.host }}:{{ service.port }}</h3>
      <el-tag v-if="overview" size="small" type="danger">v{{ overview.version }}</el-tag>
    </div>
    <el-tabs v-model="tab" @tab-change="onTab">
      <el-tab-pane :label="t('lan.mysql.overview')" name="overview">
        <div v-if="overview" class="stat-grid">
          <div class="glass stat-card"><b>{{ overview.threads_connected }}</b><span>{{ t('lan.mysql.conn') }}</span></div>
          <div class="glass stat-card"><b>{{ overview.threads_running }}</b><span>{{ t('lan.mysql.running') }}</span></div>
          <div class="glass stat-card"><b>{{ overview.qps_avg }}</b><span>QPS</span></div>
          <div class="glass stat-card"><b>{{ overview.slow_queries }}</b><span>{{ t('lan.mysql.slow') }}</span></div>
          <div class="glass stat-card"><b>{{ fmtDuration(overview.uptime_seconds) }}</b><span>{{ t('lan.mysql.uptime') }}</span></div>
          <div class="glass stat-card"><b>{{ fmtBytes(overview.bytes_sent) }}</b><span>{{ t('lan.mysql.sent') }}</span></div>
          <div class="glass stat-card wide"><b>{{ overview.hostname }}</b><span>hostname · {{ overview.datadir }}</span></div>
        </div>
      </el-tab-pane>
      <el-tab-pane :label="t('lan.mysql.schemas')" name="schemas">
        <div class="tab-toolbar">
          <el-input v-model="schemaFilter" size="small" clearable style="width: 220px"
            :placeholder="t('lan.mysql.schemaPh')" @keyup.enter="loadSchemas(1)" />
          <el-button size="small" @click="loadSchemas(1)">{{ t('common.search') }}</el-button>
          <span class="spacer" />
          <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total"
            layout="total, prev, pager, next" small @current-change="loadSchemas" />
        </div>
        <el-table :data="schemas" size="small" v-loading="loadingSchemas" max-height="420">
          <el-table-column prop="table_schema" :label="t('lan.mysql.schema')" min-width="130">
            <template #default="{ row }">
              <el-link size="small" @click="filterSchema(row.table_schema)">{{ row.table_schema }}</el-link>
            </template>
          </el-table-column>
          <el-table-column prop="table_name" :label="t('lan.mysql.table')" min-width="160" show-overflow-tooltip />
          <el-table-column prop="engine" label="Engine" width="90" />
          <el-table-column prop="table_rows" label="Rows" width="110" />
          <el-table-column prop="size_mb" label="Size (MB)" width="110" />
          <el-table-column :label="t('lan.colOp')" width="90" align="center">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="openRows(row)">{{ t('lan.mysql.data') }}</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 表数据浏览（库 → 表 → 数据；服务端白名单 SELECT + 分页截断） -->
        <el-dialog v-model="rowsVisible" :title="`${rowsTitle.schema}.${rowsTitle.table}`" width="82%" top="6vh" append-to-body>
          <div class="tab-toolbar">
            <span class="stat-chip">{{ t('lan.mysql.totalRows') }} <b>{{ rowsData?.total ?? 0 }}</b></span>
            <span class="spacer" />
            <el-pagination v-model:current-page="rowsPage" :page-size="rowsPageSize" :total="rowsData?.total ?? 0"
              layout="total, prev, pager, next" small @current-change="loadRows" />
          </div>
          <el-table :data="rowsData?.items || []" size="small" v-loading="loadingRows" max-height="52vh">
            <el-table-column v-for="col in rowsData?.columns || []" :key="col" :prop="col" :label="col"
              min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                <span :class="{ 'cell-null': row[col] === null }">{{ row[col] === null ? 'NULL' : row[col] }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-dialog>
      </el-tab-pane>
      <el-tab-pane :label="t('lan.mysql.variables')" name="variables">
        <el-input v-model="varQuery" size="small" clearable style="width: 260px; margin-bottom: 8px"
          :placeholder="t('lan.mysql.varPh')" @keyup.enter="loadVariables" />
        <el-table :data="variables" size="small" max-height="420">
          <el-table-column prop="Variable_name" label="Name" min-width="220" />
          <el-table-column prop="Value" label="Value" min-width="260" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>
      <el-tab-pane :label="t('lan.mysql.processlist')" name="processlist">
        <el-table :data="processlist" size="small" max-height="440">
          <el-table-column prop="Id" label="Id" width="80" />
          <el-table-column prop="User" label="User" width="110" />
          <el-table-column prop="Host" label="Host" min-width="160" show-overflow-tooltip />
          <el-table-column prop="db" label="DB" width="110" />
          <el-table-column prop="Command" label="Command" width="120" />
          <el-table-column prop="Time" label="Time(s)" width="90" />
          <el-table-column prop="state" label="State" min-width="140" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { lanDbApi } from '../../api/lan'
import type { DbServiceItem, MysqlOverview, MysqlSchemaRow } from '../../api/lan'

const props = defineProps<{ service: DbServiceItem }>()
const { t } = useI18n()

const tab = ref('overview')
const overview = ref<MysqlOverview | null>(null)
const schemas = ref<MysqlSchemaRow[]>([])
const schemaFilter = ref('')
const loadingSchemas = ref(false)
const page = ref(1)
const pageSize = 50
const total = ref(0)
const variables = ref<Array<{ Variable_name: string; Value: string }>>([])
const varQuery = ref('')
const processlist = ref<Array<Record<string, unknown>>>([])

const rowsVisible = ref(false)
const rowsTitle = ref({ schema: '', table: '' })
const rowsData = ref<Awaited<ReturnType<typeof lanDbApi.mysqlRows>> | null>(null)
const rowsPage = ref(1)
const rowsPageSize = 100
const loadingRows = ref(false)

const loaded = new Set<string>()

async function onTab(name: string | number) {
  await ensure(name.toString())
}

function filterSchema(schema: string) {
  schemaFilter.value = schema
  loadSchemas(1)
}

function openRows(row: MysqlSchemaRow) {
  rowsTitle.value = { schema: row.table_schema, table: row.table_name }
  rowsPage.value = 1
  rowsVisible.value = true
  loadRows(1)
}

async function loadRows(p = 1) {
  loadingRows.value = true
  try {
    rowsPage.value = p
    rowsData.value = await lanDbApi.mysqlRows(props.service.id, {
      schema: rowsTitle.value.schema, table: rowsTitle.value.table,
      page: p, page_size: rowsPageSize,
    })
  } finally {
    loadingRows.value = false
  }
}

async function ensure(name: string) {
  if (loaded.has(name)) return
  loaded.add(name)
  if (name === 'schemas') await loadSchemas(1)
  if (name === 'variables') await loadVariables()
  if (name === 'processlist') await loadProcesslist()
}

async function loadSchemas(p = 1) {
  loadingSchemas.value = true
  try {
    page.value = p
    const data = await lanDbApi.mysqlSchemas(props.service.id, {
      schema: schemaFilter.value, page: p, page_size: pageSize,
    })
    schemas.value = data.items
    total.value = data.total
  } finally {
    loadingSchemas.value = false
  }
}

async function loadVariables() {
  const data = await lanDbApi.mysqlVariables(props.service.id, varQuery.value)
  variables.value = data.items
}

async function loadProcesslist() {
  processlist.value = (await lanDbApi.mysqlProcesslist(props.service.id)).items
}

function fmtBytes(n: number) {
  if (n > 1 << 30) return (n / (1 << 30)).toFixed(1) + ' GB'
  if (n > 1 << 20) return (n / (1 << 20)).toFixed(1) + ' MB'
  return (n / (1 << 10)).toFixed(1) + ' KB'
}

function fmtDuration(seconds: number) {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  return d > 0 ? `${d}d ${h}h` : `${h}h ${Math.floor((seconds % 3600) / 60)}m`
}

onMounted(async () => {
  overview.value = await lanDbApi.mysqlOverview(props.service.id)
  loaded.add('overview')
})
</script>

<style scoped>
.viewer {
  padding: 6px 2px;
}
.viewer-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.viewer-head h3 {
  margin: 0;
  font-size: 16px;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
}
.stat-card {
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-card b {
  font-size: 18px;
}
.stat-card span {
  font-size: 12px;
  color: var(--p-muted);
}
.stat-card.wide {
  grid-column: span 2;
}
.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.stat-chip {
  font-size: 12.5px;
  color: var(--p-muted);
  background: var(--p-soft);
  border-radius: 8px;
  padding: 3px 10px;
}
.stat-chip b {
  color: var(--p-text);
  margin-left: 2px;
}
.spacer {
  flex: 1;
}
.cell-null {
  color: var(--p-muted);
  font-style: italic;
}
</style>
