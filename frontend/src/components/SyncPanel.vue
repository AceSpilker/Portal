<script setup lang="ts">
/**
 * MySQL 同步面板（P23/M15-12）：配置（密码密文存储）+ 连接测试 + 立即推送
 * + 每表状态（sync_state）+ 从 MySQL 恢复（先自动备份）。
 */
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh as IconRefresh, Upload as IconPush } from '@element-plus/icons-vue'
import { syncApi } from '../api/sync'
import type { SyncTableState } from '../api/sync'

const { t } = useI18n()

const form = reactive({
  host: '',
  port: 3306,
  user: '',
  password: '',
  database: 'portal',
  interval_min: 30,
  enabled: false,
})
const passwordSet = ref(false)
const saving = ref(false)
const testing = ref(false)
const pushing = ref(false)
const tables = ref<SyncTableState[]>([])
const statusEnabled = ref(false)

async function load() {
  try {
    const cfg = await syncApi.getConfig()
    Object.assign(form, {
      host: cfg.host,
      port: cfg.port,
      user: cfg.user,
      database: cfg.database,
      interval_min: cfg.interval_min,
      enabled: cfg.enabled,
      password: '',
    })
    passwordSet.value = cfg.password_set
    await loadStatus()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function loadStatus() {
  try {
    const st = await syncApi.status()
    tables.value = st.tables
    statusEnabled.value = st.enabled
  } catch {
    /* ignore */
  }
}

async function save() {
  saving.value = true
  try {
    const payload: Record<string, unknown> = { ...form }
    if (!form.password) delete payload.password // 空=保持原值
    await syncApi.saveConfig(payload)
    ElMessage.success(t('sync.saved'))
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  try {
    // 未保存前测试：先临时保存再用已存配置测（简化且与后端口径一致）
    const payload: Record<string, unknown> = { ...form }
    if (!form.password) delete payload.password
    await syncApi.saveConfig(payload)
    const r = await syncApi.testConnection({})
    if (r.ok) {
      ElMessage.success(t('sync.testOk', { ver: r.server_version ?? '' }))
    } else {
      ElMessage.error(t('sync.testFail', { msg: r.error ?? '' }))
    }
    await loadStatus()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    testing.value = false
  }
}

async function pushNow() {
  pushing.value = true
  try {
    const r = await syncApi.push()
    if (!r.enabled) {
      ElMessage.warning(t('sync.disabled'))
    } else if (r.error) {
      ElMessage.error(t('sync.pushFail', { msg: r.error.slice(0, 120) }))
    } else {
      ElMessage.success(t('sync.pushOk', { n: r.pushed, tables: r.tables }))
    }
    await loadStatus()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    pushing.value = false
  }
}

async function restore() {
  try {
    await ElMessageBox.confirm(t('sync.restoreConfirm'), t('sync.restoreTitle'), {
      type: 'warning',
      confirmButtonText: t('sync.restoreBtn'),
    })
  } catch {
    return
  }
  try {
    const r = await syncApi.restore()
    if (r.ok) {
      ElMessage.success(t('sync.restoreDone', { backup: r.backup }))
    } else {
      ElMessage.error(t('sync.restoreFail', { msg: r.error ?? '' }))
    }
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <div class="sync-panel">
    <section class="glass sync-card">
      <h3>{{ t('sync.configTitle') }}</h3>
      <p class="desc">{{ t('sync.configDesc') }}</p>
      <el-form label-position="top">
        <div class="grid">
          <el-form-item :label="t('sync.host')">
            <el-input v-model="form.host" placeholder="192.168.1.10" />
          </el-form-item>
          <el-form-item :label="t('sync.port')">
            <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%" />
          </el-form-item>
          <el-form-item :label="t('sync.user')">
            <el-input v-model="form.user" />
          </el-form-item>
          <el-form-item :label="t('sync.password')">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              :placeholder="passwordSet ? t('sync.passwordKeep') : ''"
            />
          </el-form-item>
          <el-form-item :label="t('sync.database')">
            <el-input v-model="form.database" />
          </el-form-item>
          <el-form-item :label="t('sync.interval')">
            <el-input-number v-model="form.interval_min" :min="1" :max="1440" style="width: 100%" />
          </el-form-item>
        </div>
        <el-form-item :label="t('sync.enabled')">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <div class="row-gap">
        <el-button type="primary" class="btn-gradient" :loading="saving" @click="save">{{ t('common.save') }}</el-button>
        <el-button :loading="testing" @click="testConnection">{{ t('sync.test') }}</el-button>
        <el-button :icon="IconPush" :loading="pushing" @click="pushNow">{{ t('sync.pushNow') }}</el-button>
      </div>
    </section>

    <section class="glass sync-card">
      <header class="card-head">
        <h3>{{ t('sync.statusTitle') }}</h3>
        <el-button size="small" :icon="IconRefresh" circle @click="loadStatus" />
      </header>
      <el-table :data="tables" size="small" style="width: 100%">
        <el-table-column prop="table" :label="t('sync.colTable')" min-width="140" />
        <el-table-column :label="t('sync.colLastPush')" width="160">
          <template #default="{ row }">
            {{ (row.last_push_at ?? '—').replace('T', ' ').slice(0, 16) }}
          </template>
        </el-table-column>
        <el-table-column prop="rows_pushed" :label="t('sync.colRows')" width="90" />
        <el-table-column :label="t('sync.colStatus')" width="100">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.status === 'ok' ? 'success' : row.status === 'failed' ? 'danger' : 'info'"
            >
              {{ t(`sync.st.${row.status}`) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" :label="t('security.colDetail')" min-width="200" show-overflow-tooltip />
      </el-table>
    </section>

    <section class="glass sync-card danger-zone">
      <h3>{{ t('sync.restoreTitle') }}</h3>
      <p class="desc">{{ t('sync.restoreDesc') }}</p>
      <el-button type="danger" plain @click="restore">{{ t('sync.restoreBtn') }}</el-button>
    </section>
  </div>
</template>

<style scoped>
.sync-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.sync-card {
  padding: 14px 18px;
}
.sync-card h3 {
  margin: 0 0 4px;
  font-size: 14px;
}
.desc {
  margin: 0 0 10px;
  font-size: 12.5px;
  color: var(--p-muted);
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0 14px;
}
.row-gap {
  display: flex;
  gap: 8px;
  align-items: center;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.card-head h3 {
  margin: 0;
}
.danger-zone {
  border: 1px solid color-mix(in srgb, var(--el-color-danger) 30%, transparent);
}
@media (max-width: 1000px) {
  .grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
