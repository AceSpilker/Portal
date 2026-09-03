<script setup lang="ts">
/** 访问方式面板（M04-7/13；dev-plan P3.5/P3.6）：环境档案管理 + 连通性测试矩阵。 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { Delete as IconDelete, Edit as IconEdit, Plus as IconPlus } from '@element-plus/icons-vue'
import { networkApi } from '../api/network'
import type { MatrixResult, NetworkProfile } from '../api/network'
import type { AccessType } from '../api/portal'
import { useEnvStore } from '../stores/env'

const { t } = useI18n()
const envStore = useEnvStore()

const ACCESS_TYPES: AccessType[] = ['domain', 'lan', 'ssh', 'vpn', 'custom']

// ---- 环境档案（M04-7）----
const profiles = ref<NetworkProfile[]>([])
const loadingProfiles = ref(false)

async function loadProfiles() {
  loadingProfiles.value = true
  try {
    profiles.value = await networkApi.listProfiles()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loadingProfiles.value = false
  }
}

const dialog = ref(false)
const saving = ref(false)
const form = ref({
  id: undefined as number | undefined,
  name: '',
  match_type: 'cidr' as 'cidr' | 'default',
  cidrs: [] as string[],
  cidrInput: '',
  prefer_types: [] as AccessType[],
  sort: 0,
  enabled: true,
})

/** 已存在的默认兜底档案（新建/切换 default 时前端预检提示） */
const existingDefault = computed(() => profiles.value.find((p) => p.match_type === 'default'))

function openCreate() {
  form.value = {
    id: undefined,
    name: '',
    match_type: 'cidr',
    cidrs: [],
    cidrInput: '',
    prefer_types: [],
    sort: 0,
    enabled: true,
  }
  dialog.value = true
}

function openEdit(p: NetworkProfile) {
  form.value = {
    id: p.id,
    name: p.name,
    match_type: p.match_type,
    cidrs: [...p.cidrs],
    cidrInput: '',
    prefer_types: [...p.prefer_types],
    sort: p.sort,
    enabled: p.enabled,
  }
  dialog.value = true
}

function addCidr() {
  const v = form.value.cidrInput.trim()
  if (!v) return
  if (!form.value.cidrs.includes(v)) form.value.cidrs.push(v)
  form.value.cidrInput = ''
}

function removeCidr(cidr: string) {
  form.value.cidrs = form.value.cidrs.filter((c) => c !== cidr)
}

