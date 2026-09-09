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
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { Setting as IconSetting } from '@element-plus/icons-vue'
import { monitorApi, type MonitorOverview } from '../api/monitor'
import { portalApi, type PortalApp } from '../api/portal'
import { probeApi } from '../api/probe'
import { useProbeStore } from '../stores/probe'
import { useAuthStore } from '../stores/auth'
import MonitorChart from '../components/MonitorChart.vue'
import ProcessTop from '../components/ProcessTop.vue'
import DockerStatsCard from '../components/DockerStatsCard.vue'
import AvailabilityCard from '../components/AvailabilityCard.vue'
import CertCard from '../components/CertCard.vue'
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
const probeStore = useProbeStore()

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
const apps = ref<Pick<PortalApp, 'id' | 'name'>[]>([])

/** 应用状态行（M17-9：监控页一屏含应用状态；M07-2） */
const appStatusRows = computed(() =>
  apps.value.map((a) => ({
    id: a.id,
    name: a.name,
    ...(probeStore.statusMap[String(a.id)] ?? { state: 'unknown', latency_ms: null, message: '' }),
  })),
)

async function checkNow(id: number) {
  const result = await probeApi.check(id)
  ElMessage.success(
    result.state === 'up'
      ? `${t('home.statusUp')} · ${result.latency_ms ?? '-'}ms`
      : result.state === 'down'
        ? t('home.statusDown')
        : t('monitor.statusUnknown'),
  )
  void probeStore.load()
}

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
  document.addEventListener('fullscreenchange', onFullscreenChange)
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
  exitWall()
  document.removeEventListener('fullscreenchange', onFullscreenChange)
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

// 动态纵轴上限（067 用户反馈）：速率(KB/s)与温度量纲随数据变化，
// ECharts 默认取整会把 40~99 区间的数据都圆到 100 上限，曲线被压扁失真。
const dynamicMax = (pad: number, step: number, floor: number) => (v: { max?: number }) => {
  const m = Number.isFinite(v?.max) ? (v.max as number) : 0
  return Math.max(floor, Math.ceil((m * pad) / step) * step)
}
// 速率轴：存储单位 KB/s，上限留 15% 余量、8KB/s 步进取整；刻度直接格式化为可读速率（与 tooltip 一致）
const rateYAxis = {
  type: 'value' as const,
  min: 0,
  max: dynamicMax(1.15, 8, 8),
  name: '',
  axisLabel: { ...axisLabel, formatter: (v: number) => formatRate(v * 1024) },
  splitLine,
  axisLine: { show: false },
}
// 温度轴：上限留 10% 余量、5°C 步进取整（随数据抬高，不钉 100）
const tempAxisMax = dynamicMax(1.1, 5, 20)

const cpuOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip(pct),
  legend: { top: 4, type: 'scroll', textStyle: axisLabel },
  grid,
  xAxis: { type: 'category', data: [...rt.cpu.ts], axisLabel, splitLine },
  yAxis: { type: 'value', max: 100, axisLabel, splitLine, axisLine: { show: false } },
  series: [
    { name: t('monitor.cpuTotal'), type: 'line', data: [...rt.cpu.total], smooth: true, showSymbol: false, lineWidth: 2, sampling: 'lttb' },
    ...rt.cpu.cores.map((data, i) => ({
      name: `CPU${i + 1}`,
      type: 'line',
      data: [...data],
      smooth: true,
      showSymbol: false,
      lineWidth: 1,
      opacity: 0.55,
      sampling: 'lttb',
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
    { name: t('monitor.memPercent'), type: 'line', data: [...rt.mem.pct], smooth: true, showSymbol: false, sampling: 'lttb', areaStyle: { opacity: 0.15 } },
  ],
}))

const netOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip((v) => formatRate(v * 1024)), // 窗口数据以 KB/s 存储
  legend: { top: 4, textStyle: axisLabel },
  grid,
  xAxis: { type: 'category', data: [...rt.net.ts], axisLabel, splitLine },
  yAxis: { ...rateYAxis },
  series: [
    { name: t('monitor.down'), type: 'line', data: [...rt.net.rx], smooth: true, showSymbol: false, sampling: 'lttb', areaStyle: { opacity: 0.12 } },
    { name: t('monitor.up'), type: 'line', data: [...rt.net.tx], smooth: true, showSymbol: false, sampling: 'lttb', areaStyle: { opacity: 0.12 } },
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
    sampling: 'lttb',
    areaStyle: { opacity: 0.12 },
  })),
}))

const ioOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: axisTooltip((v) => formatRate(v * 1024)), // KB/s 存储
  legend: { top: 4, textStyle: axisLabel },
  grid,
  xAxis: { type: 'category', data: [...rt.io.ts], axisLabel, splitLine },
  yAxis: { ...rateYAxis },
  series: [
    { name: t('monitor.read'), type: 'line', data: [...rt.io.read], smooth: true, showSymbol: false, sampling: 'lttb', areaStyle: { opacity: 0.12 } },
    { name: t('monitor.write'), type: 'line', data: [...rt.io.write], smooth: true, showSymbol: false, sampling: 'lttb', areaStyle: { opacity: 0.12 } },
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
    sampling: 'lttb', // 1440 点级历史曲线降采样绘制
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
    const unit = metric.value === 'temp' ? '°C' : metric.value === 'gpu' || metric.value === 'disk' ? '%' : 'KB/s'
    const y = {
      type: 'value',
      // 磁盘/GPU 是百分比钉 0-100；温度量纲随数据动态抬升，不钉 100
      ...(metric.value === 'disk' || metric.value === 'gpu'
        ? { max: 100 }
        : metric.value === 'temp'
          ? { max: tempAxisMax }
          : {}),
      axisLabel: { ...axisLabel, formatter: metric.value === 'temp' ? '{value}' : '{value}%' },
      splitLine,
      axisLine: { show: false },
      name: unit,
      nameTextStyle: axisLabel,
    }
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
    const toKb = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.round((v / 1024) * 10) / 10)
    return {
      backgroundColor: 'transparent',
      tooltip: axisTooltip((v) => formatRate(v * 1024)),
      legend: legendScroll,
      grid,
      xAxis: { type: 'category', data: labels, axisLabel, splitLine },
      yAxis: { ...rateYAxis },
      series: [
        mk((h.points ?? []).map((p) => toKb(p.read)), t('monitor.read')),
        mk((h.points ?? []).map((p) => toKb(p.write)), t('monitor.write')),
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
    const toKb = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.round((v / 1024) * 10) / 10)
    series = [
      mk((h.points ?? []).map((p) => toKb(p.rx)), t('monitor.down')),
      mk((h.points ?? []).map((p) => toKb(p.tx)), t('monitor.up')),
    ]
  }
  return {
    backgroundColor: 'transparent',
    tooltip: axisTooltip(metric.value === 'net' ? (v) => formatRate(v) : pct),
    legend: legendScroll,
    grid,
    xAxis: { type: 'category', data: labels, axisLabel, splitLine },
    yAxis:
      metric.value === 'net'
        ? { ...rateYAxis }
        : {
            type: 'value',
            max: 100,
            name: '%',
            axisLabel: { ...axisLabel, formatter: '{value}%' },
            splitLine,
            axisLine: { show: false },
            nameTextStyle: axisLabel,
          },
    series,
  }
})

onMounted(async () => {
  loadHistory()
  try {
    apps.value = (await portalApi.listApps()).map((a) => ({ id: a.id, name: a.name }))
  } catch {
    apps.value = []
  }
})

// ---------- P21.1 数据与报表 / P21.3 多机纳管 ----------
import { monitorEnterpriseApi, type DayReport } from '../api/monitor'

const reportDialog = ref(false)
const reportDays = ref<DayReport[]>([])
const agentDialog = ref(false)
const agentNodes = ref<Array<{ hostname: string; cpu_pct: number; mem_pct: number; disk_pct: number; online: boolean }>>([])

// ---------- 大屏模式（P21.2）：全屏暗色数据墙 + HUD 时钟 ----------
const monitorRoot = ref<HTMLElement>()
const wallMode = ref(false)
const wallClock = ref('')
const wallDate = ref('')
let wallTimer: number | undefined

