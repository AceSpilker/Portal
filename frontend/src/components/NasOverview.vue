<script setup lang="ts">
/**
 * 首页 NAS 资源速览（M02-12；dev-plan P5.6）。
 *
 * CPU/内存/磁盘使用率三枚 SVG 环形图（不引 ECharts，首页零额外包体），
 * 30s 轮询刷新；仅管理员可见（监控接口权限 A），点击进入监控页。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { monitorApi, type MonitorOverview } from '../api/monitor'

const router = useRouter()
const overview = ref<MonitorOverview | null>(null)
let timer: number | undefined

async function load() {
  try {
    overview.value = await monitorApi.system()
  } catch {
    overview.value = null
  }
}

function goMonitor() {
  void router.push('/monitor')
}

onMounted(() => {
  void load()
  timer = window.setInterval(load, 30_000)
})
onBeforeUnmount(() => window.clearInterval(timer))

/** 环形图参数：周长 2πr，进度 = dasharray 前段。 */
const R = 26
const CIRC = 2 * Math.PI * R
function ring(percent: number) {
  const p = Math.max(0, Math.min(100, percent))
  return `${(p / 100) * CIRC} ${CIRC}`
}
const diskPercent = () => {
  const disks = overview.value?.disks ?? []
  if (!disks.length) return 0
  // 汇总已用/容量，比"最大分区"更贴近整体水位
  const total = disks.reduce((s, d) => s + d.total, 0)
  const used = disks.reduce((s, d) => s + d.used, 0)
  return total ? (used / total) * 100 : 0
}
</script>

<template>
  <div class="nas-overview" :title="$t('monitor.openPage')" @click="goMonitor">
    <div v-for="item in [
      { label: $t('monitor.cpuShort'), value: overview?.cpu.percent ?? 0, text: `${(overview?.cpu.percent ?? 0).toFixed(0)}%` },
      { label: $t('monitor.memShort'), value: overview?.mem.percent ?? 0, text: `${(overview?.mem.percent ?? 0).toFixed(0)}%` },
      { label: $t('monitor.diskShort'), value: diskPercent(), text: `${diskPercent().toFixed(0)}%` },
    ]" :key="item.label" class="ring">
      <svg width="64" height="64" viewBox="0 0 64 64">
        <circle class="track" cx="32" cy="32" :r="R" fill="none" stroke-width="7" />
        <circle
          class="arc" cx="32" cy="32" :r="R" fill="none" stroke-width="7" stroke-linecap="round"
          :stroke-dasharray="ring(item.value)" transform="rotate(-90 32 32)"
        />
        <text x="32" y="37" text-anchor="middle" class="num">{{ item.text }}</text>
      </svg>
      <span class="label">{{ item.label }}</span>
    </div>
  </div>
</template>

<style scoped>
.nas-overview {
  display: flex;
  gap: 14px;
  cursor: pointer;
}
.ring {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.track {
  stroke: color-mix(in srgb, var(--p-text) 10%, transparent);
}
.arc {
  stroke: var(--p-primary);
  transition: stroke-dasharray 0.6s ease;
}
.num {
  font-size: 13px;
  font-weight: 700;
  fill: var(--p-text);
}
.label {
  font-size: 11px;
  color: var(--p-muted);
}
@media (max-width: 768px) {
  .nas-overview {
    gap: 8px;
  }
}
</style>
