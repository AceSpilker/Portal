<template>
  <div class="lan-page">
    <el-tabs v-model="tab" class="glass tabs-card">
      <!-- ======== 设备清单 ======== -->
      <el-tab-pane :label="t('lan.tabDevices')" name="devices">
        <div class="ov-toolbar">
          <span class="stat-chip">{{ t('lan.statTotal') }} <b>{{ devices.length }}</b></span>
          <span class="stat-chip">{{ t('lan.statOnline') }} <b>{{ onlineCount }}</b></span>
          <span class="stat-chip">{{ t('lan.statRouter') }} <b>{{ routerCount }}</b></span>
          <span v-if="scanRunning" class="stat-chip scan-chip">
            {{ t('lan.scanning') }} <b>{{ current?.progress ?? 0 }}%</b>
          </span>
          <span class="spacer" />
          <el-select v-model="typeFilter" size="small" clearable style="width: 130px" :placeholder="t('lan.allTypes')">
            <el-option v-for="tp in deviceTypes" :key="tp" :value="tp" :label="t(`lan.type.${tp}`)" />
          </el-select>
          <el-button size="small" type="primary" :loading="scanStarting" :disabled="scanRunning" @click="startScan">
            {{ t('lan.scanNow') }}
          </el-button>
          <el-button v-if="auth.isAdmin" size="small" @click="openSettings">{{ t('lan.settings') }}</el-button>
          <el-button size="small" :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
        </div>
        <div class="table-fill">
          <el-table :data="filteredDevices" size="small" height="100%" v-loading="loading">
            <el-table-column :label="t('lan.colState')" width="80" align="center">
              <template #default="{ row }">
                <span class="state-pill" :class="row.online ? 'up' : 'down'">
                  {{ t(`lan.state.${row.online ? 'on' : 'off'}`) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="ip" label="IP" width="130" sortable />
            <el-table-column :label="t('lan.colType')" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.is_gateway" size="small" type="warning">{{ t('lan.type.router') }}</el-tag>
                <el-tag v-else size="small" :type="tagType(row.device_type)">{{ t(`lan.type.${row.device_type}`) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="hostname" :label="t('lan.colHostname')" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">{{ row.hostname || '—' }}</template>
            </el-table-column>
            <el-table-column prop="vendor" :label="t('lan.colVendor')" min-width="110" show-overflow-tooltip>
              <template #default="{ row }">{{ row.vendor || '—' }}</template>
            </el-table-column>
            <el-table-column prop="mac" label="MAC" width="150">
              <template #default="{ row }">{{ row.mac || '—' }}</template>
            </el-table-column>
            <el-table-column :label="t('lan.colPorts')" width="110">
              <template #default="{ row }">
                <span v-if="row.open_ports.length">{{ row.open_ports.join(', ') }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('lan.colOp')" width="150" align="center">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="openDevice(row)">{{ t('lan.detail') }}</el-button>
                <el-divider direction="vertical" />
                <el-button
                  v-if="auth.isAdmin && row.mac"
                  size="small" link type="primary" @click="addWol(row)"
                >WoL</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ======== 路由器 ======== -->
      <el-tab-pane :label="t('lan.tabRouter')" name="router">
        <RouterPanel v-if="tab === 'router'" />
      </el-tab-pane>

      <!-- ======== 数据库服务 ======== -->
      <el-tab-pane :label="t('lan.tabDb')" name="db">
        <DbPanel v-if="tab === 'db'" />
      </el-tab-pane>
    </el-tabs>

    <!-- 设备详情抽屉 -->
    <el-drawer v-model="deviceVisible" :title="device?.ip || t('lan.detail')" size="420px">
      <template v-if="device">
        <div class="info-body">
          <div class="info-sec">
            <h4>{{ t('lan.secBasic') }}</h4>
            <div class="info-well">
              <span>IP <b>{{ device.ip }}</b></span>
              <span>MAC <b>{{ device.mac || '—' }}</b></span>
              <span>{{ t('lan.colHostname') }} <b>{{ device.hostname || '—' }}</b></span>
              <span>{{ t('lan.colVendor') }} <b>{{ device.vendor || '—' }}</b></span>
              <span>{{ t('lan.colType') }} <b>{{ t(`lan.type.${device.device_type}`) }}</b></span>
              <span>{{ t('lan.colPorts') }} <b>{{ device.open_ports.join(', ') || '—' }}</b></span>
              <span>{{ t('lan.colSource') }} <b>{{ device.source.join(' / ') }}</b></span>
            </div>
          </div>
          <div class="info-sec">
            <h4>{{ t('lan.secEvents') }}</h4>
            <el-table :data="device.events || []" size="small" max-height="260">
              <el-table-column :label="t('lan.colEvent')" width="90">
                <template #default="{ row }">
                  <span class="state-pill" :class="row.event === 'online' ? 'up' : 'down'">
                    {{ t(`lan.event.${row.event}`) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="created_at" :label="t('lan.colTime')" min-width="160">
                <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </div>
          <div v-if="auth.isAdmin" class="info-sec">
            <h4>{{ t('lan.secActions') }}</h4>
            <el-button
              v-if="device.open_ports.length" size="small" type="primary"
              :disabled="monitored" @click="addMonitor(device)"
            >{{ monitored ? t('lan.monitored') : t('lan.addMonitor') }}</el-button>
            <el-button v-if="device.mac" size="small" @click="addWol(device)">{{ t('lan.addWol') }}</el-button>
          </div>
        </div>
      </template>
    </el-drawer>

    <!-- 扫描设置（管理员） -->
    <el-dialog v-model="settingsVisible" :title="t('lan.settings')" width="560px">
      <el-form label-width="150px" label-position="left">
        <el-form-item :label="t('lan.setCidrs')">
          <el-select v-model="settings.scan_cidrs" multiple filterable allow-create default-first-option
            style="width: 100%" :placeholder="t('lan.setCidrsPh')">
            <el-option v-for="s in segmentOptions" :key="s.cidr" :value="s.cidr"
              :label="segmentLabel(s)" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('lan.setAuto')">
          <el-switch v-model="settings.auto_scan" />
          <span class="form-hint">{{ t('lan.setAutoHint') }}</span>
          <el-input-number v-if="settings.auto_scan" v-model="settings.scan_interval_min"
            :min="5" :max="1440" size="small" style="margin-left: 12px" />
          <span class="form-hint">min</span>
        </el-form-item>
        <el-form-item :label="t('lan.setPorts')">
          <el-input v-model="portsText" :placeholder="t('lan.setPortsPh')" />
        </el-form-item>
        <el-form-item :label="t('lan.setDns')">
          <el-switch v-model="settings.dns_lookup" />
        </el-form-item>
        <el-form-item :label="t('lan.setConcurrency')">
          <el-input-number v-model="settings.concurrency" :min="16" :max="512" size="small" />
        </el-form-item>
        <el-form-item :label="t('lan.setDbPorts')">
          <el-input v-model="dbPortsText" :placeholder="t('lan.setDbPortsPh')" style="width: 260px" />
          <span class="form-hint">{{ t('lan.setDbPortsHint') }}</span>
        </el-form-item>
        <el-divider content-position="left">SNMP</el-divider>
        <el-form-item :label="t('lan.setSnmp')">
          <el-switch v-model="settings.snmp.enabled" />
          <span class="form-hint">{{ t('lan.setSnmpHint') }}</span>
        </el-form-item>
        <template v-if="settings.snmp.enabled">
          <el-form-item label="Community">
            <el-input v-model="settings.snmp.community" show-password style="width: 240px"
              :placeholder="settings.snmp_community_set ? t('lan.keepPlaceholder') : 'public'" />
            <el-button size="small" style="margin-left: 8px" :loading="snmpTesting" @click="testSnmp">
              {{ t('lan.snmpTest') }}
            </el-button>
          </el-form-item>
          <el-form-item :label="t('lan.setSnmpTimeout')">
            <el-input-number v-model="settings.snmp.timeout_s" :min="0.5" :max="10" :step="0.5" size="small" />
            <span class="form-hint">s</span>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="settingsVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="saveSettings">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { lanApi } from '../api/lan'
import type { LanDeviceItem, LanSegment, LanSettings, ScanRun } from '../api/lan'
import { useAuthStore } from '../stores/auth'
import RouterPanel from '../components/lan/RouterPanel.vue'
import DbPanel from '../components/lan/DbPanel.vue'
import dayjs from 'dayjs'

const { t } = useI18n()
const auth = useAuthStore()

const tab = ref('devices')
const loading = ref(false)
const devices = ref<LanDeviceItem[]>([])
const typeFilter = ref('')
const deviceVisible = ref(false)
const device = ref<LanDeviceItem | null>(null)
const monitored = ref(false)

const deviceTypes = ['router', 'nas', 'db', 'host', 'iot', 'printer', 'unknown'] as const

// ---- 扫描任务 ----
const scanStarting = ref(false)
const current = ref<ScanRun | null>(null)
const scanRunning = computed(() => current.value?.status === 'running')
let pollTimer: number | undefined

async function pollScan() {
  try {
    const data = await lanApi.scanStatus()
    const prevRunning = scanRunning.value
    current.value = data.current
    if (prevRunning && !scanRunning.value) {
      ElMessage.success(t('lan.scanDone', { found: data.current?.found ?? 0 }))
      await load()
    }
  } catch {
    /* 静默轮询 */
  }
}

async function startScan() {
  scanStarting.value = true
  try {
    await lanApi.startScan()
    current.value = { status: 'running', progress: 0 } as ScanRun
    ElMessage.success(t('lan.scanStarted'))
  } finally {
    scanStarting.value = false
  }
}

// ---- 设备清单 ----
const onlineCount = computed(() => devices.value.filter((d) => d.online).length)
const routerCount = computed(() => devices.value.filter((d) => d.is_gateway || d.device_type === 'router').length)
const filteredDevices = computed(() =>
  typeFilter.value ? devices.value.filter((d) => d.device_type === typeFilter.value) : devices.value,
)

async function load() {
  loading.value = true
  try {
    const data = await lanApi.devices()
    devices.value = data.items
  } finally {
    loading.value = false
  }
}

async function openDevice(row: LanDeviceItem) {
  device.value = await lanApi.device(row.id)
  monitored.value = false
  deviceVisible.value = true
}

async function addMonitor(row: LanDeviceItem) {
  await lanApi.createMonitor(row.id)
  monitored.value = true
  ElMessage.success(t('lan.monitorAdded'))
}

async function addWol(row: LanDeviceItem) {
  await lanApi.addWolTarget(row.id)
  ElMessage.success(t('lan.wolAdded'))
}

function tagType(tp: string): 'primary' | 'success' | 'info' | 'warning' | 'danger' {
  const map: Record<string, 'primary' | 'success' | 'info' | 'warning' | 'danger'> = {
    nas: 'success', db: 'danger', iot: 'primary', printer: 'warning', host: 'primary', unknown: 'info',
  }
  return map[tp] || 'info'
}

function fmtTime(ts: string) {
  return dayjs(ts).format('MM-DD HH:mm:ss')
}

// ---- 设置 ----
const settingsVisible = ref(false)
const settings = ref<LanSettings>({
  scan_cidrs: [], auto_scan: false, scan_interval_min: 30, probe_ports: [],
  dns_lookup: true, concurrency: 128, extra_cidrs: [], db_extra_ports: [],
  snmp: { enabled: false, community: '', timeout_s: 2 }, snmp_community_set: false,
})
const portsText = ref('')
const dbPortsText = ref('')
const segmentOptions = ref<LanSegment[]>([])
const saving = ref(false)
const snmpTesting = ref(false)

async function openSettings() {
  const [cfg, segs] = await Promise.all([lanApi.getSettings(), lanApi.segments()])
  settings.value = cfg
  portsText.value = cfg.probe_ports.join(', ')
  dbPortsText.value = (cfg.db_extra_ports || []).join(', ')
  segmentOptions.value = segs
  // 未配置过网段时预填 Portal 访问地址派生网段（NAS 容器部署时的宿主网段来源）
  if (!cfg.scan_cidrs.length && segs.length) {
    settings.value.scan_cidrs = [segs[0].cidr]
  }
  settingsVisible.value = true
}

function segmentLabel(s: LanSegment) {
  if (s.source === 'portal') {
    return `${s.cidr}（${t('lan.portalSegment')} ${s.address}）`
  }
  return `${s.cidr}（${s.iface}${s.gateway ? ' · GW ' + s.gateway : ''}）`
}

async function testSnmp() {
  snmpTesting.value = true
  try {
    const result = await lanApi.snmpTest({ community: settings.value.snmp.community || undefined })
    if (result.ok) {
      ElMessage.success(result.detail)
    } else {
      ElMessage.warning(result.detail)
    }
  } finally {
    snmpTesting.value = false
  }
}

async function saveSettings() {
  saving.value = true
  try {
    const ports = portsText.value.split(/[,\s]+/).map(Number).filter((n) => Number.isInteger(n) && n > 0)
    const dbPorts = dbPortsText.value.split(/[,\s]+/).map(Number).filter((n) => Number.isInteger(n) && n > 0)
    const body = {
      ...settings.value,
      probe_ports: ports,
      db_extra_ports: dbPorts,
      snmp: { ...settings.value.snmp, community: settings.value.snmp.community || '' },
    }
    settings.value = await lanApi.saveSettings(body)
    ElMessage.success(t('common.saved'))
    settingsVisible.value = false
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load()
  pollScan()
  pollTimer = window.setInterval(pollScan, 2000)
})
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
/* 与 PortsView 同一套页面骨架样式（082 全局滚动规范化 / 100 撑满约定） */
.lan-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.tabs-card {
  /* 主内容卡撑满右侧视口高度，各页签内部滚动（同 PortsView） */
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 10px 14px 14px;
  border-radius: 12px;
}
.tabs-card :deep(.el-tabs__header) {
  flex-shrink: 0;
}
.tabs-card :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
}
.tabs-card :deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: auto;
}
.ov-toolbar {
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
.scan-chip {
  color: var(--el-color-primary);
}
.table-fill {
  flex: 1;
  min-height: 0;
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
.form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--p-muted);
}
/* 设备详情抽屉（同 PortsView 端口画像弹窗的 info 结构） */
.info-body {
  min-height: 120px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.info-sec h4 {
  margin: 0 0 6px;
  font-size: 13px;
  color: var(--p-text);
}
.info-well {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
</style>
