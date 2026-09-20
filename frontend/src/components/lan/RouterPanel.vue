<template>
  <div v-loading="loading" class="router-panel">
    <template v-if="info">
      <!-- 基础信息 -->
      <div class="card-row">
        <div class="glass sub-card">
          <h4>{{ t('lan.rBasic') }}</h4>
          <div class="kv" v-if="info.gateway_ip">
            <span>IP</span><b>{{ info.gateway_ip }}</b>
          </div>
          <div class="kv" v-if="info.device?.mac">
            <span>MAC</span><b>{{ info.device.mac }}</b>
          </div>
          <div class="kv" v-if="info.device?.vendor">
            <span>{{ t('lan.colVendor') }}</span><b>{{ info.device.vendor }}</b>
          </div>
          <div class="kv" v-if="info.device?.hostname">
            <span>{{ t('lan.colHostname') }}</span><b>{{ info.device.hostname }}</b>
          </div>
          <div class="kv" v-if="upnp?.friendly_name || upnp?.model_name">
            <span>{{ t('lan.rModel') }}</span>
            <b>{{ [upnp?.manufacturer, upnp?.model_name, upnp?.model_number].filter(Boolean).join(' ') }}</b>
          </div>
          <div class="kv" v-if="adminCandidates.length">
            <span>{{ t('lan.rAdmin') }}</span>
            <div class="admin-links">
              <el-button v-for="u in adminCandidates" :key="u" size="small" link type="primary" @click="openAdmin(u)">
                {{ u }}
              </el-button>
            </div>
          </div>
          <p v-if="!info.gateway_ip" class="empty">{{ t('lan.rEmpty') }}</p>        </div>

        <!-- WAN 状态 -->
        <div class="glass sub-card">
          <h4>{{ t('lan.rWan') }}</h4>
          <div class="kv" v-if="upnp?.external_ip">
            <span>{{ t('lan.rExtIp') }}</span><b class="ext-ip">{{ upnp.external_ip }}</b>
          </div>
          <div class="kv" v-if="upnp?.connection_status">
            <span>{{ t('lan.rConn') }}</span>
            <el-tag size="small" :type="upnp.connection_status === 'Connected' ? 'success' : 'info'">
              {{ upnp.connection_status }}
            </el-tag>
          </div>
          <div class="kv" v-if="upnp?.uptime_seconds != null">
            <span>{{ t('lan.rUptime') }}</span><b>{{ fmtDuration(upnp.uptime_seconds) }}</b>
          </div>
          <p v-if="!upnp || (!upnp.external_ip && !upnp.connection_status)" class="empty">
            {{ t('lan.rWanEmpty') }}
          </p>
        </div>

        <!-- 接口流量（SNMP） -->
        <div class="glass sub-card">
          <h4>{{ t('lan.rIfaces') }}</h4>
          <template v-if="interfaces.length">
            <div v-for="row in interfaces" :key="row.index" class="iface-row">
              <span class="iface-name" :title="row.name">{{ row.name }}</span>
              <span class="dir">↓ {{ fmtRate(row.in_bps) }}</span>
              <span class="dir up">↑ {{ fmtRate(row.out_bps) }}</span>
              <span class="total">{{ t('lan.rTotal') }} {{ fmtBytes(row.in_octets + row.out_octets) }}</span>
            </div>
          </template>
          <p v-else class="empty">
            {{ ifaceReason ? t(`lan.rReason.${ifaceReason}`) : t('lan.rReason.snmp_unreachable') }}
          </p>
        </div>
      </div>

      <!-- 连接设备 -->
      <div class="glass clients-card">
        <div class="clients-head">
          <h4>{{ t('lan.rClients') }}</h4>
          <el-tag v-if="clientsSources.length" size="small" type="info">
            {{ t('lan.rSource') }}: {{ clientsSources.join(' + ') }}
          </el-tag>
          <span class="spacer" />
          <el-button size="small" :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
        </div>
        <el-table :data="clients" size="small" max-height="360">
          <el-table-column prop="ip" label="IP" width="140" sortable />
          <el-table-column prop="mac" label="MAC" width="160" />
          <el-table-column prop="vendor" :label="t('lan.colVendor')" min-width="120">
            <template #default="{ row }">{{ row.vendor || '—' }}</template>
          </el-table-column>
          <el-table-column prop="source" :label="t('lan.colSource')" width="150" />
        </el-table>
      </div>
    </template>
    <p v-else-if="!loading" class="empty">{{ t('lan.rEmpty') }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { lanApi } from '../../api/lan'
import type { RouterClient, RouterInfo, RouterInterface } from '../../api/lan'

const { t } = useI18n()
const loading = ref(false)
const info = ref<RouterInfo | null>(null)
const clients = ref<RouterClient[]>([])
const clientsSources = ref<string[]>([])
const interfaces = ref<RouterInterface[]>([])
const ifaceReason = ref<string | null>(null)

const upnp = computed(() => info.value?.upnp)
const adminCandidates = computed(() => info.value?.admin_candidates || [])

async function load() {
  loading.value = true
  try {
    const [router, clientsData, ifaces] = await Promise.all([
      lanApi.router(),
      lanApi.routerClients(),
      lanApi.routerInterfaces(),
    ])
    info.value = router
    clients.value = clientsData.items
    clientsSources.value = clientsData.sources
    interfaces.value = ifaces.items
    ifaceReason.value = ifaces.reason
  } finally {
    loading.value = false
  }
}

function openAdmin(url: string) {
  window.open(url, '_blank')
}

function fmtRate(bps: number) {
  if (bps > 1_000_000) return (bps / 1_000_000).toFixed(1) + ' Mbps'
  if (bps > 1_000) return (bps / 1_000).toFixed(1) + ' Kbps'
  return bps + ' bps'
}

function fmtBytes(n: number) {
  if (n > 1 << 30) return (n / (1 << 30)).toFixed(1) + ' GB'
  if (n > 1 << 20) return (n / (1 << 20)).toFixed(1) + ' MB'
  if (n > 1 << 10) return (n / (1 << 10)).toFixed(1) + ' KB'
  return n + ' B'
}

function fmtDuration(seconds: number) {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return d > 0 ? `${d}d ${h}h ${m}m` : h > 0 ? `${h}h ${m}m` : `${m}m`
}

onMounted(load)
</script>

<style scoped>
/* 同 PortsView：glass 提供底/描边/圆角/阴影，子卡只补内边距与小圆角（lookup-card 范式） */
.router-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.card-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.sub-card {
  padding: 12px 14px;
  border-radius: 12px;
}
.sub-card h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--p-text);
}
.kv {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 13px;
}
.kv > span {
  color: var(--p-muted);
  min-width: 64px;
}
.ext-ip {
  font-size: 15px;
  color: var(--el-color-primary);
}
.admin-links {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.iface-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  padding: 3px 0;
}
.iface-name {
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.dir {
  color: var(--el-color-primary);
  min-width: 90px;
}
.dir.up {
  color: var(--el-color-success);
}
.total {
  color: var(--p-muted);
  font-size: 12px;
}
.clients-card {
  padding: 12px 14px;
  border-radius: 12px;
}
.clients-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.clients-head h4 {
  margin: 0;
  font-size: 13px;
  color: var(--p-text);
}
.spacer {
  flex: 1;
}
.empty {
  color: var(--p-muted);
  font-size: 13px;
  padding: 8px 0;
}
</style>
