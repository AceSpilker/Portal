<script setup lang="ts">
/**
 * 监控页（M17-9；dev-plan P5.5）。
 *
 * 一屏：系统信息 + CPU/内存/网络 实时曲线（WS /ws/monitor 每 2 秒推送，
 * 失败自动降级 5s 轮询）+ 磁盘分区列表 + 历史曲线（24h/7d/30d）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { monitorApi, type MonitorOverview, type MonitorHistory } from '../api/monitor'
import { useAuthStore } from '../stores/auth'
import MonitorChart from '../components/MonitorChart.vue'
import { formatBytes, formatRate, formatUptime, HISTORY_RANGES, type HistoryMetric, type HistoryRange } from '../utils/monitor'

const { t, locale } = useI18n()
const auth = useAuthStore()

// ---- 实时数据（WS 推送 / 轮询降级共用）----
const overview = ref<MonitorOverview | null>(null)
const wsLost = ref(false)
let ws: WebSocket | null = null
let pollTimer: number | undefined
let reconnectDelay = 2000
let closed = false

/** 实时窗口（最近 5 分钟的 2s 点），驱动三张曲线图。 */
const rt = reactive<{ ts: string[]; cpu: number[]; mem: number[]; rx: number[]; tx: number[] }>({
  ts: [],
  cpu: [],
  mem: [],
  rx: [],
  tx: [],
})
const coreWindow = reactive<number[][]>([]) // 每核一条序列
const WINDOW_MAX = 150 // 5 分钟 @2s

function pushWindow(o: MonitorOverview) {
  const label = new Date(o.ts).toLocaleTimeString('zh-CN', { hour12: false })
  rt.ts.push(label)
  rt.cpu.push(Number(o.cpu.percent.toFixed(1)))
  rt.mem.push(Number(o.mem.percent.toFixed(1)))
  rt.rx.push(Number((o.nets.reduce((s, n) => s + n.rx_rate, 0) / 1024).toFixed(1))) // KB/s
  rt.tx.push(Number((o.nets.reduce((s, n) => s + n.tx_rate, 0) / 1024).toFixed(1)))
  o.cpu.per_core.forEach((v, i) => {
    if (coreWindow[i]) coreWindow[i].push(Number(v.toFixed(1)))
    else coreWindow[i] = [Number(v.toFixed(1))]
  })
  if (coreWindow.length > o.cpu.per_core.length) coreWindow.length = o.cpu.per_core.length
  for (const key of ['ts', 'cpu', 'mem', 'rx', 'tx'] as const) {
    if (rt[key].length > WINDOW_MAX) rt[key].shift()
  }
  for (const series of coreWindow) {
    if (series.length > WINDOW_MAX) series.shift()
  }
}

function applyOverview(o: MonitorOverview) {
  overview.value = o
  pushWindow(o)
}

function connectWs() {
  ws = new WebSocket(buildWsUrl())
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data) as { type: string; data: MonitorOverview }
    if (msg.type === 'monitor') {
      wsLost.value = false
      reconnectDelay = 2000
      applyOverview(msg.data)
    }
  }
  ws.onclose = () => {
    ws = null
    if (closed) return
    startPolling()
    // 指数退避重连，成功后停轮询
    setTimeout(() => {
      if (!closed && !ws) connectWs()
    }, reconnectDelay)
    reconnectDelay = Math.min(reconnectDelay * 2, 30_000)
  }
}

function startPolling() {
  if (pollTimer) return
  wsLost.value = true
  pollTimer = window.setInterval(async () => {
    try {
      applyOverview(await monitorApi.system())
    } catch {
      /* 轮询失败静默，下一轮重试 */
    }
  }, 5000)
}

function stopPolling() {
  window.clearTimeout(pollTimer)
  pollTimer = undefined
}

function buildWsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/monitor?token=${encodeURIComponent(auth.token)}`
}

onMounted(async () => {
  connectWs()
  try {
    applyOverview(await monitorApi.system()) // 首屏先出数据，不等 WS 首推
  } catch {
    /* 无权限/网络异常由路由守卫与 WS 降级兜底 */
  }
})
onBeforeUnmount(() => {
  closed = true
  ws?.close()
  stopPolling()
})

// ---- 图表公共外观 ----
const axisLabel = { color: '#8a93a8', fontSize: 11 }
const splitLine = { lineStyle: { color: 'rgba(138, 147, 168, 0.18)' } }
const grid = { left: 46, right: 16, top: 34, bottom: 26 }
/** 轴触发提示；fmt 给出时数值带单位显示（% / KB/s→可读速率） */
const axisTooltip = (fmt?: (v: number) => string) => ({
  trigger: 'axis' as const,
  ...(fmt ? { valueFormatter: (v: number) => fmt(Number(v)) } : {}),
})
const pct = (v: number) => `${v}%`

const cpuOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip(pct),
  legend: { top: 4, type: 'scroll', textStyle: axisLabel },
  grid,
  xAxis: { type: 'category', data: [...rt.ts], axisLabel, splitLine },
  yAxis: { type: 'value', max: 100, axisLabel, splitLine, axisLine: { show: false } },
  series: [
    { name: t('monitor.cpuTotal'), type: 'line', data: [...rt.cpu], smooth: true, showSymbol: false, lineWidth: 2 },
    ...coreWindow.map((data, i) => ({
      name: `CPU${i + 1}`,
      type: 'line',
      data: [...data],
      smooth: true,
      showSymbol: false,
      lineWidth: 1,
      opacity: 0.55,
    })),
  ],
}))

const memOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip(pct),
  grid,
  xAxis: { type: 'category', data: [...rt.ts], axisLabel, splitLine },
  yAxis: { type: 'value', max: 100, axisLabel, splitLine, axisLine: { show: false } },
  series: [
    { name: t('monitor.memPercent'), type: 'line', data: [...rt.mem], smooth: true, showSymbol: false, areaStyle: { opacity: 0.15 } },
  ],
}))

const netOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip((v) => formatRate(v * 1024)), // 窗口数据以 KB/s 存储
  legend: { top: 4, textStyle: axisLabel },
  grid,
  xAxis: { type: 'category', data: [...rt.ts], axisLabel, splitLine },
  yAxis: { type: 'value', axisLabel, splitLine, axisLine: { show: false }, name: 'KB/s', nameTextStyle: axisLabel },
  series: [
    { name: t('monitor.down'), type: 'line', data: [...rt.rx], smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 } },
    { name: t('monitor.up'), type: 'line', data: [...rt.tx], smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 } },
  ],
}))

// ---- 历史曲线 ----
const metric = ref<HistoryMetric>('cpu')
const range = ref<HistoryRange>('24h')
const history = ref<MonitorHistory | null>(null)
const historyLoading = ref(false)

async function loadHistory() {
  historyLoading.value = true
  try {
    history.value = await monitorApi.history(metric.value, range.value)
  } finally {
    historyLoading.value = false
  }
}
// 切换即清空旧数据：避免新指标的 series 去读旧响应的字段（如 cpu 点上读 percent）
watch([metric, range], () => {
  history.value = null
  loadHistory()
})

const historyOption = computed(() => {
  const h = history.value
  if (!h) return { backgroundColor: 'transparent' }
  // disk 响应无 points，时间轴取首个挂载点（后端保证各挂载点对齐、缺失补 null）
  const timeline = metric.value === 'disk' ? (h.mounts?.[0]?.points ?? []) : (h.points ?? [])
  const labels = timeline.map((p) =>
    new Date(p.ts).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }),
  )
  const mk = (data: (number | undefined)[], name: string, thin = false) => ({
    name,
    type: 'line',
    data,
    smooth: true,
    showSymbol: false,
    lineWidth: thin ? 1 : 2,
    opacity: thin ? 0.55 : 1,
    connectNulls: false,
  })
  const legendScroll = { top: 4, type: 'scroll', textStyle: axisLabel }
  if (metric.value === 'disk') {
    const series = (h.mounts ?? []).map((m) => ({
      name: m.mount,
      type: 'line' as const,
      data: m.points.map((p) => p.percent),
      smooth: true,
      showSymbol: false,
    }))
    return {
      backgroundColor: 'transparent',
      tooltip: axisTooltip(pct),
      legend: legendScroll,
      grid,
      xAxis: { type: 'category', data: labels, axisLabel, splitLine },
      yAxis: { type: 'value', max: 100, axisLabel, splitLine, axisLine: { show: false } },
      series,
    }
  }
  let series
  if (metric.value === 'cpu') {
    const pts = h.points ?? []
    // 总使用率（粗线）+ 每核（细线，M17-2）
    const coreCount = pts[0]?.cores?.length ?? 0
    series = [
      mk(pts.map((p) => p.cpu), t('monitor.cpuTotal')),
      ...Array.from({ length: coreCount }, (_, i) =>
        mk(
          pts.map((p) => p.cores?.[i]),
          `CPU${i + 1}`,
          true,
        ),
      ),
    ]
  } else if (metric.value === 'mem') {
    series = [mk((h.points ?? []).map((p) => p.percent), t('monitor.memPercent'))]
  } else {
    series = [
      mk((h.points ?? []).map((p) => p.rx), t('monitor.down')),
      mk((h.points ?? []).map((p) => p.tx), t('monitor.up')),
    ]
  }
  return {
    backgroundColor: 'transparent',
    tooltip: axisTooltip(
      metric.value === 'net' ? (v) => formatRate(v) : pct,
    ),
    legend: legendScroll,
    grid,
    xAxis: { type: 'category', data: labels, axisLabel, splitLine },
    yAxis: {
      type: 'value',
      axisLabel,
      splitLine,
      axisLine: { show: false },
      ...(metric.value === 'cpu' || metric.value === 'mem' ? { max: 100 } : {}),
    },
    series,
  }
})

onMounted(loadHistory)
</script>

<template>
  <div class="monitor">
    <header class="page-head">
      <h2>{{ t('monitor.title') }}</h2>
    </header>

    <!-- 系统信息（M17-1） -->
    <section v-if="overview" class="glass sys-card fade-up">
      <div class="sys-item"><span class="k">{{ t('monitor.hostname') }}</span><span class="v">{{ overview.system.hostname }}</span></div>
      <div class="sys-item"><span class="k">{{ t('monitor.os') }}</span><span class="v">{{ overview.system.os }}</span></div>
      <div class="sys-item"><span class="k">{{ t('monitor.kernel') }}</span><span class="v">{{ overview.system.kernel }}</span></div>
      <div class="sys-item"><span class="k">{{ t('monitor.arch') }}</span><span class="v">{{ overview.system.arch }}</span></div>
      <div class="sys-item"><span class="k">{{ t('monitor.uptime') }}</span><span class="v">{{ formatUptime(overview.system.uptime, locale) }}</span></div>
      <div class="sys-item">
        <span class="k">{{ t('monitor.load') }}</span>
        <span class="v">{{ overview.cpu.load.map((l) => l ?? '-').join(' / ') }}</span>
      </div>
      <div class="sys-item"><span class="k">{{ t('monitor.cores') }}</span><span class="v">{{ overview.cpu.cores }}</span></div>
    </section>

    <el-alert v-if="wsLost" :title="t('monitor.wsLost')" type="warning" :closable="false" class="fade-up" />

    <!-- 实时曲线（M17-8） -->
    <div class="chart-grid fade-up">
      <section class="glass chart-card">
        <h3>
          {{ t('monitor.cpuTitle') }}
          <b v-if="overview" class="now">{{ overview.cpu.percent.toFixed(1) }}%</b>
        </h3>
        <MonitorChart :option="cpuOption" height="230px" />
      </section>
      <section class="glass chart-card">
        <h3>
          {{ t('monitor.memTitle') }}
          <b v-if="overview" class="now">{{ overview.mem.percent.toFixed(1) }}%</b>
          <small v-if="overview" class="sub">{{ formatBytes(overview.mem.used) }} / {{ formatBytes(overview.mem.total) }}</small>
        </h3>
        <MonitorChart :option="memOption" height="230px" />
      </section>
      <section class="glass chart-card">
        <h3>
          {{ t('monitor.netTitle') }}
          <small v-if="overview" class="sub">
            ↓ {{ formatRate(overview.nets.reduce((s, n) => s + n.rx_rate, 0)) }} · ↑
            {{ formatRate(overview.nets.reduce((s, n) => s + n.tx_rate, 0)) }}
          </small>
        </h3>
        <MonitorChart :option="netOption" height="230px" />
      </section>

      <!-- 磁盘分区（M17-4） -->
      <section class="glass chart-card">
        <h3>{{ t('monitor.diskTitle') }}</h3>
        <div v-if="overview" class="disk-list">
          <div v-for="d in overview.disks" :key="d.mount" class="disk-row">
            <div class="disk-head">
              <span class="mount">{{ d.mount }}</span>
              <span class="usage">{{ formatBytes(d.used) }} / {{ formatBytes(d.total) }}</span>
              <span class="pct">{{ d.percent.toFixed(1) }}%</span>
            </div>
            <el-progress :percentage="d.percent" :show-text="false" :stroke-width="8" />
            <small v-if="d.inode_p !== null" class="inode">inode {{ d.inode_p.toFixed(1) }}%</small>
          </div>
          <p v-if="!overview.disks.length" class="empty">{{ t('monitor.noData') }}</p>
        </div>
      </section>
    </div>

    <!-- 历史曲线（M17-6） -->
    <section class="glass history fade-up" v-loading="historyLoading">
      <div class="history-head">
        <h3>{{ t('monitor.history') }}</h3>
        <div class="history-ctrl">
          <el-radio-group v-model="metric" size="small">
            <el-radio-button value="cpu">{{ t('monitor.cpuTitle') }}</el-radio-button>
            <el-radio-button value="mem">{{ t('monitor.memTitle') }}</el-radio-button>
            <el-radio-button value="net">{{ t('monitor.netTitle') }}</el-radio-button>
            <el-radio-button value="disk">{{ t('monitor.diskTitle') }}</el-radio-button>
          </el-radio-group>
          <el-radio-group v-model="range" size="small">
            <el-radio-button v-for="r in HISTORY_RANGES" :key="r" :value="r">
              {{ t(`monitor.range.${r}`) }}
            </el-radio-button>
          </el-radio-group>
        </div>
      </div>
      <MonitorChart :option="historyOption" height="300px" />
    </section>
  </div>
</template>

<style scoped>
.monitor {
  flex: 1;
  min-height: 0;
  overflow-y: auto; /* 页面内容超出视口时垂直滚动（与首页/工具页约定一致） */
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-bottom: 6px;
}
.page-head h2 {
  margin: 0;
}
.sys-card {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 28px;
  padding: 14px 20px;
  border-radius: 14px;
}
.sys-item .k {
  color: var(--p-muted);
  font-size: 12px;
  margin-right: 8px;
}
.sys-item .v {
  font-weight: 600;
  font-size: 13px;
}
.chart-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 14px;
}
.chart-card {
  padding: 14px 16px;
  border-radius: 14px;
}
.chart-card h3 {
  margin: 0 0 6px;
  font-size: 14px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.chart-card .now {
  color: var(--p-primary);
  font-size: 18px;
}
.chart-card .sub {
  color: var(--p-muted);
  font-size: 12px;
  font-weight: 400;
}
.disk-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 6px;
}
.disk-head {
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
  margin-bottom: 4px;
}
.disk-head .mount {
  font-weight: 600;
}
.disk-head .usage {
  color: var(--p-muted);
}
.disk-head .pct {
  font-weight: 700;
  color: var(--p-primary);
}
.inode {
  color: var(--p-muted);
  font-size: 11px;
}
.empty {
  color: var(--p-muted);
  font-size: 12.5px;
}
.history {
  padding: 14px 16px;
  border-radius: 14px;
}
.history-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.history-head h3 {
  margin: 0;
  font-size: 14px;
}
.history-ctrl {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
@media (max-width: 768px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
