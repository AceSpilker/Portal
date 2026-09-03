<script setup lang="ts">
/**
 * 监控页（M17-9/11；dev-plan P5.5 + 温度与分块推送增强）。
 *
 * 一屏：系统信息 + CPU（总量+每核）/内存/网络 实时曲线 + 磁盘/温度列表
 * + 历史曲线（cpu/mem/net/disk/temp × 24h/7d/30d）。
 * 数据由 WS /ws/monitor 推送（断连降级 5s 轮询）；每个数据块可单独设置
 * 刷新间隔（localStorage 持久化），帧到达时按块节流应用。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Setting as IconSetting } from '@element-plus/icons-vue'
import { monitorApi, type MonitorOverview } from '../api/monitor'
import { useAuthStore } from '../stores/auth'
import MonitorChart from '../components/MonitorChart.vue'
import {
  formatBytes,
  formatRate,
  formatUptime,
  HISTORY_RANGES,
  type HistoryMetric,
  type HistoryRange,
} from '../utils/monitor'

const { t, locale } = useI18n()
const auth = useAuthStore()

// ---- 分块推送间隔（秒，localStorage 持久化）----
const BLOCKS = ['cpu', 'mem', 'net', 'disk', 'io', 'gpu', 'temp'] as const
type Block = (typeof BLOCKS)[number]
const INTERVALS_KEY = 'portal.monitor.intervals'
const DEFAULT_INTERVALS: Record<Block, number> = {
  cpu: 2,
  mem: 5,
  net: 2,
  disk: 30,
  io: 5,
  gpu: 5,
  temp: 60,
}
const INTERVAL_OPTIONS = [1, 2, 5, 10, 30, 60]

function loadIntervals(): Record<Block, number> {
  try {
    const raw = JSON.parse(localStorage.getItem(INTERVALS_KEY) ?? '{}') as Partial<Record<Block, number>>
    return { ...DEFAULT_INTERVALS, ...raw }
  } catch {
    return { ...DEFAULT_INTERVALS }
  }
}
const blockIntervals = reactive<Record<Block, number>>(loadIntervals())
const settingsVisible = ref(false)
function saveIntervals() {
  localStorage.setItem(INTERVALS_KEY, JSON.stringify({ ...blockIntervals }))
}
function resetIntervals() {
  Object.assign(blockIntervals, DEFAULT_INTERVALS)
}
watch(blockIntervals, saveIntervals, { deep: true })

// ---- 分块数据（WS 帧 × 块间隔节流后写入）----
const sysInfo = ref<MonitorOverview['system'] | null>(null)
const cpuBlock = ref<MonitorOverview['cpu'] | null>(null)
const memBlock = ref<MonitorOverview['mem'] | null>(null)
const netBlock = ref<MonitorOverview['nets'] | null>(null)
const disks = ref<MonitorOverview['disks']>([])
const ioBlock = ref<MonitorOverview['io']>(null)
const gpuBlock = ref<MonitorOverview['gpu']>([])
const temps = ref<MonitorOverview['temps']>([])
const hasTemps = computed(() => temps.value.length > 0)
const firstGpuUtil = computed(() => {
  const u = gpuBlock.value[0]?.util
  return typeof u === 'number' ? u : null
})
const hasGpu = computed(() => gpuBlock.value.length > 0)

const rt = reactive({
  cpu: { ts: [] as string[], total: [] as number[], cores: [] as number[][] },
  mem: { ts: [] as string[], pct: [] as number[] },
  net: { ts: [] as string[], rx: [] as number[], tx: [] as number[] },
  io: { ts: [] as string[], read: [] as number[], write: [] as number[] },
  gpu: { ts: [] as string[], perGpu: [] as number[][] },
})
const WINDOW_MAX = 150 // 5 分钟 @2s

const lastApplied: Record<Block, number> = {
  cpu: 0,
  mem: 0,
  net: 0,
  disk: 0,
  io: 0,
  gpu: 0,
  temp: 0,
}

function pushWin(win: { ts: string[] }, label: string) {
  win.ts.push(label)
  if (win.ts.length > WINDOW_MAX) win.ts.shift()
}

function applyBlock(o: MonitorOverview, block: Block) {
  const label = new Date(o.ts).toLocaleTimeString('zh-CN', { hour12: false })
  if (block === 'cpu') {
    cpuBlock.value = o.cpu
    pushWin(rt.cpu, label)
    rt.cpu.total.push(Number(o.cpu.percent.toFixed(1)))
    o.cpu.per_core.forEach((v, i) => {
      const rounded = Number(v.toFixed(1))
      if (rt.cpu.cores[i]) rt.cpu.cores[i].push(rounded)
      else rt.cpu.cores[i] = [rounded]
    })
    if (rt.cpu.cores.length > o.cpu.per_core.length) rt.cpu.cores.length = o.cpu.per_core.length
    for (const s of rt.cpu.cores) if (s.length > WINDOW_MAX) s.shift()
    if (rt.cpu.total.length > WINDOW_MAX) rt.cpu.total.shift()
  } else if (block === 'mem') {
    memBlock.value = o.mem
    pushWin(rt.mem, label)
    rt.mem.pct.push(Number(o.mem.percent.toFixed(1)))
    if (rt.mem.pct.length > WINDOW_MAX) rt.mem.pct.shift()
  } else if (block === 'net') {
    netBlock.value = o.nets
    pushWin(rt.net, label)
    rt.net.rx.push(Number((o.nets.reduce((s, n) => s + n.rx_rate, 0) / 1024).toFixed(1)))
    rt.net.tx.push(Number((o.nets.reduce((s, n) => s + n.tx_rate, 0) / 1024).toFixed(1)))
    if (rt.net.rx.length > WINDOW_MAX) rt.net.rx.shift()
    if (rt.net.tx.length > WINDOW_MAX) rt.net.tx.shift()
  } else if (block === 'disk') {
    disks.value = o.disks
  } else if (block === 'io') {
    ioBlock.value = o.io
    if (o.io) {
      pushWin(rt.io, label)
      rt.io.read.push(Number((o.io.read_rate / 1024).toFixed(1)))
      rt.io.write.push(Number((o.io.write_rate / 1024).toFixed(1)))
      if (rt.io.read.length > WINDOW_MAX) rt.io.read.shift()
      if (rt.io.write.length > WINDOW_MAX) rt.io.write.shift()
    }
  } else if (block === 'gpu') {
    gpuBlock.value = o.gpu
    if (o.gpu.length) {
      pushWin(rt.gpu, label)
      o.gpu.forEach((g, i) => {
        const v = Number(g.util.toFixed(1))
        if (rt.gpu.perGpu[i]) rt.gpu.perGpu[i].push(v)
        else rt.gpu.perGpu[i] = [v]
      })
      if (rt.gpu.perGpu.length > o.gpu.length) rt.gpu.perGpu.length = o.gpu.length
      for (const s of rt.gpu.perGpu) if (s.length > WINDOW_MAX) s.shift()
    }
  } else if (block === 'temp') {
    temps.value = o.temps
  }
}

function applyOverview(o: MonitorOverview) {
  sysInfo.value = o.system // 系统信息随每帧（开销可忽略）
  const now = Date.now()
  for (const block of BLOCKS) {
    if (now - lastApplied[block] >= blockIntervals[block] * 1000) {
      lastApplied[block] = now
      applyBlock(o, block)
    }
  }
}

// ---- WS 推送 + 轮询降级 ----
const wsLost = ref(false)
let ws: WebSocket | null = null
let pollTimer: number | undefined
let reconnectDelay = 2000
let closed = false

function buildWsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/monitor?token=${encodeURIComponent(auth.token)}`
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
  xAxis: { type: 'category', data: [...rt.cpu.ts], axisLabel, splitLine },
  yAxis: { type: 'value', max: 100, axisLabel, splitLine, axisLine: { show: false } },
  series: [
    { name: t('monitor.cpuTotal'), type: 'line', data: [...rt.cpu.total], smooth: true, showSymbol: false, lineWidth: 2 },
    ...rt.cpu.cores.map((data, i) => ({
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
  xAxis: { type: 'category', data: [...rt.mem.ts], axisLabel, splitLine },
  yAxis: { type: 'value', max: 100, axisLabel, splitLine, axisLine: { show: false } },
  series: [
    { name: t('monitor.memPercent'), type: 'line', data: [...rt.mem.pct], smooth: true, showSymbol: false, areaStyle: { opacity: 0.15 } },
  ],
}))

const netOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip((v) => formatRate(v * 1024)), // 窗口数据以 KB/s 存储
  legend: { top: 4, textStyle: axisLabel },
  grid,
  xAxis: { type: 'category', data: [...rt.net.ts], axisLabel, splitLine },
  yAxis: { type: 'value', axisLabel, splitLine, axisLine: { show: false }, name: 'KB/s', nameTextStyle: axisLabel },
  series: [
    { name: t('monitor.down'), type: 'line', data: [...rt.net.rx], smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 } },
    { name: t('monitor.up'), type: 'line', data: [...rt.net.tx], smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 } },
  ],
}))

const gpuOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip(pct),
  legend: { top: 4, type: 'scroll', textStyle: axisLabel },
  grid,
  xAxis: { type: 'category', data: [...rt.gpu.ts], axisLabel, splitLine },
  yAxis: { type: 'value', max: 100, axisLabel, splitLine, axisLine: { show: false } },
  series: gpuBlock.value.map((g, i) => ({
    name: g.name || `GPU${i + 1}`,
    type: 'line',
    data: [...(rt.gpu.perGpu[i] ?? [])],
    smooth: true,
    showSymbol: false,
    lineWidth: 2,
    areaStyle: { opacity: 0.12 },
  })),
}))

const ioOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip((v) => formatRate(v * 1024)), // KB/s 存储
  legend: { top: 4, textStyle: axisLabel },
  grid,
  xAxis: { type: 'category', data: [...rt.io.ts], axisLabel, splitLine },
  yAxis: { type: 'value', axisLabel, splitLine, axisLine: { show: false }, name: 'KB/s', nameTextStyle: axisLabel },
  series: [
    { name: t('monitor.read'), type: 'line', data: [...rt.io.read], smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 } },
    { name: t('monitor.write'), type: 'line', data: [...rt.io.write], smooth: true, showSymbol: false, areaStyle: { opacity: 0.12 } },
  ],
}))

// ---- 历史曲线 ----
const metric = ref<HistoryMetric>('cpu')
const range = ref<HistoryRange>('24h')
const history = ref<Awaited<ReturnType<typeof monitorApi.history>> | null>(null)
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
// 无温度传感器时温度 tab 自动隐藏并回退 cpu（M17-11：无传感器自动隐藏）
watch(hasTemps, (has) => {
  if (!has && metric.value === 'temp') metric.value = 'cpu'
})
watch(hasGpu, (has) => {
  if (!has && metric.value === 'gpu') metric.value = 'cpu'
})

const historyOption = computed(() => {
  const h = history.value
  if (!h) return { backgroundColor: 'transparent' }
  // disk/temp 响应无 points，时间轴取首序列（后端保证各序列对齐、缺失补 null）
  const multiSeriesMeta = metric.value === 'disk' ? h.mounts : metric.value === 'temp' ? h.sensors : metric.value === 'gpu' ? h.gpus : undefined
  const timeline = multiSeriesMeta ? (multiSeriesMeta[0]?.points ?? []) : (h.points ?? [])
  const labels = timeline.map((p) =>
    new Date(p.ts).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }),
  )
  const mk = (data: (number | null | undefined)[], name: string, thin = false) => ({
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
  if (multiSeriesMeta) {
    const multi = multiSeriesMeta.map((s) => {
      const name = 'mount' in s ? s.mount : s.name
      const data = s.points.map((p) => ('percent' in p ? p.percent : 'current' in p ? p.current : p.util))
      return { name, data }
    })
    const fmt =
      metric.value === 'disk' ? pct : metric.value === 'temp' ? (v: number) => `${v} °C` : metric.value === 'gpu' ? pct : (v: number) => formatRate(v)
    const y =
      metric.value === 'disk' || metric.value === 'gpu'
        ? { type: 'value', max: 100, axisLabel, splitLine, axisLine: { show: false } }
        : metric.value === 'temp'
          ? { type: 'value', axisLabel, splitLine, axisLine: { show: false }, name: '°C', nameTextStyle: axisLabel }
          : { type: 'value', axisLabel, splitLine, axisLine: { show: false }, name: 'B/s', nameTextStyle: axisLabel }
    return {
      backgroundColor: 'transparent',
      tooltip: axisTooltip(fmt),
      legend: legendScroll,
      grid,
      xAxis: { type: 'category', data: labels, axisLabel, splitLine },
      yAxis: y,
      series: multi.map((s) => mk(s.data, s.name)),
    }
  }
  if (metric.value === 'io') {
    return {
      backgroundColor: 'transparent',
      tooltip: axisTooltip((v) => formatRate(v)),
      legend: legendScroll,
      grid,
      xAxis: { type: 'category', data: labels, axisLabel, splitLine },
      yAxis: { type: 'value', axisLabel, splitLine, axisLine: { show: false }, name: 'B/s', nameTextStyle: axisLabel },
      series: [
        mk((h.points ?? []).map((p) => p.read), t('monitor.read')),
        mk((h.points ?? []).map((p) => p.write), t('monitor.write')),
      ],
    }
  }
  let series
  if (metric.value === 'cpu') {
    const pts = h.points ?? []
    // 总使用率（粗线）+ 每核（细线，M17-2）；核数从最新样本取——
    // cpu_cores 是后加列，早期样本没有该字段（画图时留断口）
    let coreCount = 0
    for (let i = pts.length - 1; i >= 0; i--) {
      if (pts[i]?.cores?.length) {
        coreCount = pts[i].cores!.length
        break
      }
    }
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
    tooltip: axisTooltip(metric.value === 'net' ? (v) => formatRate(v) : pct),
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
      <el-popover v-model:visible="settingsVisible" trigger="click" width="260">
        <template #reference>
          <button type="button" class="push-settings" :title="t('monitor.pushSettings')">
            <el-icon :size="14"><IconSetting /></el-icon>
            <span>{{ t('monitor.pushSettings') }}</span>
          </button>
        </template>
        <div class="push-table">
          <div v-for="b in BLOCKS" :key="b" class="push-row">
            <span class="push-label">{{ t(`monitor.block.${b}`) }}</span>
            <el-select v-model="blockIntervals[b]" size="small" style="width: 110px" @change="saveIntervals">
              <el-option v-for="s in INTERVAL_OPTIONS" :key="s" :value="s" :label="`${s} ${$t('monitor.seconds')}`" />
            </el-select>
          </div>
          <p class="push-hint">{{ t('monitor.pushHint') }}</p>
          <div class="push-reset">
            <el-button size="small" @click="resetIntervals">{{ t('monitor.resetIntervals') }}</el-button>
          </div>
        </div>
      </el-popover>
    </header>

    <!-- 系统信息（M17-1） -->
    <section v-if="sysInfo" class="glass sys-card fade-up">
      <div class="sys-item"><span class="k">{{ t('monitor.hostname') }}</span><span class="v">{{ sysInfo.hostname }}</span></div>
      <div class="sys-item"><span class="k">{{ t('monitor.os') }}</span><span class="v">{{ sysInfo.os }}</span></div>
      <div class="sys-item"><span class="k">{{ t('monitor.kernel') }}</span><span class="v">{{ sysInfo.kernel }}</span></div>
      <div class="sys-item"><span class="k">{{ t('monitor.arch') }}</span><span class="v">{{ sysInfo.arch }}</span></div>
      <div class="sys-item"><span class="k">{{ t('monitor.uptime') }}</span><span class="v">{{ formatUptime(sysInfo.uptime, locale) }}</span></div>
      <div class="sys-item" v-if="cpuBlock">
        <span class="k">{{ t('monitor.load') }}</span>
        <span class="v">{{ cpuBlock.load.map((l) => l ?? '-').join(' / ') }}</span>
      </div>
      <div class="sys-item" v-if="cpuBlock"><span class="k">{{ t('monitor.cores') }}</span><span class="v">{{ cpuBlock.cores }}</span></div>
    </section>

    <el-alert v-if="wsLost" :title="t('monitor.wsLost')" type="warning" :closable="false" class="fade-up" />

    <!-- 实时曲线（M17-8） -->
    <div class="chart-grid fade-up">
      <section class="glass chart-card">
        <h3>
          {{ t('monitor.cpuTitle') }}
          <b v-if="cpuBlock" class="now">{{ cpuBlock.percent.toFixed(1) }}%</b>
        </h3>
        <MonitorChart :option="cpuOption" height="230px" />
      </section>
      <section class="glass chart-card">
        <h3>
          {{ t('monitor.memTitle') }}
          <b v-if="memBlock" class="now">{{ memBlock.percent.toFixed(1) }}%</b>
          <small v-if="memBlock" class="sub">{{ formatBytes(memBlock.used) }} / {{ formatBytes(memBlock.total) }}</small>
        </h3>
        <MonitorChart :option="memOption" height="230px" />
      </section>
      <section class="glass chart-card">
        <h3>
          {{ t('monitor.netTitle') }}
          <small v-if="netBlock" class="sub">
            ↓ {{ formatRate(netBlock.reduce((s, n) => s + n.rx_rate, 0)) }} · ↑
            {{ formatRate(netBlock.reduce((s, n) => s + n.tx_rate, 0)) }}
          </small>
        </h3>
        <MonitorChart :option="netOption" height="230px" />
      </section>

      <!-- 磁盘分区（M17-4） -->
      <section class="glass chart-card">
        <h3>{{ t('monitor.diskTitle') }}</h3>
        <div class="disk-list">
          <div v-for="d in disks" :key="d.mount" class="disk-row">
            <div class="disk-head">
              <span class="mount">{{ d.mount }}</span>
              <span class="usage">{{ formatBytes(d.used) }} / {{ formatBytes(d.total) }}</span>
              <span class="pct">{{ d.percent.toFixed(1) }}%</span>
            </div>
            <el-progress :percentage="d.percent" :show-text="false" :stroke-width="8" />
            <small v-if="d.inode_p !== null" class="inode">inode {{ d.inode_p.toFixed(1) }}%</small>
          </div>
          <p v-if="!disks.length" class="empty">{{ t('monitor.noData') }}</p>
        </div>
      </section>

      <!-- 磁盘 IO（M17-10） -->
      <section class="glass chart-card">
        <h3>
          I/O
          <small v-if="ioBlock" class="sub">
            {{ t('monitor.read') }} {{ formatRate(ioBlock.read_rate) }} · {{ t('monitor.write') }} {{ formatRate(ioBlock.write_rate) }}
          </small>
        </h3>
        <MonitorChart :option="ioOption" height="230px" />
      </section>

      <!-- GPU（尽力而为：nvidia-smi / Windows GPU Engine 计数器；无数据整卡隐藏） -->
      <section v-if="hasGpu" class="glass chart-card">
        <h3>
          GPU
          <b class="now">{{ firstGpuUtil !== null ? `${firstGpuUtil.toFixed(1)}%` : '-' }}</b>
          <small
            v-if="gpuBlock[0]?.mem_used !== null && gpuBlock[0]?.mem_total"
            class="sub"
          >
            {{ formatBytes(gpuBlock[0].mem_used) }} / {{ formatBytes(gpuBlock[0].mem_total) }}
          </small>
        </h3>
        <MonitorChart :option="gpuOption" height="230px" />
      </section>

      <!-- 温度（M17-11；无传感器时显示提示，NAS/Linux 有 hwmon 自动出数据） -->
      <section class="glass chart-card">
        <h3>{{ t('monitor.tempTitle') }}</h3>
        <p v-if="!hasTemps" class="empty">{{ t('monitor.noTempSensor') }}</p>
        <div v-else class="disk-list">
          <div v-for="s in temps" :key="s.name" class="disk-row">
            <div class="disk-head">
              <span class="mount">{{ s.name }}</span>
              <span class="usage" v-if="s.high !== null">≥ {{ s.high }}°C 注意</span>
              <span class="pct temp" :class="{ hot: s.critical !== null && s.current !== null && s.current >= s.critical }">
                {{ s.current !== null ? `${s.current.toFixed(1)}°C` : '-' }}
              </span>
            </div>
            <el-progress
              :percentage="Math.min(100, Math.round(((s.current ?? 0) / (s.critical ?? s.high ?? 100)) * 100))"
              :show-text="false"
              :stroke-width="8"
              :status="s.critical !== null && s.current !== null && s.current >= s.critical ? 'exception' : undefined"
            />
          </div>
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
            <el-radio-button value="io">I/O</el-radio-button>
            <el-radio-button v-if="hasGpu" value="gpu">GPU</el-radio-button>
            <el-radio-button v-if="hasTemps" value="temp">{{ t('monitor.tempTitle') }}</el-radio-button>
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
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-head h2 {
  margin: 0;
}
.push-settings {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--p-muted);
  border: 1px solid var(--p-card-border);
  background: var(--p-card);
  padding: 5px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.push-settings:hover {
  border-color: var(--p-primary);
  color: var(--p-primary);
}
.push-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 0;
}
.push-label {
  font-size: 12.5px;
}
.push-hint {
  margin: 8px 0 8px;
  font-size: 11.5px;
  color: var(--p-muted);
}
.push-reset {
  display: flex;
  justify-content: flex-end;
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
.disk-head .pct.temp.hot {
  color: var(--el-color-danger);
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
