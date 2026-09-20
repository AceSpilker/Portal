<template>
  <div class="viewer">
    <div class="viewer-head">
      <h3>MinIO · {{ service.host }}:{{ service.port }}</h3>
      <el-tag v-if="overview" size="small" :type="overview.healthy ? 'success' : 'danger'">
        {{ overview.healthy ? 'Healthy' : 'Unreachable' }}
      </el-tag>
    </div>

    <!-- 桶视图 -->
    <template v-if="!currentBucket">
      <div v-if="overview" class="stat-grid" style="margin-bottom: 14px">
        <div class="glass stat-card"><b>{{ overview.bucket_count }}</b><span>{{ t('lan.minio.buckets') }}</span></div>
        <div class="glass stat-card"><b>{{ overview.object_count }}</b><span>{{ t('lan.minio.objects') }}</span></div>
        <div class="glass stat-card"><b>{{ fmtBytes(overview.total_size_bytes) }}</b><span>{{ t('lan.minio.size') }}</span></div>
      </div>
      <el-table :data="buckets" size="small" v-loading="loading" max-height="420">
        <el-table-column prop="name" label="Bucket" min-width="180" />
        <el-table-column prop="object_count" :label="t('lan.minio.objects')" width="120" />
        <el-table-column :label="t('lan.minio.size')" width="130">
          <template #default="{ row }">
            {{ fmtBytes(row.size_bytes) }}
            <el-tag v-if="row.truncated" size="small" type="info">≈</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" :label="t('lan.minio.created')" width="180" />
        <el-table-column :label="t('lan.colOp')" width="110" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="enterBucket(row.name)">{{ t('lan.minio.browse') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- 对象视图 -->
    <template v-else>
      <div class="crumbs">
        <el-button size="small" link @click="leaveBucket">{{ t('lan.minio.backBuckets') }}</el-button>
        <el-divider direction="vertical" />
        <b>{{ currentBucket }}</b>
        <span class="prefix">/{{ prefix }}</span>
      </div>
      <el-table :data="objects" size="small" v-loading="loadingObjects" max-height="400">
        <el-table-column prop="key" label="Key" min-width="280" show-overflow-tooltip />
        <el-table-column :label="t('lan.minio.size')" width="120">
          <template #default="{ row }">{{ fmtBytes(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="etag" label="ETag" width="150" show-overflow-tooltip />
        <el-table-column prop="last_modified" :label="t('lan.minio.modified')" width="180" />
        <el-table-column :label="t('lan.colOp')" width="120" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="download(row)">{{ t('lan.minio.download') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="nextToken" style="margin-top: 10px; text-align: center">
        <el-button size="small" :loading="loadingObjects" @click="loadObjects(false)">
          {{ t('common.more') }}
        </el-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { lanDbApi } from '../../api/lan'
import type { DbServiceItem, MinioBucket, MinioObject } from '../../api/lan'

const props = defineProps<{ service: DbServiceItem }>()
const { t } = useI18n()

const overview = ref<Awaited<ReturnType<typeof lanDbApi.minioOverview>> | null>(null)
const buckets = ref<MinioBucket[]>([])
const loading = ref(false)
const currentBucket = ref('')
const prefix = ref('')
const objects = ref<MinioObject[]>([])
const nextToken = ref('')
const loadingObjects = ref(false)

async function loadBuckets() {
  loading.value = true
  try {
    const [ov, bs] = await Promise.all([lanDbApi.minioOverview(props.service.id), lanDbApi.minioBuckets(props.service.id)])
    overview.value = ov
    buckets.value = bs.items
  } finally {
    loading.value = false
  }
}

function enterBucket(name: string) {
  currentBucket.value = name
  prefix.value = ''
  loadObjects(true)
}

function leaveBucket() {
  currentBucket.value = ''
  objects.value = []
}

async function loadObjects(reset: boolean) {
  loadingObjects.value = true
  try {
    const data = await lanDbApi.minioObjects(props.service.id, {
      bucket: currentBucket.value,
      prefix: prefix.value,
      token: reset ? '' : nextToken.value,
    })
    objects.value = reset ? data.objects : [...objects.value, ...data.objects]
    nextToken.value = data.truncated ? data.next_token : ''
  } finally {
    loadingObjects.value = false
  }
}

async function download(row: MinioObject) {
  const { url } = await lanDbApi.minioObjectUrl(props.service.id, {
    bucket: currentBucket.value, key: row.key,
  })
  window.open(url, '_blank')
}

function fmtBytes(n: number) {
  if (n > 1 << 30) return (n / (1 << 30)).toFixed(1) + ' GB'
  if (n > 1 << 20) return (n / (1 << 20)).toFixed(1) + ' MB'
  if (n > 1 << 10) return (n / (1 << 10)).toFixed(1) + ' KB'
  return n + ' B'
}

onMounted(loadBuckets)
</script>

<style scoped>
.viewer {
  padding: 6px 2px;
}
.viewer-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.viewer-head h3 {
  margin: 0;
  font-size: 16px;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
}
.stat-card {
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-card b {
  font-size: 18px;
}
.stat-card span {
  font-size: 12px;
  color: var(--p-muted);
}
.crumbs {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  font-size: 14px;
}
.prefix {
  color: var(--p-muted);
  font-size: 13px;
}
</style>
