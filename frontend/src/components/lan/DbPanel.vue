<template>
  <div class="db-panel">
    <div class="ov-toolbar">
      <span class="stat-chip">{{ t('lan.db.statTotal') }} <b>{{ services.length }}</b></span>
      <span class="stat-chip">{{ t('lan.db.statUp') }} <b>{{ upCount }}</b></span>
      <span class="stat-chip">{{ t('lan.db.statCred') }} <b>{{ withCredCount }}</b></span>
      <span class="spacer" />
      <el-select v-model="typeFilter" size="small" clearable style="width: 140px" :placeholder="t('lan.allTypes')">
        <el-option v-for="tp in serviceTypes" :key="tp" :value="tp" :label="tp" />
      </el-select>
      <el-button v-if="auth.isAdmin" size="small" type="primary" :loading="scanning" @click="startScan">
        {{ t('lan.db.scanNow') }}
      </el-button>
      <el-button v-if="auth.isAdmin" size="small" @click="openCreds">{{ t('lan.db.creds') }}</el-button>
      <el-button size="small" :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
    </div>

    <el-table :data="filtered" size="small" v-loading="loading">
      <el-table-column :label="t('lan.colState')" width="84" align="center">
        <template #default="{ row }">
          <span class="state-pill" :class="row.state">{{ t(`ports.state.${row.state}`) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="130">
        <template #default="{ row }">
          <el-tag size="small" :type="typeTag(row.service_type)">{{ row.service_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('lan.db.colTarget')" min-width="160">
        <template #default="{ row }">
          <b>{{ row.host }}:{{ row.port }}</b>
          <span v-if="row.device?.hostname" class="dev-note">@ {{ row.device.hostname }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('lan.db.colVersion')" min-width="110">
        <template #default="{ row }">{{ row.version || '—' }}</template>
      </el-table-column>
      <el-table-column :label="t('lan.db.colLatency')" width="90">
        <template #default="{ row }">{{ row.latency_ms != null ? row.latency_ms + ' ms' : '—' }}</template>
      </el-table-column>
      <el-table-column :label="t('lan.db.colCred')" width="90" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.credential_id" size="small" type="success">{{ t('lan.db.credSet') }}</el-tag>
          <el-tag v-else size="small" type="info">—</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('lan.colOp')" width="200" align="center">
        <template #default="{ row }">
          <template v-if="auth.isAdmin && viewable(row.service_type) && row.credential_id">
            <el-button size="small" link type="primary" @click="openViewer(row)">{{ t('lan.db.view') }}</el-button>
            <el-divider direction="vertical" />
          </template>
          <el-button v-if="auth.isAdmin" size="small" link @click="addMonitor(row)">{{ t('lan.addMonitor') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 凭据管理抽屉 -->
    <el-drawer v-model="credsVisible" :title="t('lan.db.credsTitle')" size="520px">
      <div class="creds-toolbar">
        <el-button size="small" type="primary" @click="openEdit(null)">{{ t('lan.db.credNew') }}</el-button>
        <span class="spacer" />
        <el-button size="small" :loading="credLoading" @click="loadCreds">{{ t('common.refresh') }}</el-button>
      </div>
      <el-table :data="creds" size="small" v-loading="credLoading">
        <el-table-column :label="t('lan.db.colTarget')" min-width="150">
          <template #default="{ row }">{{ row.service_type }} · {{ row.host }}:{{ row.port }}</template>
        </el-table-column>
        <el-table-column prop="username" label="用户" width="110" show-overflow-tooltip />
        <el-table-column :label="t('lan.db.colTest')" width="86" align="center">
          <template #default="{ row }">
            <span v-if="row.last_test_ok != null" class="state-pill" :class="row.last_test_ok ? 'up' : 'down'">
              {{ row.last_test_ok ? 'OK' : 'FAIL' }}
            </span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('lan.colOp')" width="170" align="center">
          <template #default="{ row }">
            <el-button size="small" link type="primary" :loading="testingId === row.id" @click="testCred(row)">
              {{ t('lan.db.test') }}
            </el-button>
            <el-divider direction="vertical" />
            <el-button size="small" link @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-button size="small" link type="danger" @click="removeCred(row)">{{ t('common.delete') }}</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 凭据编辑 -->
      <el-dialog v-model="editVisible" :title="editId ? t('lan.db.credEdit') : t('lan.db.credNew')" width="460px" append-to-body>
        <el-form label-width="110px" label-position="left">
          <el-form-item label="类型">
            <el-select v-model="editForm.service_type" :disabled="!!editId" style="width: 160px">
              <el-option value="mysql" label="MySQL" />
              <el-option value="redis" label="Redis" />
              <el-option value="minio" label="MinIO" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('lan.db.credHost')">
            <el-input v-model="editForm.host" style="width: 200px" placeholder="192.168.1.10 / 127.0.0.1" />
            <el-input-number v-model="editForm.port" :min="1" :max="65535" style="margin-left: 8px; width: 120px" />
          </el-form-item>
          <el-form-item v-if="editForm.service_type !== 'redis'" label="用户名">
            <el-input v-model="editForm.username" style="width: 240px" />
          </el-form-item>
          <el-form-item :label="t('lan.db.credPass')">
            <el-input v-model="editForm.password" type="password" show-password style="width: 240px"
              :placeholder="editId && editPasswordSet ? t('lan.keepPlaceholder') : ''" />
          </el-form-item>
          <el-form-item v-if="editForm.service_type === 'mysql'" label="Database">
            <el-input v-model="editForm.database" style="width: 240px" placeholder="mysql" />
          </el-form-item>
          <el-form-item v-if="editForm.service_type === 'redis'" label="DB">
            <el-input-number v-model="editForm.db" :min="0" :max="15" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editVisible = false">{{ t('common.cancel') }}</el-button>
          <el-button type="primary" :loading="savingCred" @click="saveCred">{{ t('common.save') }}</el-button>
        </template>
      </el-dialog>
    </el-drawer>

    <!-- 查看器抽屉 -->
    <el-drawer v-model="viewerVisible" size="70%" :with-header="false" destroy-on-close>
      <MysqlViewer v-if="viewerService?.service_type === 'mysql'" :service="viewerService" />
      <RedisViewer v-else-if="viewerService?.service_type === 'redis'" :service="viewerService" />
      <MinioViewer v-else-if="viewerService?.service_type === 'minio'" :service="viewerService" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { lanDbApi } from '../../api/lan'
import type { DbCredentialItem, DbServiceItem } from '../../api/lan'
import { useAuthStore } from '../../stores/auth'
import MysqlViewer from './MysqlViewer.vue'
import RedisViewer from './RedisViewer.vue'
import MinioViewer from './MinioViewer.vue'

const { t } = useI18n()
const auth = useAuthStore()

const serviceTypes = ['mysql', 'redis', 'minio', 'postgresql', 'mongodb', 'elasticsearch', 'memcached', 'etcd', 'clickhouse']
const loading = ref(false)
const services = ref<DbServiceItem[]>([])
const typeFilter = ref('')
const scanning = ref(false)

const upCount = computed(() => services.value.filter((s) => s.state === 'up').length)
const withCredCount = computed(() => services.value.filter((s) => s.credential_id).length)
const filtered = computed(() =>
  typeFilter.value ? services.value.filter((s) => s.service_type === typeFilter.value) : services.value,
)

async function load() {
  loading.value = true
  try {
    services.value = (await lanDbApi.services()).items
  } finally {
    loading.value = false
  }
}

async function startScan() {
  scanning.value = true
  try {
    await lanDbApi.startScan()
    ElMessage.success(t('lan.scanStarted'))
  } finally {
    scanning.value = false
  }
}

function viewable(tp: string) {
  return ['mysql', 'redis', 'minio'].includes(tp)
}

function typeTag(tp: string): 'success' | 'danger' | 'primary' | 'info' {
  const map: Record<string, 'success' | 'danger' | 'primary' | 'info'> = {
    mysql: 'danger', redis: 'success', minio: 'primary',
  }
  return map[tp] || 'info'
}

async function addMonitor(row: DbServiceItem) {
  await lanDbApi.createMonitor(row.id)
  ElMessage.success(t('lan.monitorAdded'))
}

// ---- 凭据管理 ----
const credsVisible = ref(false)
const credLoading = ref(false)
const creds = ref<DbCredentialItem[]>([])
const testingId = ref<number | null>(null)

async function loadCreds() {
  credLoading.value = true
  try {
    creds.value = (await lanDbApi.credentials()).items
  } finally {
    credLoading.value = false
  }
}

async function openCreds() {
  credsVisible.value = true
  await loadCreds()
}

async function testCred(row: DbCredentialItem) {
  testingId.value = row.id
  try {
    const result = await lanDbApi.testCredential(row.id)
    if (result.ok) {
      ElMessage.success(result.detail)
    } else {
      ElMessage.warning(result.detail)
    }
    await loadCreds()
  } finally {
    testingId.value = null
  }
}

async function removeCred(row: DbCredentialItem) {
  await ElMessageBox.confirm(
    t('lan.db.credDeleteConfirm', { target: `${row.host}:${row.port}` }),
    t('common.confirm'),
    { type: 'warning' },
  )
  await lanDbApi.deleteCredential(row.id)
  ElMessage.success(t('common.deleted'))
  await loadCreds()
  await load()
}

// ---- 凭据编辑 ----
const editVisible = ref(false)
const editId = ref<number | null>(null)
const editPasswordSet = ref(false)
const savingCred = ref(false)
const editForm = ref({
  service_type: 'mysql', host: '', port: 3306, username: '', password: '', database: '', db: 0,
})

function openEdit(row: DbCredentialItem | null) {
  editId.value = row?.id ?? null
  editPasswordSet.value = row?.password_set ?? false
  editForm.value = {
    service_type: row?.service_type ?? 'mysql',
    host: row?.host ?? '',
    port: row?.port ?? 3306,
    username: row?.username ?? '',
    password: '',
    database: String((row?.extra as Record<string, unknown>)?.database ?? ''),
    db: Number((row?.extra as Record<string, unknown>)?.db ?? 0),
  }
  editVisible.value = true
}

async function saveCred() {
  savingCred.value = true
  try {
    const f = editForm.value
    const extra: Record<string, unknown> = {}
    if (f.service_type === 'mysql' && f.database) extra.database = f.database
    if (f.service_type === 'redis') extra.db = f.db
    const body: Record<string, unknown> = {
      service_type: f.service_type, host: f.host.trim(), port: f.port,
      username: f.username, password: f.password, extra,
    }
    if (editId.value) {
      await lanDbApi.updateCredential(editId.value, body)
    } else {
      await lanDbApi.createCredential(body)
    }
    ElMessage.success(t('common.saved'))
    editVisible.value = false
    await loadCreds()
    await load()
  } finally {
    savingCred.value = false
  }
}

// ---- 查看器 ----
const viewerVisible = ref(false)
const viewerService = ref<DbServiceItem | null>(null)

function openViewer(row: DbServiceItem) {
  viewerService.value = row
  viewerVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.db-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ov-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.spacer {
  flex: 1;
}
.dev-note {
  margin-left: 6px;
  color: var(--p-text-secondary, #909399);
  font-size: 12px;
}
.state-pill {
  display: inline-block;
  padding: 1px 10px;
  border-radius: 999px;
  font-size: 12px;
}
.state-pill.up {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
}
.state-pill.down {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
}
.state-pill.unknown {
  background: var(--el-fill-color-light);
  color: var(--p-text-secondary, #909399);
}
.creds-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
}
</style>
