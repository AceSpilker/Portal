<script setup lang="ts">
/**
 * 首页小组件（M02-11/13~15；dev-plan P15.2）：天气 / 最近通知 / Flow 状态 / 容器状态。
 * 数据失败或模块未启用时自动隐藏。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { appsEnhApi, type WeatherInfo, type WidgetsSummary } from '../api/appsEnh'

const { t } = useI18n()
const weather = ref<WeatherInfo | null>(null)
const summary = ref<WidgetsSummary | null>(null)

function weatherIcon(desc: string): string {
  const d = desc.toLowerCase()
  if (d.includes('rain') || d.includes('drizzle')) return '🌧️'
  if (d.includes('snow')) return '🌨️'
  if (d.includes('cloud') || d.includes('overcast')) return '☁️'
  if (d.includes('thunder')) return '⛈️'
  if (d.includes('fog') || d.includes('mist')) return '🌫️'
  return '☀️'
}

onMounted(async () => {
  appsEnhApi.weather().then((w) => (weather.value = w)).catch(() => {})
  appsEnhApi.summary().then((s) => (summary.value = s)).catch(() => {})
})
</script>

<template>
  <div class="widgets-row fade-up">
    <!-- 天气 -->
    <section v-if="weather" class="glass widget">
      <div class="wx-main">
        <span class="wx-icon">{{ weatherIcon(weather.desc) }}</span>
        <span class="wx-temp">{{ weather.temp_c }}°C</span>
      </div>
      <div class="wx-desc">{{ weather.city }} · {{ weather.desc }} · {{ t('home.wx.feels') }} {{ weather.feels_c }}°C</div>
      <div class="wx-days">
        <div v-for="d in weather.days" :key="d.date" class="wx-day">
          <span class="wx-date">{{ d.date.slice(5) }}</span>
          <span>{{ d.max }}° / {{ d.min }}°</span>
        </div>
      </div>
    </section>

    <!-- 最近通知 -->
    <section v-if="summary && summary.notifications.length" class="glass widget">
      <h4>{{ t('home.wx.notifications') }}</h4>
      <div class="mini-list">
        <div v-for="n in summary.notifications" :key="n.id" class="mini-row">
          <span class="dot" :class="n.level" />
          <span class="mini-title">{{ n.title }}</span>
          <span v-if="!n.is_read" class="unread-dot" />
        </div>
      </div>
    </section>

    <!-- Flow 状态 -->
    <section v-if="summary && summary.flow_runs.length" class="glass widget">
      <h4>{{ t('home.wx.flows') }}</h4>
      <div class="mini-list">
        <div v-for="r in summary.flow_runs" :key="r.id" class="mini-row">
          <span class="dot" :class="r.status === 'success' ? 'up' : r.status === 'failed' ? 'down' : 'unknown'" />
          <span class="mini-title">{{ r.flow }}</span>
          <span class="mini-meta">{{ r.status }}</span>
        </div>
      </div>
    </section>

    <!-- 容器状态 -->
    <section v-if="summary && summary.docker" class="glass widget">
      <h4>{{ t('home.wx.docker') }}</h4>
      <div class="docker-nums">
        <span class="dn up">{{ summary.docker.running }} {{ t('home.wx.running') }}</span>
        <span class="dn">{{ summary.docker.stopped }} {{ t('home.wx.stopped') }}</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.widgets-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.widget {
  flex: 1;
  min-width: 220px;
  padding: 12px 14px;
  border-radius: 12px;
}
.widget h4 {
  margin: 0 0 8px;
  font-size: 13px;
}
.wx-main {
  display: flex;
  align-items: center;
  gap: 12px;
}
.wx-icon {
  font-size: 30px;
}
.wx-temp {
  font-size: 26px;
  font-weight: 700;
}
.wx-desc {
  font-size: 12px;
  color: var(--p-muted);
  margin: 4px 0 8px;
}
.wx-days {
  display: flex;
  gap: 10px;
  font-size: 12px;
}
.wx-day {
  display: flex;
  flex-direction: column;
  color: var(--p-muted);
}
.wx-date {
  font-weight: 600;
  color: var(--p-text);
}
.mini-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.mini-row {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--el-color-info);
}
.dot.info { background: var(--el-color-info); }
.dot.warn { background: var(--el-color-warning); }
.dot.error { background: var(--el-color-danger); }
.dot.up { background: var(--el-color-success); }
.dot.down { background: var(--el-color-danger); }
.dot.unknown { background: var(--el-color-info); }
.mini-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.unread-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
}
.mini-meta {
  color: var(--p-muted);
}
.docker-nums {
  display: flex;
  gap: 14px;
  font-size: 15px;
  font-weight: 700;
}
.dn.up {
  color: var(--el-color-success);
}
</style>
