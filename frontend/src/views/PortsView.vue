<script setup lang="ts">
/**
 * 端口监控页（M18-1~7；dev-plan P11）：总览看板（异常置顶）+ 监听清单 + 事件流水。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import {
  portsApi,
  type LookupRow,
  type ListenRow,
  type PortEventItem,
  type PortMonitorBody,
  type PortMonitorItem,
} from '../api/ports'
import { portalApi, type PortalApp } from '../api/portal'
import { portsAdvancedApi, type ExposedPort, type ListenChange, type PortLatencyHistory, type PublicReach } from '../api/ports'
import TunnelsPanel from '../components/TunnelsPanel.vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const { t } = useI18n()
const router = useRouter()

// ---------- 监控项 ----------
const items = ref<PortMonitorItem[]>([])
const listenRows = ref<ListenRow[]>([])
const events = ref<PortEventItem[]>([])
const apps = ref<PortalApp[]>([])
const loading = ref(false)
const filter = ref<'all' | 'down' | 'up'>('all')
const tab = ref<'monitors' | 'listen' | 'events' | 'tunnels'>('monitors')

// ---------- 端口进阶（P20.3/M18-8~12） ----------
const latDialog = ref(false)
const latTarget = ref<PortMonitorItem | null>(null)
const latData = ref<PortLatencyHistory | null>(null)
const latLoading = ref(false)
let latChart: echarts.ECharts | null = null

const histDialog = ref(false)
const listenChanges = ref<ListenChange[]>([])

const expDialog = ref(false)
const exposed = ref<ExposedPort[]>([])

const reachDialog = ref(false)
const reach = ref<PublicReach | null>(null)
const reachLoading = ref(false)

async function showLatency(row: PortMonitorItem) {
  latTarget.value = row
  latDialog.value = true
  latLoading.value = true
  try {
    latData.value = await portsAdvancedApi.latency(row.id, '24h')
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    latLoading.value = false
  }
  setTimeout(renderLatencyChart, 60)
}

function renderLatencyChart() {
  const el = document.getElementById('port-latency-chart')
  if (!el || !latData.value) return
  if (!latChart) latChart = echarts.init(el)
  const pts = latData.value.points
  latChart.setOption({
    grid: { left: 44, right: 12, top: 14, bottom: 26 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: pts.map((p) => p.checked_at.slice(11, 16)), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { fontSize: 10, formatter: '{value}ms' } },
    series: [
      {
        type: 'line',
        data: pts.map((p) => (p.state === 'up' ? p.latency_ms : null)),
        connectNulls: false,
        smooth: true,
        symbolSize: 4,
      },
    ],
  })
  latChart.resize()
}

async function openListenHistory() {
  histDialog.value = true
  try {
    listenChanges.value = await portsAdvancedApi.listenHistory(20)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function openExposed() {
  expDialog.value = true
  try {
    exposed.value = await portsAdvancedApi.exposed()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function openPublicReach() {
  reachDialog.value = true
  reachLoading.value = true
  try {
    reach.value = await portsAdvancedApi.publicReach()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    reachLoading.value = false
  }
}

onUnmounted(() => {
  latChart?.dispose()
  latChart = null
})
let timer: number | undefined

const sorted = computed(() => {
  const rows = [...items.value]
  rows.sort((a, b) => {
    const rank = (m: PortMonitorItem) => (m.enabled ? (m.state === 'down' ? 0 : 1) : 2)
    if (rank(a) !== rank(b)) return rank(a) - rank(b)
    return a.id - b.id
  })
  if (filter.value === 'down') return rows.filter((r) => r.state === 'down' && r.enabled)
  if (filter.value === 'up') return rows.filter((r) => r.state === 'up')
  return rows
})

async function load() {
  loading.value = true
  try {
    const [mons, evs] = await Promise.all([portsApi.monitors(), portsApi.events(50)])
    items.value = mons
    events.value = evs
    if (tab.value === 'listen') listenRows.value = await portsApi.listen()
  } finally {
    loading.value = false
  }
}

function onTab(name: string | number) {
  if (name === 'listen') void portsApi.listen().then((r) => (listenRows.value = r))
}

onMounted(async () => {
  await load()
  apps.value = await portalApi.listApps().catch(() => [] as PortalApp[])
  timer = window.setInterval(load, 10000)
})
onUnmounted(() => window.clearInterval(timer))

// ---------- 添加/编辑 ----------
const dialog = ref(false)
const editing = ref<PortMonitorItem | null>(null)
const form = reactive<PortMonitorBody>({ name: '', host: '127.0.0.1', port: 8080, app_id: null, interval: 60, enabled: true })

function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', host: '127.0.0.1', port: 8080, app_id: null, interval: 60, enabled: true })
  dialog.value = true
}

function openEdit(m: PortMonitorItem) {
  editing.value = m
  Object.assign(form, {
    name: m.name, host: m.host, port: m.port, app_id: m.app_id,
    interval: m.interval, enabled: m.enabled,
  })
  dialog.value = true
}

async function save() {
  try {
    if (editing.value) await portsApi.update(editing.value.id, { ...form })
    else await portsApi.create({ ...form })
    ElMessage.success(t('ports.saved'))
    dialog.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function remove(m: PortMonitorItem) {
  const ok = await ElMessageBox.confirm(t('ports.confirmDelete', { name: m.name || `${m.host}:${m.port}` }), t('common.confirm'), {
    type: 'warning',
  }).then(
    () => true,
    () => false,
  )
  if (!ok) return
  await portsApi.remove(m.id)
  await load()
}

// ---------- 批量导入 ----------
const importDialog = ref(false)
const importText = ref('')

async function doImport() {
  const lines = importText.value.split('\n').map((s) => s.trim()).filter(Boolean)
  if (!lines.length) return
  try {
    const r = await portsApi.import(lines)
    ElMessage.success(t('ports.importOk', { created: r.created, skipped: r.skipped }))
    importDialog.value = false
    importText.value = ''
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

// ---------- 占用检索 ----------
const lookupPort = ref<number | null>(null)
const lookupRows = ref<LookupRow[] | null>(null)
async function doLookup() {
  if (!lookupPort.value) return
  try {
    lookupRows.value = await portsApi.lookup(lookupPort.value)
  } catch {
    lookupRows.value = []
  }
}

async function toggleEnabled(row: PortMonitorItem, enabled: unknown) {
  await portsApi.update(row.id, {
    name: row.name, host: row.host, port: row.port, app_id: row.app_id,
    interval: row.interval, enabled: Boolean(enabled),
  })
  row.enabled = Boolean(enabled)
}

function stateClass(s: string): string {
  return s === 'up' ? 'up' : s === 'down' ? 'down' : 'unknown'
}

function goApp(appId: number | null) {
  if (appId) void router.push('/apps')
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
</script>

<template>
  <div class="ports-page fade-up">
    <header class="page-head">
      <el-radio-group v-model="filter" size="small">
        <el-radio-button value="all">{{ t('ports.filterAll') }}</el-radio-button>
        <el-radio-button value="down">{{ t('ports.filterDown') }}</el-radio-button>
        <el-radio-button value="up">{{ t('ports.filterUp') }}</el-radio-button>
      </el-radio-group>
      <div class="head-ops">
        <el-input-number
          v-model="lookupPort"
          size="small"
          :min="1"
          :max="65535"
          :placeholder="t('ports.lookupPh')"
          :controls="false"
          style="width: 130px"
          @keyup.enter="doLookup"
        />
        <el-button size="small" @click="doLookup">{{ t('ports.lookup') }}</el-button>
        <el-button size="small" @click="importDialog = true">{{ t('ports.import') }}</el-button>
        <el-button type="primary" class="btn-gradient" size="small" :icon="Plus" @click="openCreate">
          {{ t('ports.add') }}
        </el-button>
      </div>
    </header>

    <!-- 占用检索结果 -->
    <section v-if="lookupRows" class="glass lookup-card">
      <header class="card-head">
        <h4>{{ t('ports.lookupResult', { port: lookupPort }) }}</h4>
        <el-button link size="small" @click="lookupRows = null">{{ t('common.close') }}</el-button>
      </header>
      <p v-if="!lookupRows.length" class="empty">{{ t('ports.lookupEmpty') }}</p>
      <div v-else class="lookup-list">
        <div v-for="(r, i) in lookupRows" :key="i" class="lookup-row">
          <span class="lk-proc">{{ r.proc }}</span>
          <span class="lk-cmd">{{ r.cmdline }}</span>
          <span class="lk-meta">PID {{ r.pid }} · {{ r.addr }} · {{ r.status }}</span>
        </div>
      </div>
    </section>

    <el-tabs v-model="tab" class="glass tabs-card" @tab-change="onTab">
      <!-- ======== 监控项看板 ======== -->
      <el-tab-pane :label="t('ports.tabMonitors')" name="monitors">
        <el-table :data="sorted" size="small" v-loading="loading">
          <el-table-column :label="t('ports.colState')" width="90" align="center">
            <template #default="{ row }">
              <span class="state-pill" :class="stateClass(row.enabled ? row.state : 'unknown')">
                {{ t(`ports.state.${row.enabled ? row.state : 'unknown'}`) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column :label="t('ports.colTarget')" min-width="170">
            <template #default="{ row }">
              <span class="mon-name">{{ row.name || `#${row.id}` }}</span>
              <span class="mon-addr">{{ row.host }}:{{ row.port }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('ports.colApp')" min-width="120">
            <template #default="{ row }">
              <el-link v-if="row.app_id" type="primary" @click="goApp(row.app_id)">{{ row.app_name }}</el-link>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('ports.colLatency')" width="90" align="right">
            <template #default="{ row }">
              {{ row.last_latency_ms !== null ? row.last_latency_ms + 'ms' : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="interval" :label="t('ports.colInterval')" width="80" align="right" />
          <el-table-column :label="t('ports.colTags')" min-width="110">
            <template #default="{ row }">
              <el-tag v-for="tg in row.tags || []" :key="tg" size="small" class="tag-item">{{ tg }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('ports.colActions')" width="180" align="right">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" size="small" @update:model-value="toggleEnabled(row, $event)" />
              <el-button link size="small" @click="showLatency(row)">{{ t('ports.curve') }}</el-button>
              <el-button link size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
              <el-button link size="small" type="danger" :icon="Delete" @click="remove(row)" />
            </template>
          </el-table-column>
          <template #empty>{{ t('ports.empty') }}</template>
        </el-table>

        <!-- 端口进阶工具（M18-9~11；P20.3） -->
        <div class="adv-row">
          <el-button size="small" @click="openListenHistory">{{ t('ports.listenHistory') }}</el-button>
          <el-button size="small" @click="openExposed">{{ t('ports.exposed') }}</el-button>
          <el-button size="small" @click="openPublicReach">{{ t('ports.publicReach') }}</el-button>
        </div>
      </el-tab-pane>

      <!-- ======== 监听清单 ======== -->
      <el-tab-pane :label="t('ports.tabListen')" name="listen">
        <el-table :data="listenRows" size="small" height="480">
          <el-table-column prop="proto" :label="t('ports.colProto')" width="70" />
          <el-table-column prop="addr" :label="t('ports.colAddr')" min-width="140" />
          <el-table-column prop="port" :label="t('ports.colPort')" width="90" />
          <el-table-column prop="proc" :label="t('ports.colProc')" min-width="130" />
          <el-table-column prop="cmdline" :label="t('ports.colCmdline')" min-width="240" show-overflow-tooltip />
          <el-table-column prop="pid" label="PID" width="90" />
        </el-table>
      </el-tab-pane>

      <!-- ======== 事件流水 ======== -->
      <el-tab-pane :label="t('ports.tabTunnels')" name="tunnels" lazy>
        <TunnelsPanel />
      </el-tab-pane>
      <el-tab-pane :label="t('ports.tabEvents')" name="events">
        <div v-if="!events.length" class="empty">{{ t('ports.noEvents') }}</div>
        <div v-else class="event-list">
          <div v-for="e in events" :key="e.id" class="event-row">
            <span class="ev-dot" :class="e.event" />
            <span class="ev-name">{{ e.monitor_name }}</span>
            <span class="ev-text" :class="e.event">
              {{ e.event === 'up' ? t('ports.evUp') : t('ports.evDown') }}
              <template v-if="e.latency_ms !== null"> · {{ e.latency_ms }}ms</template>
              <template v-if="e.app_name"> · {{ t('ports.evLinked') }}{{ e.app_name }}</template>
            </span>
            <span class="ev-time">{{ timeLabel(e.created_at) }}</span>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 添加/编辑对话框 -->
    <el-dialog v-model="dialog" :title="editing ? t('ports.edit') : t('ports.add')" width="440px">
      <el-form label-width="100px">
        <el-form-item :label="t('ports.fld.name')">
          <el-input v-model="form.name" maxlength="50" />
        </el-form-item>
        <el-form-item :label="t('ports.fld.host')">
          <el-input v-model="form.host" placeholder="127.0.0.1" />
        </el-form-item>
        <el-form-item :label="t('ports.fld.port')">
          <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('ports.colApp')">
          <el-select v-model="form.app_id" clearable style="width: 100%">
            <el-option v-for="a in apps" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('ports.colInterval')">
          <el-input-number v-model="form.interval" :min="10" :max="86400" :step="10" style="width: 100%" />
        </el-form-item>
        <el-form-item :label="t('notify.fld.enabled')">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="save">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入 -->
    <el-dialog v-model="importDialog" :title="t('ports.import')" width="440px">
      <p class="quiet-hint">{{ t('ports.importHint') }}</p>
      <el-input v-model="importText" type="textarea" :rows="6" :placeholder="t('ports.importPh')" />
      <template #footer>
        <el-button @click="importDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="doImport">{{ t('apps.importBtn') }}</el-button>
      </template>
    </el-dialog>

    <!-- 延迟曲线（P20.3/M18-8） -->
    <el-dialog append-to-body v-model="latDialog" :title="t('ports.latencyTitle', { name: latTarget?.name ?? '' })" width="640px">
      <p class="muted">
        {{ t('ports.latencyStats', {
          avg: latData?.avg_ms ?? '-', max: latData?.max_ms ?? '-', up: latData?.up_pct ?? '-' }) }}
      </p>
      <div id="port-latency-chart" style="width: 100%; height: 220px" />
    </el-dialog>

    <!-- 监听变更历史（M18-9） -->
    <el-dialog append-to-body v-model="histDialog" :title="t('ports.listenHistoryTitle')" width="620px">
      <div v-if="!listenChanges.length" class="muted">{{ t('common.noData') }}</div>
      <div v-for="h in listenChanges" :key="h.id" class="hist-card">
        <div class="hist-ts">{{ h.created_at.replace('T', ' ').slice(0, 19) }}</div>
        <div v-if="h.added.length" class="hist-added">
          + {{ h.added.map((a) => `${a.host}:${a.port}(${a.process})`).join('、') }}
        </div>
        <div v-if="h.removed.length" class="hist-removed">
          − {{ h.removed.map((a) => `${a.host}:${a.port}(${a.process})`).join('、') }}
        </div>
      </div>
    </el-dialog>

    <!-- 裸露端口（M18-10） -->
    <el-dialog append-to-body v-model="expDialog" :title="t('ports.exposedTitle')" width="520px">
      <el-table :data="exposed" size="small">
        <el-table-column prop="port" label="Port" width="100" />
        <el-table-column prop="process" :label="t('ports.colProcess')" min-width="160" />
        <el-table-column prop="host" label="Host" width="140" />
        <template #empty>{{ t('ports.exposedNone') }}</template>
      </el-table>
      <p class="muted" style="margin-top: 8px">{{ t('ports.exposedTip') }}</p>
    </el-dialog>

    <!-- 公网可达性对比（M18-11） -->
    <el-dialog append-to-body v-model="reachDialog" :title="t('ports.reachTitle')" width="560px">
      <div v-loading="reachLoading">
        <p v-if="reach" class="muted">
          {{ t('ports.reachIp', { ip: reach.public_ip ?? t('ports.reachUnknown') }) }}
        </p>
        <el-table :data="reach?.items ?? []" size="small">
          <el-table-column prop="name" :label="t('security.colName')" min-width="140" />
          <el-table-column prop="port" label="Port" width="90" />
          <el-table-column :label="t('ports.reachLocal')" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.local_state === 'up' ? 'success' : 'danger'">{{ row.local_state }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('ports.reachPublic')" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.public_reachable !== null" size="small" :type="row.public_reachable ? 'success' : 'danger'">
                {{ row.public_reachable ? '✓' : '✗' }}
              </el-tag>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <template #empty>{{ t('common.noData') }}</template>
        </el-table>
        <p class="muted" style="margin-top: 8px">{{ t('ports.reachTip') }}</p>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.ports-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.head-ops {
  display: flex;
  align-items: center;
  gap: 8px;
}
.lookup-card {
  padding: 12px 14px;
  border-radius: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-head h4 {
  margin: 0 0 4px;
}
.empty {
  color: var(--p-muted);
  font-size: 13px;
  padding: 8px 0;
}
.lookup-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
}
.lk-proc {
  font-weight: 700;
  min-width: 110px;
}
.lk-cmd {
  flex: 1;
  min-width: 0;
  color: var(--p-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tabs-card {
  padding: 10px 14px 14px;
  border-radius: 12px;
}
.state-pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
}
.state-pill.up { background: var(--el-color-success-light-8); color: var(--el-color-success); }
.state-pill.down { background: var(--el-color-danger-light-8); color: var(--el-color-danger); }
.state-pill.unknown { background: rgba(127, 127, 127, 0.15); color: var(--p-muted); }
.mon-name {
  font-weight: 600;
  margin-right: 8px;
}
.mon-addr {
  color: var(--p-muted);
  font-size: 12px;
}
.muted {
  color: var(--p-muted);
}
.event-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.event-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}
.ev-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ev-dot.up { background: var(--el-color-success); }
.ev-dot.down { background: var(--el-color-danger); }
.ev-name {
  font-weight: 600;
}
.ev-text {
  flex: 1;
  min-width: 0;
}
.ev-text.down { color: var(--el-color-danger); }
.ev-time {
  color: var(--p-muted);
  flex-shrink: 0;
}
.quiet-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--p-muted);
}
</style>
