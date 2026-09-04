<script setup lang="ts">
/**
 * Docker 容器管理页（M08-1~4；dev-plan P12，可选模块）。
 * 列表（运行中排前）+ 生命周期操作（确认弹窗 + 后端审计）+ 尾部日志（轮询）+ 详情（脱敏）。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, InfoFilled, VideoPlay, VideoPause, RefreshRight } from '@element-plus/icons-vue'
import { dockerApi, dockerAdvancedApi, type DockerContainer, type DockerDetail, type DockerImage } from '../api/docker'

const { t } = useI18n()
const rows = ref<DockerContainer[]>([])
const loading = ref(false)

const sorted = computed(() =>
  [...rows.value].sort((a, b) => (a.state === 'running' ? 0 : 1) - (b.state === 'running' ? 0 : 1)),
)

async function load() {
  loading.value = true
  try {
    rows.value = await dockerApi.containers()
  } finally {
    loading.value = false
  }
}

// ---------- Docker 增强（P21.4/M08-5~8） ----------
const selected = ref<string[]>([])
const imgDialog = ref(false)
const images = ref<DockerImage[]>([])
const updDialog = ref(false)
const updates = ref<Array<{ tag: string; created_days_old: number }>>([])

async function batchOp(op: 'start' | 'stop' | 'restart') {
  if (!selected.value.length) {
    ElMessage.warning(t('docker.batchEmpty'))
    return
  }
  try {
    const r = await dockerAdvancedApi.batch(selected.value, op)
    ElMessage.success(t('docker.batchDone', { ok: r.ok_count, total: r.results.length }))
    selected.value = []
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function openImages() {
  imgDialog.value = true
  try {
    images.value = await dockerAdvancedApi.images()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function removeImage(img: DockerImage) {
  try {
    await dockerAdvancedApi.deleteImage(img.id, true)
    images.value = await dockerAdvancedApi.images()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function openUpdates() {
  updDialog.value = true
  try {
    updates.value = await dockerAdvancedApi.updates()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

onMounted(load)

function stateTag(s: string): 'success' | 'info' | 'danger' | 'warning' {
  if (s === 'running') return 'success'
  if (s === 'exited' || s === 'dead') return 'danger'
  if (s === 'paused') return 'warning'
  return 'info'
}

async function doOp(c: DockerContainer, op: 'start' | 'stop' | 'restart') {
  const ok = await ElMessageBox.confirm(t('docker.confirmOp', { name: c.name, op: t(`docker.op.${op}`) }), t('common.confirm'), {
    type: 'warning',
  }).then(
    () => true,
    () => false,
  )
  if (!ok) return
  try {
    await dockerApi.op(c.name, op)
    ElMessage.success(t('docker.opDone', { name: c.name, op: t(`docker.op.${op}`) }))
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

// ---------- 日志 ----------
const logDialog = ref(false)
const logName = ref('')
const logText = ref('')
const logLoading = ref(false)
let logTimer: number | undefined

async function openLogs(c: DockerContainer) {
  logName.value = c.name
  logText.value = ''
  logDialog.value = true
  await refreshLogs()
  logTimer = window.setInterval(refreshLogs, 4000)
}

async function refreshLogs() {
  if (!logName.value) return
  logLoading.value = true
  try {
    logText.value = (await dockerApi.logs(logName.value, 200)).logs
    await Promise.resolve()
    const box = document.querySelector('.log-view')
    if (box) box.scrollTop = box.scrollHeight
  } finally {
    logLoading.value = false
  }
}

function closeLogs() {
  window.clearInterval(logTimer)
  logName.value = ''
}

// ---------- 详情 ----------
const detailDialog = ref(false)
const detail = ref<DockerDetail | null>(null)

async function openDetail(c: DockerContainer) {
  try {
    detail.value = await dockerApi.detail(c.name)
    detailDialog.value = true
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}
</script>

<template>
  <div class="docker-page fade-up">
    <header class="page-head">
      <h2>{{ t('docker.title') }}</h2>
      <div class="head-btns">
        <el-button size="small" :disabled="!selected.length" @click="batchOp('restart')">
          {{ t('docker.batchRestart') }} ({{ selected.length }})
        </el-button>
        <el-button size="small" :disabled="!selected.length" type="danger" plain @click="batchOp('stop')">
          {{ t('docker.batchStop') }}
        </el-button>
        <el-button size="small" @click="openImages">{{ t('docker.images') }}</el-button>
        <el-button size="small" @click="openUpdates">{{ t('docker.updates') }}</el-button>
        <el-button size="small" @click="load">{{ t('notify.cert.refresh') }}</el-button>
      </div>
    </header>

    <section class="glass list-card">
      <el-table :data="sorted" size="default" v-loading="loading" @selection-change="(rows: DockerContainer[]) => (selected = rows.map((r) => r.name))">
        <el-table-column type="selection" width="42" />
        <el-table-column :label="t('docker.colName')" min-width="150">
          <template #default="{ row }"><span class="c-name">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column prop="image" :label="t('docker.colImage')" min-width="170" show-overflow-tooltip />
        <el-table-column :label="t('docker.colState')" width="150">
          <template #default="{ row }">
            <el-tag :type="stateTag(row.state)" size="small">{{ row.status || row.state }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="CPU" width="90" align="right">
          <template #default="{ row }">
            {{ row.cpu_percent !== undefined ? row.cpu_percent + '%' : '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="t('docker.colMem')" width="150" align="right">
          <template #default="{ row }">
            <template v-if="row.mem_used_mb !== undefined">{{ row.mem_used_mb }}MB · {{ row.mem_percent }}%</template>
            <template v-else>-</template>
          </template>
        </el-table-column>
        <el-table-column :label="t('ports.colActions')" width="240" align="right">
          <template #default="{ row }">
            <template v-if="row.state === 'running'">
              <el-button link size="small" :icon="VideoPause" @click="doOp(row, 'stop')">{{ t('docker.op.stop') }}</el-button>
              <el-button link size="small" :icon="RefreshRight" @click="doOp(row, 'restart')">
                {{ t('docker.op.restart') }}
              </el-button>
            </template>
            <el-button v-else link size="small" :icon="VideoPlay" @click="doOp(row, 'start')">
              {{ t('docker.op.start') }}
            </el-button>
            <el-button link size="small" :icon="Document" @click="openLogs(row)">{{ t('docker.logs') }}</el-button>
            <el-button link size="small" :icon="InfoFilled" @click="openDetail(row)">{{ t('docker.detail') }}</el-button>
          </template>
        </el-table-column>
        <template #empty>{{ t('docker.empty') }}</template>
      </el-table>
    </section>

    <!-- 日志对话框（尾部 + 轮询滚动） -->
    <el-dialog append-to-body v-model="logDialog" :title="t('docker.logsTitle', { name: logName })" width="760px" @close="closeLogs">
      <pre ref="logBox" class="log-view">{{ logText || t('docker.logsEmpty') }}</pre>
      <template #footer>
        <el-button size="small" :loading="logLoading" @click="refreshLogs">{{ t('docker.logsRefresh') }}</el-button>
      </template>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog append-to-body v-model="detailDialog" :title="t('docker.detailTitle', { name: detail?.name ?? '' })" width="680px">
      <template v-if="detail">
        <h4>{{ t('docker.colImage') }}</h4>
        <p class="mono">{{ detail.image }}</p>
        <h4>{{ t('docker.ports') }}</h4>
        <div v-if="detail.ports.length" class="kv-list">
          <div v-for="(p, i) in detail.ports" :key="i" class="kv mono">
            {{ p.host_ip || '0.0.0.0' }}:{{ p.host_port }} → {{ p.container }}
          </div>
        </div>
        <p v-else class="muted">{{ t('docker.none') }}</p>
        <h4>{{ t('docker.mounts') }}</h4>
        <div v-if="detail.mounts.length" class="kv-list">
          <div v-for="(m, i) in detail.mounts" :key="i" class="kv mono">{{ m.source }} → {{ m.destination }}</div>
        </div>
        <p v-else class="muted">{{ t('docker.none') }}</p>
        <h4>{{ t('docker.env') }}</h4>
        <div class="kv-list">
          <div v-for="e in detail.env" :key="e" class="kv mono">{{ e }}</div>
        </div>
      </template>
    </el-dialog>
    <!-- 镜像管理（M08-7） -->
    <el-dialog append-to-body v-model="imgDialog" :title="t('docker.imagesTitle')" width="640px">
      <el-table :data="images" size="small">
        <el-table-column :label="t('docker.colImage')" min-width="220">
          <template #default="{ row }">{{ (row.tags && row.tags[0]) || row.id }}</template>
        </el-table-column>
        <el-table-column :label="t('docker.imgCreated')" width="120">
          <template #default="{ row }">
            {{ new Date((row.created || 0) * 1000).toLocaleDateString() }}
          </template>
        </el-table-column>
        <el-table-column width="90" align="right">
          <template #default="{ row }">
            <el-button link size="small" type="danger" @click="removeImage(row)">{{ t('common.delete') }}</el-button>
          </template>
        </el-table-column>
        <template #empty>{{ t('common.noData') }}</template>
      </el-table>
    </el-dialog>

    <!-- 更新检测（M08-8） -->
    <el-dialog append-to-body v-model="updDialog" :title="t('docker.updatesTitle')" width="520px">
      <div v-if="!updates.length" class="muted">{{ t('docker.updatesNone') }}</div>
      <div v-for="u in updates" :key="u.tag" class="upd-row">
        <span>{{ u.tag }}</span>
        <el-tag size="small" type="warning">{{ t('docker.updateStale', { n: u.created_days_old }) }}</el-tag>
      </div>
      <p class="muted" style="margin-top: 8px">{{ t('docker.updatesTip') }}</p>
    </el-dialog>
  </div>
</template>

<style scoped>
.docker-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.page-head h2 {
  margin: 0;
}
.list-card {
  padding: 10px 14px 14px;
  border-radius: 12px;
}
.c-name {
  font-weight: 600;
}
.log-view {
  background: rgba(127, 127, 127, 0.1);
  border-radius: 8px;
  padding: 10px 12px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.5;
  max-height: 420px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 12.5px;
  word-break: break-all;
}
.kv-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}
.kv {
  padding: 5px 8px;
  background: rgba(127, 127, 127, 0.08);
  border-radius: 6px;
}
h4 {
  margin: 12px 0 6px;
  font-size: 13px;
}
.muted {
  color: var(--p-muted);
  font-size: 12.5px;
}
</style>
