<template>
  <div class="viewer">
    <div class="viewer-head">
      <h3>Redis · {{ service.host }}:{{ service.port }}</h3>
      <el-tag v-if="version" size="small" type="success">v{{ version }}</el-tag>
      <el-tag v-if="info" size="small">{{ t('lan.redis.keys') }}: {{ info.dbsize }}</el-tag>
    </div>
    <el-tabs v-model="tab" @tab-change="onTab">
      <el-tab-pane :label="t('lan.redis.keysTab')" name="keys">
        <div class="tab-toolbar">
          <el-select v-model="dbIndex" size="small" style="width: 90px" @change="loadKeys(true)">
            <el-option v-for="i in 16" :key="i - 1" :value="i - 1" :label="`db${i - 1}`" />
          </el-select>
          <el-input v-model="match" size="small" clearable style="width: 220px"
            :placeholder="t('lan.redis.matchPh')" @keyup.enter="loadKeys(true)" />
          <el-button size="small" @click="loadKeys(true)">{{ t('common.search') }}</el-button>
          <span class="spacer" />
          <el-button size="small" :disabled="!cursor" @click="loadMore">{{ t('common.more') }}</el-button>
        </div>
        <el-table :data="keys" size="small" v-loading="loadingKeys" max-height="400"
          @row-click="openKey" highlight-current-row>
          <el-table-column prop="key" label="Key" min-width="240" show-overflow-tooltip />
          <el-table-column prop="type" :label="t('lan.redis.colType')" width="90" />
          <el-table-column :label="t('lan.redis.colTtl')" width="110">
            <template #default="{ row }">{{ row.ttl === -1 ? '∞' : row.ttl + ' s' }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane :label="t('lan.redis.infoTab')" name="info">
        <el-collapse v-if="info">
          <el-collapse-item v-for="(rows, sec) in info.sections" :key="sec" :title="sec" :name="sec">
            <div class="info-grid">
              <template v-for="(v, k) in rows" :key="k">
                <span class="k">{{ k }}</span><span class="v">{{ v }}</span>
              </template>
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>
      <el-tab-pane :label="t('lan.redis.slowTab')" name="slowlog">
        <el-table :data="slowlog" size="small" max-height="420">
          <el-table-column prop="id" label="Id" width="90" />
          <el-table-column :label="t('lan.redis.colTime')" width="170">
            <template #default="{ row }">{{ fmtTs(row.started_at) }}</template>
          </el-table-column>
          <el-table-column :label="t('lan.redis.colCost')" width="110">
            <template #default="{ row }">{{ (row.duration_us / 1000).toFixed(1) }} ms</template>
          </el-table-column>
          <el-table-column prop="command" label="Command" min-width="260" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>
      <el-tab-pane :label="t('lan.redis.clientsTab')" name="clients">
        <el-table :data="clients" size="small" max-height="420">
          <el-table-column prop="id" label="Id" width="90" />
          <el-table-column prop="addr" label="Addr" min-width="180" />
          <el-table-column prop="name" label="Name" width="110" />
          <el-table-column prop="db" label="DB" width="70" />
          <el-table-column prop="cmd" label="Cmd" width="120" />
          <el-table-column prop="idle" label="Idle(s)" width="90" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 键详情 -->
    <el-dialog v-model="keyVisible" :title="keyDetail?.key || ''" width="640px">
      <template v-if="keyDetail">
        <div class="kv"><span>{{ t('lan.redis.colType') }}</span><b>{{ keyDetail.type }}</b></div>
        <div class="kv"><span>{{ t('lan.redis.colTtl') }}</span>
          <b>{{ keyDetail.ttl === -1 ? '∞' : keyDetail.ttl + ' s' }}</b></div>
        <div class="kv" v-if="keyDetail.memory_bytes != null"><span>{{ t('lan.redis.mem') }}</span>
          <b>{{ fmtBytes(keyDetail.memory_bytes) }}</b></div>
        <div class="kv" v-if="keyDetail.size_bytes != null && keyDetail.type !== 'string'">
          <span>{{ t('lan.redis.size') }}</span><b>{{ keyDetail.size_bytes }}</b>
        </div>
        <template v-if="keyDetail.type === 'string'">
          <div class="value-box" :class="{ hex: keyDetail.binary }">{{ keyDetail.preview }}</div>
          <div v-if="keyDetail.truncated" class="truncated">{{ t('lan.redis.truncated') }}</div>
        </template>
        <el-table v-else :data="keyDetail.items || []" size="small" max-height="300">
          <el-table-column v-if="keyDetail.type === 'hash'" prop="field" label="Field" min-width="150" />
          <el-table-column v-else-if="keyDetail.type === 'zset'" prop="member" label="Member" min-width="150" />
          <el-table-column :label="t('lan.redis.value')">
            <template #default="{ row }">
              <span :class="{ hex: row.binary }">{{ row.preview }}</span>
              <el-tag v-if="row.score != null" size="small" style="margin-left: 6px">{{ row.score }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { lanDbApi } from '../../api/lan'
import type { DbServiceItem, RedisKeyDetail, RedisKeyRow } from '../../api/lan'
import dayjs from 'dayjs'

const props = defineProps<{ service: DbServiceItem }>()
const { t } = useI18n()

const tab = ref('keys')
const info = ref<Awaited<ReturnType<typeof lanDbApi.redisInfo>> | null>(null)
const version = computed(() => String(info.value?.sections?.server?.redis_version ?? ''))
const keys = ref<RedisKeyRow[]>([])
const loadingKeys = ref(false)
const dbIndex = ref(0)
const match = ref('')
const cursor = ref(0)
const slowlog = ref<Array<{ id: number; started_at: number; duration_us: number; command: string }>>([])
const clients = ref<Array<Record<string, unknown>>>([])
const keyVisible = ref(false)
const keyDetail = ref<RedisKeyDetail | null>(null)

const loaded = new Set<string>()

async function onTab(name: string | number) {
  const key = name.toString()
  if (loaded.has(key)) return
  loaded.add(key)
  if (key === 'slowlog') slowlog.value = (await lanDbApi.redisSlowlog(props.service.id)).items
  if (key === 'clients') clients.value = (await lanDbApi.redisClients(props.service.id)).items
}

async function loadKeys(reset: boolean) {
  loadingKeys.value = true
  try {
    const data = await lanDbApi.redisKeys(props.service.id, {
      db: dbIndex.value, cursor: reset ? 0 : cursor.value, match: match.value,
    })
    keys.value = reset ? data.items : [...keys.value, ...data.items]
    cursor.value = data.cursor
  } finally {
    loadingKeys.value = false
  }
}

async function loadMore() {
  await loadKeys(false)
}

async function openKey(row: RedisKeyRow) {
  keyDetail.value = await lanDbApi.redisKey(props.service.id, { key: row.key, db: dbIndex.value })
  keyVisible.value = true
}

function fmtTs(ts: number) {
  return dayjs.unix(ts).format('MM-DD HH:mm:ss')
}

function fmtBytes(n: number) {
  if (n > 1 << 20) return (n / (1 << 20)).toFixed(1) + ' MB'
  if (n > 1 << 10) return (n / (1 << 10)).toFixed(1) + ' KB'
  return n + ' B'
}

onMounted(async () => {
  info.value = await lanDbApi.redisInfo(props.service.id)
  loaded.add('info')
  await loadKeys(true)
})
</script>

<style scoped>
.viewer {
  padding: 6px 2px;
}
.viewer-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.viewer-head h3 {
  margin: 0;
  font-size: 16px;
}
.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.spacer {
  flex: 1;
}
.info-grid {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 4px 12px;
  font-size: 13px;
}
.info-grid .k {
  color: var(--p-text-secondary, #909399);
}
.kv {
  display: flex;
  gap: 10px;
  margin: 4px 0;
  font-size: 13px;
}
.kv span {
  color: var(--p-text-secondary, #909399);
  min-width: 60px;
}
.value-box {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  font-family: monospace;
  font-size: 12.5px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
}
.hex {
  font-family: monospace;
  word-break: break-all;
}
.truncated {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-color-warning);
}
</style>
