<script setup lang="ts">
/**
 * SSH 隧道面板（M04-16；dev-plan P20.1/P20.2）：
 * 凭据库（密码/私钥，密文存储）+ 隧道列表（启动/停止/断线重连/空闲回收）+ 直达链接。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete as IconDelete, Link as IconLink, Plus as IconPlus } from '@element-plus/icons-vue'
import { tunnelsApi, type SSHCredential, type Tunnel } from '../api/tunnels'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const auth = useAuthStore()

const creds = ref<SSHCredential[]>([])
const tunnels = ref<Tunnel[]>([])
const loading = ref(false)

const credDlg = ref(false)
const credForm = reactive({ name: '', host: '', port: 22, username: 'root', password: '', private_key: '', note: '' })
const tunDlg = ref(false)
const tunForm = reactive({ name: '', credential_id: null as number | null, remote_host: '127.0.0.1', remote_port: 80, auto_close_min: 30 })

async function load() {
  if (!auth.isAdmin) return
  loading.value = true
  try {
    creds.value = await tunnelsApi.listCredentials()
    tunnels.value = await tunnelsApi.list()
  } catch {
    /* 非管理员/接口异常静默 */
  } finally {
    loading.value = false
  }
}

const STATUS_TAG: Record<string, 'success' | 'info' | 'warning' | 'danger'> = {
  running: 'success',
  stopped: 'info',
  error: 'danger',
  degraded: 'warning',
}

function openCredDlg() {
  Object.assign(credForm, { name: '', host: '', port: 22, username: 'root', password: '', private_key: '', note: '' })
  credDlg.value = true
}

