<script setup lang="ts">
/**
 * 域名证书卡（M07-6；dev-plan P10.5）：到期天数与分级；域名在 设置 → 通知 → 证书监控 维护。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { monitorApi, type CertInfo } from '../api/monitor'

const { t } = useI18n()
const rows = ref<CertInfo[] | null>(null)

function cls(level?: string): string {
  return level === 'ok' ? 'good' : level === 'info' ? 'mid' : level === 'warn' ? 'warn' : 'bad'
}

onMounted(async () => {
  try {
    rows.value = await monitorApi.certs()
  } catch {
    rows.value = []
  }
})
</script>

<template>
  <section v-if="rows && rows.length" class="glass chart-card">
    <h3>{{ t('monitor.certTitle') }}</h3>
    <div class="cert-rows">
      <div v-for="c in rows" :key="c.host" class="cert-row">
        <span class="host">{{ c.host }}</span>
        <span v-if="c.error" class="lvl bad">{{ t('monitor.certError') }}</span>
        <span v-else class="lvl" :class="cls(c.level)">
          {{ c.days_left }}{{ t('monitor.certDays') }} · {{ c.not_after }}
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped>
h3 {
  margin: 0 0 8px;
}
.cert-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}
.host {
  font-weight: 600;
}
.lvl.good { color: var(--el-color-success); }
.lvl.mid { color: var(--el-color-success); }
.lvl.warn { color: var(--el-color-warning); }
.lvl.bad { color: var(--el-color-danger); }
</style>
