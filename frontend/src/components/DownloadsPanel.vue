<script setup lang="ts">
/**
 * 下载与媒体面板（M12-1/2/4/5；dev-plan P16.3）。
 *
 * - qBittorrent 任务列表/速度/进度 + 磁力/URL 下发（管理员）；
 * - 下载完成通知由后端轮询推送（P9 路由）；
 * - Jellyfin 最近入库海报墙（海报经服务端代理，key 不落前端）。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Plus as IconPlus, Refresh as IconRefresh } from '@element-plus/icons-vue'
import { downloadsApi } from '../api/downloads'
import type { MediaItem, TorrentTask } from '../api/downloads'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const auth = useAuthStore()

const summary = ref<Awaited<ReturnType<typeof downloadsApi.summary>> | null>(null)
const tasks = ref<TorrentTask[]>([])
const media = ref<MediaItem[]>([])
const loading = ref(false)
const addVisible = ref(false)
const addText = ref('')

const unavailable = ref(false)

function fmtSpeed(n: number): string {
  if (!n) return '0 B/s'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

function fmtSize(n: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

async function load() {
  if (!auth.isAdmin) return
  loading.value = true
  try {
    summary.value = await downloadsApi.summary()
    unavailable.value = false
    if (summary.value.connected) {
      tasks.value = await downloadsApi.tasks()
    }
    try {
      media.value = (await downloadsApi.mediaRecent()).items
    } catch {
      media.value = [] // 媒体库未配置自动隐藏
    }
  } catch {
    unavailable.value = true // 404：下载器未启用
  } finally {
    loading.value = false
  }
}

async function addTasks() {
  const urls = addText.value.split('\n').map((s) => s.trim()).filter(Boolean)
  if (!urls.length) {
    ElMessage.warning(t('eff.urlRequired'))
    return
  }
  try {
    const r = await downloadsApi.add(urls)
    ElMessage.success(t('eff.addDone', { n: r.count }))
    addVisible.value = false
    addText.value = ''
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

const statCards = computed(() => [
  { label: t('eff.dlSpeed'), value: fmtSpeed(summary.value?.speed.dl ?? 0) },
  { label: t('eff.upSpeed'), value: fmtSpeed(summary.value?.speed.up ?? 0) },
  { label: t('eff.downloading'), value: summary.value?.counts.downloading ?? 0 },
  { label: t('eff.completedN'), value: summary.value?.counts.completed ?? 0 },
])

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="dl">
    <section v-if="unavailable" class="glass empty-state">
      <p>{{ t('eff.dlNotConfigured') }}</p>
      <el-button v-if="auth.isAdmin" type="primary" class="btn-gradient" @click="$router.push('/settings')">
        {{ t('eff.goSettings') }}
      </el-button>
    </section>

    <template v-else>
      <section class="stat-row">
        <div v-for="s in statCards" :key="s.label" class="glass stat-card">
          <span class="stat-value">{{ s.value }}</span>
          <span class="stat-label">{{ s.label }}</span>
        </div>
      </section>

      <section class="glass dl-body">
        <header class="sec-head">
          <h3>{{ t('eff.tasks') }}</h3>
          <span class="spacer" />
          <template v-if="auth.isAdmin">
            <el-button size="small" type="primary" class="btn-gradient" :icon="IconPlus" @click="addVisible = true">
              {{ t('eff.addTask') }}
            </el-button>
          </template>
          <el-button size="small" :icon="IconRefresh" circle @click="load" />
        </header>

        <p v-if="summary && !summary.connected" class="conn-warn">
          {{ t('eff.dlUnreachable', { msg: summary.error ?? '' }) }}
        </p>

        <el-table :data="tasks" size="small" style="width: 100%">
          <el-table-column prop="name" :label="t('eff.colName')" min-width="240" show-overflow-tooltip />
          <el-table-column :label="t('eff.colProgress')" width="170">
            <template #default="{ row }">
              <el-progress :percentage="row.progress" :stroke-width="8" :status="row.completed ? 'success' : undefined" />
            </template>
          </el-table-column>
          <el-table-column :label="t('eff.colSize')" width="90">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column :label="t('eff.colDl')" width="100">
            <template #default="{ row }">{{ fmtSpeed(row.dlspeed) }}</template>
          </el-table-column>
          <el-table-column prop="state" :label="t('eff.colState')" width="110" />
        </el-table>
      </section>

      <section v-if="media.length" class="glass dl-body">
        <header class="sec-head">
          <h3>{{ t('eff.mediaRecent') }}</h3>
        </header>
        <div class="poster-wall">
          <figure v-for="m in media" :key="m.id" class="poster" :title="m.title">
            <img v-if="m.poster" :src="m.poster" :alt="m.title" loading="lazy" />
            <div v-else class="poster-ph">🎬</div>
            <figcaption>
              <span class="poster-title">{{ m.title }}</span>
              <span v-if="m.series" class="poster-sub">{{ m.series }} · {{ m.added_at }}</span>
            </figcaption>
          </figure>
        </div>
      </section>
    </template>

    <el-dialog v-model="addVisible" :title="t('eff.addTask')" width="480px" append-to-body>
      <el-input
        v-model="addText"
        type="textarea"
        :rows="5"
        :placeholder="t('eff.addPlaceholder')"
      />
      <template #footer>
        <el-button @click="addVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="addTasks">{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.stat-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 18px;
}
.stat-value {
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.stat-label {
  font-size: 12px;
  color: var(--p-muted);
}
.dl-body {
  padding: 12px 16px;
}
.sec-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.sec-head h3 {
  margin: 0;
  font-size: 14px;
}
.spacer {
  flex: 1;
}
.conn-warn {
  color: #d97706;
  font-size: 12.5px;
  margin: 0 0 8px;
}
.poster-wall {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 12px;
}
.poster {
  margin: 0;
}
.poster img,
.poster-ph {
  width: 100%;
  aspect-ratio: 2/3;
  object-fit: cover;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  background: color-mix(in srgb, var(--p-primary) 6%, transparent);
}
figcaption {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.poster-title {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.poster-sub {
  font-size: 11px;
  color: var(--p-muted);
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 46px 0;
  color: var(--p-muted);
}
@media (max-width: 900px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