async function saveCred() {
  if (!credForm.name.trim() || !credForm.host.trim() || (!credForm.password && !credForm.private_key)) {
    ElMessage.warning(t('tunnel.credRequired'))
    return
  }
  try {
    await tunnelsApi.createCredential({ ...credForm })
    credDlg.value = false
    ElMessage.success(t('common.save'))
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function removeCred(c: SSHCredential) {
  try {
    await ElMessageBox.confirm(t('tunnel.credDeleteConfirm', { name: c.name }), t('common.confirm'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await tunnelsApi.deleteCredential(c.id)
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function openTunDlg() {
  if (!creds.value.length) {
    ElMessage.warning(t('tunnel.needCred'))
    return
  }
  Object.assign(tunForm, { name: '', credential_id: creds.value[0]!.id, remote_host: '127.0.0.1', remote_port: 80, auto_close_min: 30 })
  tunDlg.value = true
}

async function saveTunnel(startNow = false) {
  if (!tunForm.name.trim()) {
    ElMessage.warning(t('eff.nameRequired'))
    return
  }
  try {
    const created = await tunnelsApi.create({
      name: tunForm.name.trim(),
      credential_id: tunForm.credential_id ?? 0,
      remote_host: tunForm.remote_host,
      remote_port: tunForm.remote_port,
      auto_close_min: tunForm.auto_close_min,
    })
    if (startNow) await tunnelsApi.start(created.id)
    tunDlg.value = false
    ElMessage.success(t('common.save'))
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function toggleTunnel(t: Tunnel) {
  try {
    if (t.status === 'running') await tunnelsApi.stop(t.id)
    else await tunnelsApi.start(t.id)
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function removeTunnel(tun: Tunnel) {
  try {
    await ElMessageBox.confirm(t('tunnel.deleteConfirm', { name: tun.name }), t('common.confirm'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await tunnelsApi.remove(tun.id)
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function openDirect(t: Tunnel) {
  try {
    const r = await tunnelsApi.openUrl(t.id)
    window.open(r.url, '_blank')
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

const canManage = computed(() => auth.isAdmin)

onMounted(load)
</script>

<template>
  <div class="tunnels">
    <section class="glass tun-card">
      <header class="card-head">
        <h3>{{ t('tunnel.credsTitle') }}</h3>
        <el-button v-if="canManage" size="small" type="primary" class="btn-gradient" :icon="IconPlus" @click="openCredDlg">
          {{ t('tunnel.credAdd') }}
        </el-button>
      </header>
      <el-table :data="creds" size="small" style="width: 100%">
        <el-table-column prop="name" :label="t('security.colName')" min-width="120" />
        <el-table-column :label="t('tunnel.sshTarget')" min-width="180">
          <template #default="{ row }">{{ row.username }}@{{ row.host }}:{{ row.port }}</template>
        </el-table-column>
        <el-table-column width="90" align="right">
          <template #default="{ row }">
            <el-button v-if="canManage" link size="small" type="danger" :icon="IconDelete" @click="removeCred(row)" />
          </template>
        </el-table-column>
        <template #empty>{{ t('common.noData') }}</template>
      </el-table>
    </section>

    <section class="glass tun-card">
      <header class="card-head">
        <h3>{{ t('tunnel.tunnelsTitle') }}</h3>
        <el-button v-if="canManage" size="small" type="primary" class="btn-gradient" :icon="IconLink" @click="openTunDlg">
          {{ t('tunnel.tunnelAdd') }}
        </el-button>
      </header>
      <el-table :data="tunnels" size="small" style="width: 100%">
        <el-table-column prop="name" :label="t('security.colName')" min-width="130" />
        <el-table-column :label="t('tunnel.target')" min-width="180">
          <template #default="{ row }">{{ row.remote_host }}:{{ row.remote_port }}</template>
        </el-table-column>
        <el-table-column :label="t('tunnel.localPort')" width="100">
          <template #default="{ row }">{{ row.status === 'running' ? row.local_port : '—' }}</template>
        </el-table-column>
        <el-table-column :label="t('tunnel.status')" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_TAG[row.status] ?? 'info'">{{ t(`tunnel.st.${row.status}`) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column width="190" align="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'running'" link size="small" @click="openDirect(row)">
              {{ t('tunnel.openDirect') }}
            </el-button>
            <el-button link size="small" @click="toggleTunnel(row)">
              {{ row.status === 'running' ? t('tunnel.stop') : t('tunnel.start') }}
            </el-button>
            <el-button v-if="canManage" link size="small" type="danger" :icon="IconDelete" @click="removeTunnel(row)" />
          </template>
        </el-table-column>
        <template #empty>{{ t('common.noData') }}</template>
      </el-table>
    </section>

    <!-- 凭据对话框 -->
    <el-dialog v-model="credDlg" :title="t('tunnel.credAdd')" width="440px" append-to-body>
      <el-form label-position="top">
        <el-form-item :label="t('security.colName')"><el-input v-model="credForm.name" maxlength="60" /></el-form-item>
        <div class="row">
          <el-form-item :label="t('redis.host')"><el-input v-model="credForm.host" /></el-form-item>
          <el-form-item :label="t('redis.port')"><el-input-number v-model="credForm.port" :min="1" :max="65535" /></el-form-item>
        </div>
        <el-form-item :label="t('settings.effUser')"><el-input v-model="credForm.username" /></el-form-item>
        <el-form-item :label="t('settings.effPass')">
          <el-input v-model="credForm.password" type="password" show-password :placeholder="t('tunnel.passOrKey')" />
        </el-form-item>
        <el-form-item :label="t('tunnel.privateKey')">
          <el-input v-model="credForm.private_key" type="textarea" :rows="3" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="credDlg = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="saveCred">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- 隧道对话框 -->
    <el-dialog v-model="tunDlg" :title="t('tunnel.tunnelAdd')" width="460px" append-to-body>
      <el-form label-position="top">
        <el-form-item :label="t('security.colName')"><el-input v-model="tunForm.name" maxlength="60" /></el-form-item>
        <el-form-item :label="t('tunnel.cred')">
          <el-select v-model="tunForm.credential_id" style="width: 100%">
            <el-option v-for="c in creds" :key="c.id" :value="c.id" :label="`${c.name}（${c.host}）`" />
          </el-select>
        </el-form-item>
        <div class="row">
          <el-form-item :label="t('tunnel.remoteHost')"><el-input v-model="tunForm.remote_host" /></el-form-item>
          <el-form-item :label="t('tunnel.remotePort')"><el-input-number v-model="tunForm.remote_port" :min="1" :max="65535" /></el-form-item>
        </div>
        <el-form-item :label="t('tunnel.autoClose')">
          <el-input-number v-model="tunForm.auto_close_min" :min="0" :max="1440" />
          <span class="tip">{{ t('tunnel.autoCloseTip') }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tunDlg = false">{{ t('common.cancel') }}</el-button>
        <el-button @click="saveTunnel(true)">{{ t('common.save') }}+{{ t('tunnel.start') }}</el-button>
        <el-button type="primary" class="btn-gradient" @click="saveTunnel(false)">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tunnels {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.tun-card {
  padding: 14px 18px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.card-head h3 {
  margin: 0;
  font-size: 14px;
}
.row {
  display: flex;
  gap: 10px;
}
.row .el-form-item {
  flex: 1;
}
.tip {
  margin-left: 8px;
  font-size: 12px;
  color: var(--p-muted);
}
</style>