function tickWallClock() {
  const d = new Date()
  wallClock.value = d.toLocaleTimeString('zh-CN', { hour12: false })
  wallDate.value = d.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  })
}

function exitWall() {
  wallMode.value = false
  window.clearInterval(wallTimer)
  wallTimer = undefined
  if (document.fullscreenElement) void document.exitFullscreen()
}

function toggleWall() {
  if (wallMode.value) {
    exitWall()
    return
  }
  wallMode.value = true
  tickWallClock()
  wallTimer = window.setInterval(tickWallClock, 1000)
  const el = monitorRoot.value
  // 全屏尽力而为：被浏览器拒绝（非用户手势等）也保持暗色大墙
  if (el?.requestFullscreen) void el.requestFullscreen().catch(() => {})
}

// Esc 退出全屏时同步退出大屏模式（否则只剩一个没有出口的暗色页）
function onFullscreenChange() {
  if (!document.fullscreenElement && wallMode.value) exitWall()
}

// ---- 大屏单屏适配（086）：页面 overflow hidden 不出滚动条，各块压缩限行 ----
// 图表高度：常规模式定值，大屏交给 flex 容器自适应（MonitorChart 有 ResizeObserver）
const chartH = computed(() => (wallMode.value ? '100%' : '230px'))
const histH = computed(() => (wallMode.value ? '100%' : '300px'))
// 列表类数据大屏截断限行，保证整页一屏放下
const diskRows = computed(() => (wallMode.value ? disks.value.slice(0, 3) : disks.value))
const tempRows = computed(() => (wallMode.value ? temps.value.slice(0, 3) : temps.value))
const statusRows = computed(() =>
  wallMode.value ? appStatusRows.value.slice(0, 6) : appStatusRows.value,
)