async function saveProfile() {
  if (!form.value.name.trim()) {
    ElMessage.warning(t('env.profileNamePh'))
    return
  }
  if (form.value.match_type === 'cidr' && !form.value.cidrs.length) {
    ElMessage.warning(t('env.cidrsPh'))
    return
  }
  if (
    form.value.match_type === 'default' &&
    existingDefault.value &&
    existingDefault.value.id !== form.value.id
  ) {
    ElMessage.warning(t('env.defaultExistsWarn'))
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      match_type: form.value.match_type,
      cidrs: form.value.match_type === 'default' ? [] : form.value.cidrs,
      prefer_types: form.value.prefer_types,
      sort: form.value.sort,
      enabled: form.value.enabled,
    }
    if (form.value.id) await networkApi.updateProfile(form.value.id, payload)
    else await networkApi.createProfile(payload)
    ElMessage.success(t('env.profileSaved'))
    dialog.value = false
    await loadProfiles()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function removeProfile(p: NetworkProfile) {
  try {
    await ElMessageBox.confirm(
      t('env.confirmDeleteProfile', { name: p.name }),
      t('common.delete'),
      { type: 'warning', confirmButtonText: t('common.delete') },
    )
  } catch {
    return
  }
  try {
    await networkApi.deleteProfile(p.id)
    ElMessage.success(t('env.profileDeleted'))
    await loadProfiles()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

const typeLabel = (v: AccessType) => t(`apps.urlType.${v}`)
const preferText = (p: NetworkProfile) => p.prefer_types.map(typeLabel).join(' → ')

// ---- 连通性测试矩阵（M04-13）----
const matrix = ref<MatrixResult | null>(null)
const probing = ref(false)

async function runMatrix() {
  probing.value = true
  try {
    matrix.value = await networkApi.matrix()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    probing.value = false
  }
}

const stateTag = (s: string) => (s === 'up' ? 'success' : s === 'down' ? 'danger' : 'info')
const stateText = (s: string) => t(`env.state${s[0].toUpperCase()}${s.slice(1)}`)

onMounted(loadProfiles)
</script>

<template>
  <div class="access-body">
    <!-- 环境探测调试（M04-18；P15.4）：当前来源 IP 与命中档案 -->
    <section class="glass" style="padding: 10px 14px; border-radius: 10px; font-size: 12.5px">
      <strong>{{ t('env.debugTitle') }}</strong>：
      {{ t('env.debugIp', { ip: envStore.clientIp }) }} ·
      {{ t('env.debugHit', { name: envStore.effective?.name ?? t('env.autoNone') }) }}
    </section>
    <!-- 环境档案管理 -->
    <section>
      <header class="sec-head">
        <div>
          <h3>{{ t('env.envTitle') }}</h3>
          <p>{{ t('env.envDesc') }}</p>
        </div>
        <el-button type="primary" class="btn-gradient" :icon="IconPlus" @click="openCreate">
          {{ t('common.add') }}
        </el-button>
      </header>
      <el-table :data="profiles" v-loading="loadingProfiles" class="profile-table">
        <el-table-column prop="name" :label="t('env.profileName')" min-width="110" />
        <el-table-column :label="t('env.matchType')" width="100">
          <template #default="{ row }">
            <el-tag :type="row.match_type === 'default' ? 'warning' : 'primary'" size="small">
              {{ row.match_type === 'default' ? t('env.matchDefault') : t('env.matchCidr') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('env.cidrs')" min-width="170">
          <template #default="{ row }">
            <span v-if="row.match_type === 'default'" class="muted">—</span>
            <span v-else class="cidr-cell">{{ row.cidrs.join('、') }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('env.preferTypes')" min-width="150">
          <template #default="{ row }">
            <span v-if="row.prefer_types.length" class="prefer-cell">{{ preferText(row) }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="sort" :label="t('env.sort')" width="70" />
        <el-table-column :label="t('common.enabled')" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '✓' : '✗' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('apps.thActions')" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link size="small" :icon="IconEdit" @click="openEdit(row)" />
            <el-button link size="small" type="danger" :icon="IconDelete" @click="removeProfile(row)" />
          </template>
        </el-table-column>
      </el-table>
      <p class="hint">{{ t('env.matchOrderHint') }}</p>
    </section>

    <!-- 连通性测试矩阵 -->
    <section>
      <header class="sec-head">
        <div>
          <h3>{{ t('env.matrixTitle') }}</h3>
          <p>{{ t('env.matrixDesc') }}</p>
        </div>
        <el-button type="primary" class="btn-gradient" :loading="probing" @click="runMatrix">
          {{ probing ? t('env.matrixRunning') : t('env.matrixRun') }}
        </el-button>
      </header>
      <p v-if="matrix" class="muted probe-at">
        {{ t('env.matrixAt', { time: new Date(matrix.probed_at).toLocaleString() }) }}
      </p>
      <el-table v-if="matrix" :data="matrix.apps" class="matrix-table">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="matrix-urls">
              <div v-for="u in row.urls" :key="u.id" class="matrix-url">
                <el-tag :type="stateTag(u.state)" size="small" class="state-tag">
                  {{ stateText(u.state) }}
                </el-tag>
                <el-tag size="small" type="info">{{ typeLabel(u.access_type) }}</el-tag>
                <span class="u-url">{{ u.url }}</span>
                <span v-if="u.latency_ms !== null" class="u-latency">
                  {{ t('env.latencyMs', { n: u.latency_ms }) }}
                </span>
              </div>
              <p v-if="!row.urls.length" class="muted">{{ t('apps.noEntry') }}</p>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" :label="t('apps.thApp')" min-width="140" />
        <el-table-column :label="t('apps.thUrls')" min-width="220">
          <template #default="{ row }">
            <span class="muted">{{ row.urls.length }}</span>
          </template>
        </el-table-column>
      </el-table>
      <p v-else class="muted">{{ t('common.noData') }}</p>
    </section>

    <!-- 新增/编辑环境档案 -->
    <el-dialog
      v-model="dialog"
      :title="form.id ? t('env.profileName') : t('common.add')"
      width="480px"
      append-to-body
    >
      <el-form label-position="top">
        <el-form-item :label="t('env.profileName')">
          <el-input v-model="form.name" :placeholder="t('env.profileNamePh')" maxlength="64" />
        </el-form-item>
        <el-form-item :label="t('env.matchType')">
          <el-radio-group v-model="form.match_type">
            <el-radio-button value="cidr">{{ t('env.matchCidr') }}</el-radio-button>
            <el-radio-button value="default" :disabled="!!existingDefault && existingDefault.id !== form.id">
              {{ t('env.matchDefault') }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.match_type === 'cidr'" :label="t('env.cidrs')">
          <div class="cidr-editor">
            <el-tag
              v-for="c in form.cidrs"
              :key="c"
              closable
              class="cidr-tag"
              @close="removeCidr(c)"
            >
              {{ c }}
            </el-tag>
            <el-input
              v-model="form.cidrInput"
              :placeholder="t('env.cidrsPh')"
              size="small"
              class="cidr-input"
              @keyup.enter="addCidr"
            />
          </div>
        </el-form-item>
        <el-form-item :label="t('env.preferTypes')">
          <el-select v-model="form.prefer_types" multiple clearable style="width: 100%">
            <el-option
              v-for="tp in ACCESS_TYPES"
              :key="tp"
              :label="typeLabel(tp)"
              :value="tp"
            />
          </el-select>
        </el-form-item>
        <div class="form-row">
          <el-form-item :label="t('env.sort')">
            <el-input-number v-model="form.sort" :min="-999" :max="999" />
          </el-form-item>
          <el-form-item :label="t('common.enabled')">
            <el-switch v-model="form.enabled" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" class="btn-gradient" :loading="saving" @click="saveProfile">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.access-body {
  display: flex;
  flex-direction: column;
  gap: 28px;
}
.sec-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.sec-head h3 {
  margin: 0 0 6px;
  font-size: 16px;
}
.sec-head p {
  margin: 0;
  color: var(--p-muted);
  font-size: 13px;
  max-width: 560px;
}
.hint,
.muted {
  color: var(--p-muted);
  font-size: 12.5px;
}
.hint {
  margin: 8px 2px 0;
}
.cidr-cell,
.prefer-cell {
  font-size: 12.5px;
}
.probe-at {
  margin: 0 0 8px;
}
.matrix-urls {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 12px;
}
.matrix-url {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}
.state-tag {
  width: 44px;
  justify-content: center;
}
.u-url {
  word-break: break-all;
}
.u-latency {
  margin-left: auto;
  color: var(--p-muted);
  white-space: nowrap;
}
.cidr-editor {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  width: 100%;
}
.cidr-tag {
  font-size: 12px;
}
.cidr-input {
  width: 210px;
}
.form-row {
  display: flex;
  gap: 24px;
}
</style>