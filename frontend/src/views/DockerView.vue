<script setup lang="ts">
/**
 * Docker 容器管理页（M08-1~4；dev-plan P12，可选模块）。
 * 列表（运行中排前）+ 生命周期操作（确认弹窗 + 后端审计）+ 尾部日志（轮询）+ 详情（脱敏）。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, InfoFilled, VideoPlay, VideoPause, RefreshRight } from '@element-plus/icons-vue'
import { dockerApi, type DockerContainer, type DockerDetail } from '../api/docker'

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
      <el-button size="small" @click="load">{{ t('notify.cert.refresh') }}</el-button>
    </header>

    <section class="glass list-card">
      <el-table :data="sorted" size="default" v-loading="loading">
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
    <el-dialog v-model="logDialog" :title="t('docker.logsTitle', { name: logName })" width="760px" @close="closeLogs">
      <pre ref="logBox" class="log-view">{{ logText || t('docker.logsEmpty') }}</pre>
      <template #footer>
        <el-button size="small" :loading="logLoading" @click="refreshLogs">{{ t('docker.logsRefresh') }}</el-button>
      </template>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog v-model="detailDialog" :title="t('docker.detailTitle', { name: detail?.name ?? '' })" width="680px">
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
