<script setup lang="ts">
/**
 * 应用可用性（M07-3/4；dev-plan P10.4）：24h/7d/30d 可用率 + 最近事件时间线。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import request from '../api/request'

const { t } = useI18n()
const range = ref<'24h' | '7d' | '30d'>('24h')
const apps = ref<AvailabilityApp[]>([])
const timeline = ref<TimelineItem[]>([])
const loading = ref(false)

interface AvailabilityApp {
  app_id: number
  name: string
  uptime_pct: number | null
  current_state: string
  event_count: number
}
interface TimelineItem {
  app_id: number
  app_name: string
  event: string
  latency_ms: number | null
  created_at: string
}

function onRange(v: '24h' | '7d' | '30d') {
  range.value = v
  void load()
}

async function load() {
  loading.value = true
  try {
    const data = await request.get<never, { apps: AvailabilityApp[]; timeline: TimelineItem[] }>(
      '/probe/availability',
      { params: { range: range.value } },
    )
    apps.value = data.apps
    timeline.value = data.timeline.slice(0, 12)
  } finally {
    loading.value = false
  }
}

function pctClass(v: number | null): string {
  if (v === null) return 'unknown'
  if (v >= 99) return 'good'
  if (v >= 95) return 'mid'
  return 'bad'
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <section class="glass chart-card">
    <header class="avail-head">
      <h3>{{ t('monitor.availTitle') }}</h3>
      <el-radio-group :model-value="range" size="small" @update:model-value="onRange">
        <el-radio-button value="24h">{{ t('monitor.range.24h') }}</el-radio-button>
        <el-radio-button value="7d">{{ t('monitor.range.7d') }}</el-radio-button>
        <el-radio-button value="30d">{{ t('monitor.range.30d') }}</el-radio-button>
      </el-radio-group>
    </header>

    <div v-if="apps.length === 0" class="empty">{{ t('monitor.availEmpty') }}</div>
    <div v-else class="avail-rows">
      <div v-for="a in apps" :key="a.app_id" class="avail-row">
        <span class="avail-name">{{ a.name }}</span>
        <span class="avail-pct" :class="pctClass(a.uptime_pct)">
          {{ a.uptime_pct === null ? t('monitor.availUnknown') : a.uptime_pct + '%' }}
        </span>
      </div>
    </div>

    <div v-if="timeline.length" class="avail-timeline">
      <div class="tl-title">{{ t('monitor.availTimeline') }}</div>
      <div v-for="(e, i) in timeline" :key="i" class="tl-row">
        <span class="tl-dot" :class="e.event === 'up' ? 'up' : e.event === 'down' ? 'down' : 'slow'" />
        <span class="tl-text">{{ e.app_name }} · {{ t(`monitor.status${e.event[0].toUpperCase()}${e.event.slice(1)}`) }}
          <template v-if="e.latency_ms !== null"> · {{ e.latency_ms }}ms</template>
        </span>
        <span class="tl-time">{{ timeLabel(e.created_at) }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.avail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.avail-head h3 {
  margin: 0;
}
.empty {
  color: var(--p-muted);
  font-size: 13px;
  padding: 8px 0;
}
.avail-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 6px;
}
.avail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}
.avail-name {
  font-weight: 600;
}
.avail-pct.good { color: var(--el-color-success); }
.avail-pct.mid { color: var(--el-color-warning); }
.avail-pct.bad { color: var(--el-color-danger); }
.avail-pct.unknown { color: var(--p-muted); }
.avail-timeline {
  border-top: 1px dashed var(--p-border, rgba(127, 127, 127, 0.25));
  padding-top: 8px;
}
.tl-title {
  font-size: 12px;
  color: var(--p-muted);
  margin-bottom: 6px;
}
.tl-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  padding: 2px 0;
}
.tl-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tl-dot.up { background: var(--el-color-success); }
.tl-dot.down { background: var(--el-color-danger); }
.tl-dot.slow { background: var(--el-color-warning); }
.tl-text {
  flex: 1;
  min-width: 0;
}
.tl-time {
  color: var(--p-muted);
  flex-shrink: 0;
}
</style>