async function exportCsv() {
  try {
    const r = await monitorEnterpriseApi.exportCsv('cpu', '7d')
    const blob = new Blob(['\ufeff' + r.csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = r.filename
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function openReport() {
  reportDialog.value = true
  try {
    const r = await monitorEnterpriseApi.report(7)
    reportDays.value = r.days
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function openAgents() {
  agentDialog.value = true
  try {
    agentNodes.value = await monitorEnterpriseApi.agents()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function registerAgent() {
  try {
    const hostname = prompt(t('monitor.agentHostnamePrompt'))
    if (!hostname) return
    await monitorEnterpriseApi.registerAgent(hostname)
    ElMessage.success(t('monitor.agentRegistered'))
    await openAgents()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}
</script>

<template>
  <div ref="monitorRoot" class="monitor" :class="{ 'wall-mode': wallMode }">
    <!-- 大屏模式 HUD：主机名/日期 + 实时时钟 + 退出（084 重设计） -->
    <div v-if="wallMode" class="wall-hud">
      <div class="wall-left">
        <span class="wall-name">{{ sysInfo?.hostname || 'Portal' }}</span>
        <span class="wall-date">{{ wallDate }}</span>
      </div>
      <div class="wall-right">
        <span class="wall-clock">{{ wallClock }}</span>
        <button type="button" class="wall-exit" @click="exitWall">{{ t('monitor.wallExit') }}</button>
      </div>
    </div>

    <header class="page-head">
      <h2>{{ t('monitor.title') }}</h2>
      <div class="mon-tools">
        <el-button size="small" @click="exportCsv">{{ t('monitor.exportCsv') }}</el-button>
        <el-button size="small" @click="openReport">{{ t('monitor.report') }}</el-button>
        <el-button v-if="auth.isAdmin" size="small" @click="agentDialog = true">{{ t('monitor.agents') }}</el-button>
        <el-button size="small" @click="toggleWall">{{ t('monitor.wallMode') }}</el-button>
      </div>
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
        <div class="chart-box"><MonitorChart :option="cpuOption" :height="chartH" /></div>
      </section>
      <section class="glass chart-card">
        <h3>
          {{ t('monitor.memTitle') }}
          <b v-if="memBlock" class="now">{{ memBlock.percent.toFixed(1) }}%</b>
          <small v-if="memBlock" class="sub">{{ formatBytes(memBlock.used) }} / {{ formatBytes(memBlock.total) }}</small>
        </h3>
        <div class="chart-box"><MonitorChart :option="memOption" :height="chartH" /></div>
      </section>
      <section class="glass chart-card">
        <h3>
          {{ t('monitor.netTitle') }}
          <small v-if="netBlock" class="sub">
            ↓ {{ formatRate(netBlock.reduce((s, n) => s + n.rx_rate, 0)) }} · ↑
            {{ formatRate(netBlock.reduce((s, n) => s + n.tx_rate, 0)) }}
          </small>
        </h3>
        <div class="chart-box"><MonitorChart :option="netOption" :height="chartH" /></div>
      </section>

      <!-- 磁盘分区（M17-4） -->
      <section class="glass chart-card">
        <h3>{{ t('monitor.diskTitle') }}</h3>
        <div class="disk-list">
          <div v-for="d in diskRows" :key="d.mount" class="disk-row">
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
        <div class="chart-box"><MonitorChart :option="ioOption" :height="chartH" /></div>
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
        <div class="chart-box"><MonitorChart :option="gpuOption" :height="chartH" /></div>
      </section>

      <!-- 温度（M17-11；无传感器时显示提示，NAS/Linux 有 hwmon 自动出数据） -->
      <section class="glass chart-card">
        <h3>{{ t('monitor.tempTitle') }}</h3>
        <p v-if="!hasTemps" class="empty">{{ t('monitor.noTempSensor') }}</p>
        <div v-else class="disk-list">
          <div v-for="s in tempRows" :key="s.name" class="disk-row">
            <div class="disk-head">
              <span class="mount">{{ s.name }}</span>
              <span class="usage" v-if="s.high !== null">{{ t('monitor.tempHigh', { temp: s.high }) }}</span>
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

    <!-- 应用状态 + 进程榜：大屏下两列并排（086），常规模式 display:contents 不影响原布局 -->
    <div class="mid-grid">
      <section class="glass history fade-up">
        <div class="history-head">
          <h3>{{ t('monitor.statusList') }}</h3>
        </div>
        <div class="app-status-list">
          <div v-for="row in statusRows" :key="row.id" class="app-status-row">
            <span class="as-dot" :class="row.state" />
            <span class="as-name">{{ row.name }}</span>
            <span class="as-state" :class="row.state">
              {{ row.state === 'up' ? t('monitor.statusUp') : row.state === 'down' ? t('monitor.statusDown') : t('monitor.statusUnknown') }}
              <small v-if="row.state === 'up' && row.latency_ms !== null"> · {{ row.latency_ms }}ms</small>
            </span>
            <el-button link size="small" @click="checkNow(row.id)">{{ t('home.probeCheckNow') }}</el-button>
          </div>
          <p v-if="!appStatusRows.length" class="empty">{{ t('monitor.noData') }}</p>
        </div>
      </section>

      <!-- P10.1 进程 Top 榜（M17-12，管理员） -->
      <ProcessTop v-if="auth.isAdmin" :compact="wallMode" class="fade-up" />
    </div>
    <!-- P10.2 Docker 资源占用（M17-13，无 socket 自动隐藏；大屏隐藏保证单屏） -->
    <DockerStatsCard v-if="!wallMode" class="fade-up" />
    <!-- P10.4 可用性分析（M07-3/4） -->
    <AvailabilityCard v-if="!wallMode" class="fade-up" />
    <!-- P10.5 域名证书（M07-6，未配置域名时自动隐藏） -->
    <CertCard v-if="!wallMode" class="fade-up" />

    <!-- 历史曲线（M17-6） -->
    <section class="glass history history-main fade-up" v-loading="historyLoading">
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
      <div class="chart-box"><MonitorChart :option="historyOption" :height="histH" /></div>
    </section>
  </div>

    <!-- 性能报表（P21.1/M17-20） -->
    <el-dialog append-to-body v-model="reportDialog" :title="t('monitor.reportTitle')" width="620px">
      <el-table :data="reportDays" size="small">
        <el-table-column prop="date" :label="t('ports.colTime')" width="120" />
        <el-table-column :label="'CPU %'">
          <template #default="{ row }">
            min {{ row.cpu.min ?? '-' }} / avg {{ row.cpu.avg ?? '-' }} / max {{ row.cpu.max ?? '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="'MEM %'">
          <template #default="{ row }">
            min {{ row.mem.min ?? '-' }} / avg {{ row.mem.avg ?? '-' }} / max {{ row.mem.max ?? '-' }}
          </template>
        </el-table-column>
        <template #empty>{{ t('common.noData') }}</template>
      </el-table>
    </el-dialog>

    <!-- 多机纳管（P21.3/M17-18） -->
    <el-dialog append-to-body v-model="agentDialog" :title="t('monitor.agentsTitle')" width="640px">
      <div class="agent-ops">
        <el-button size="small" type="primary" class="btn-gradient" @click="registerAgent">{{ t('monitor.agentRegister') }}</el-button>
        <el-button size="small" @click="openAgents">{{ t('notify.cert.refresh') }}</el-button>
      </div>
      <el-table :data="agentNodes" size="small">
        <el-table-column prop="hostname" :label="t('monitor.hostname')" min-width="140" />
        <el-table-column label="CPU %" width="90">
          <template #default="{ row }">{{ row.cpu_pct }}</template>
        </el-table-column>
        <el-table-column label="MEM %" width="90">
          <template #default="{ row }">{{ row.mem_pct }}</template>
        </el-table-column>
        <el-table-column label="DISK %" width="90">
          <template #default="{ row }">{{ row.disk_pct }}</template>
        </el-table-column>
        <el-table-column :label="t('tunnel.status')" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.online ? 'success' : 'info'">{{ row.online ? t('ports.reachLocal') : t('ports.state.down') }}</el-tag>
          </template>
        </el-table-column>
        <template #empty>{{ t('common.noData') }}</template>
      </el-table>
      <p class="muted" style="margin-top: 8px">{{ t('monitor.agentScriptTip') }}</p>
    </el-dialog>
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
  border-radius: var(--p-radius);
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
  border-radius: var(--p-radius);
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
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.disk-head .usage {
  color: var(--p-muted);
  white-space: nowrap;
  flex-shrink: 0;
}
.disk-head .pct {
  font-weight: 700;
  color: var(--p-primary);
  white-space: nowrap;
  flex-shrink: 0;
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
  border-radius: var(--p-radius);
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
.app-status-list {
  display: flex;
  flex-direction: column;
}
.app-status-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 2px;
  border-bottom: 1px solid color-mix(in srgb, var(--p-text) 6%, transparent);
}
.app-status-row:last-child {
  border-bottom: none;
}
.as-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--p-muted);
  opacity: 0.5;
}
.as-dot.up {
  background: #22c55e;
  opacity: 1;
}
.as-dot.down {
  background: var(--p-down);
  opacity: 1;
}
.as-name {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
}
.as-state {
  font-size: 12px;
  color: var(--p-muted);
}
.as-state.up {
  color: var(--p-up);
}
.as-state.down {
  color: var(--p-down);
}
@media (max-width: 768px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }
}

/* ===== 大屏模式（084 重设计 / 086 单屏无滚动重构）=====
   固定全屏暗色数据墙：在容器上重定义 --p 与 --el 全套变量，级联到所有
   .glass 面板与 Element Plus 组件（子组件零改动整体变暗）。
   086：页面本身不滚动（overflow hidden）——图表区弹性伸缩吃掉剩余高度
   （MonitorChart 自带 ResizeObserver 随容器缩放），列表区截断限行，
   可用性/证书/Docker 等次级卡在大屏隐藏，保证任何高度都一屏铺满。 */
.monitor.wall-mode {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
  padding: 12px 18px 14px;
  background:
    radial-gradient(1100px 520px at 82% -12%, rgba(91, 95, 241, 0.2), transparent 62%),
    radial-gradient(900px 480px at -8% 108%, rgba(6, 182, 212, 0.12), transparent 60%),
    linear-gradient(165deg, #0a1126 0%, #060b1c 58%, #071022 100%);
  color: var(--p-text);
}
/* 变量级联：语义色/卡片表面/EP 组件全套换暗色（写法对齐 html.dark） */
.monitor.wall-mode {
  --p-text: #dce4f7;
  --p-muted: #8e9abc;
  --p-card: rgba(17, 27, 56, 0.55);
  --p-card-border: rgba(126, 146, 255, 0.16);
  --p-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
  --el-bg-color: #131c38;
  --el-bg-color-overlay: #182348;
  --el-text-color-primary: #dce4f7;
  --el-text-color-regular: #b9c3e0;
  --el-border-color: rgba(126, 146, 255, 0.22);
  --el-border-color-light: rgba(126, 146, 255, 0.16);
  --el-border-color-lighter: rgba(255, 255, 255, 0.08);
  --el-fill-color-blank: transparent;
  --el-fill-color-light: rgba(255, 255, 255, 0.06);
  /* v-loading 遮罩暗色化（086 用户反馈：白底刺眼） */
  --el-mask-color: rgba(8, 14, 32, 0.72);
  --el-mask-color-extra-light: rgba(8, 14, 32, 0.45);
}
.monitor.wall-mode .glass {
  border-radius: var(--p-radius);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
.monitor.wall-mode .fade-up {
  animation: none; /* 大屏常驻显示，不要入场抖动 */
}
.monitor.wall-mode .page-head {
  display: none; /* 工具动作不属于数据墙，出口走 HUD 退出按钮/Esc */
}
/* 系统信息压成单行细条 */
.monitor.wall-mode .sys-card {
  flex: none;
  flex-wrap: nowrap;
  overflow: hidden;
  padding: 8px 16px;
}
.monitor.wall-mode .sys-item {
  flex: none;
  white-space: nowrap;
}
/* 图表区：3 列 × N 行等分剩余高度，卡片内图表随容器伸缩 */
.monitor.wall-mode .chart-grid {
  flex: 1 1 0;
  min-height: 220px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-auto-rows: 1fr;
  gap: 10px;
}
.monitor.wall-mode .chart-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: 10px 14px;
}
.monitor.wall-mode .chart-card h3 {
  flex: none;
  margin-bottom: 2px;
}
.monitor.wall-mode .chart-box {
  flex: 1;
  min-height: 0;
}
/* 应用状态 + 进程榜两列（display:contents 常规模式不改变原布局） */
.mid-grid {
  display: contents;
}
.monitor.wall-mode .mid-grid {
  flex: none;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 10px;
}
.monitor.wall-mode .app-status-row {
  padding: 4px 2px;
}
.monitor.wall-mode .disk-list {
  gap: 8px;
  padding-top: 2px;
}
/* 历史曲线定高压底 */
.monitor.wall-mode .history-main .chart-box {
  flex: none;
  height: 150px;
}
/* 大屏内滚动条细而暗（表格内部滚动用） */
.monitor.wall-mode ::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.monitor.wall-mode ::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.16);
}
/* 暗底上提亮主数值（--p-primary 原色在深蓝底上发闷） */
.monitor.wall-mode .now,
.monitor.wall-mode .disk-head .pct {
  color: #a3a7ff;
}
.monitor.wall-mode .chart-card :deep(.el-progress-bar__outer) {
  background-color: rgba(255, 255, 255, 0.08);
}

/* HUD：左主机名+日期，右时钟+退出 */
.wall-hud {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 2px;
}
.wall-left {
  display: flex;
  align-items: baseline;
  gap: 14px;
  min-width: 0;
}
.wall-name {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 1px;
  background: linear-gradient(120deg, #9ba0ff, #37e0ff 90%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  white-space: nowrap;
}
.wall-date {
  font-size: 13px;
  color: var(--p-muted);
  white-space: nowrap;
}
.wall-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}
.wall-clock {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 2px;
  font-variant-numeric: tabular-nums;
  color: var(--p-text);
}
.wall-exit {
  border: 1px solid rgba(126, 146, 255, 0.3);
  background: rgba(21, 30, 62, 0.6);
  color: #b9c3e0;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 12.5px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.wall-exit:hover {
  color: #fff;
  border-color: var(--p-primary);
}
</style>
